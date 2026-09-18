"""Adding ``submissions.course_id`` to a database that already holds grades.

This is the first migration in ``plans/multicourse.md`` that writes to the
database rather than moving files, and it runs on boot against the live
portal's table of real student submissions.  So the tests here start from a
database built with the **pre-phase-3 schema** -- every column the table has
today except ``course_id`` -- put rows in it, and check what survives.

Three properties, in order of how expensive they would be to get wrong:

* existing rows keep every value they had and gain the default course id;
* a second boot changes nothing -- the backfill is once per database, ever;
* a row written outside any course stays NULL and is never adopted later.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.services.course_registry import CourseRegistry
from llmgrader.services.grader import Grader
from llmgrader.services.portal_storage import PortalStorage

# The same realistic package tests/services/test_course_registry_migration.py
# migrates from: two units, no <course_id>, so the id is slugged from <name>
# and <semester>.
LEGACY_PACKAGE = Path(__file__).resolve().parents[2] / "soln_repos"
LEGACY_COURSE_ID = "demo-class-spring-2026"

# One pre-upgrade row, spelled out so the assertions can compare values rather
# than merely count rows.  A migration that silently blanked a column would
# pass a row count.
LEGACY_ROW = {
    "timestamp": "2026-09-01T12:00:00+00:00",
    "client_id": "a1b2c3d4",
    "unit_name": "Unit 1:  Calculus Review",
    "qtag": "Exponential derivative",
    "part_label": "all",
    "required": 1,
    "partial_credit": 0,
    "question_text": "Differentiate exp(3x).",
    "ref_soln": "3 exp(3x)",
    "grading_notes": "Chain rule.",
    "student_soln": "An answer from before the upgrade",
    "model": "gpt-5.6-luna",
    "timeout": 60.0,
    "latency_ms": 1234,
    "timed_out": 0,
    "tokens_in": 800,
    "tokens_out": 120,
    "used_admin_key": 1,
    "raw_prompt": "the prompt as sent",
    "result": "pass",
    "full_explanation": "Correct.",
    "feedback": "Nice work.",
    "points": 1.0,
    "max_points": 1.0,
}


def pre_phase3_columns() -> list[str]:
    """The submissions columns as they stood before this phase.

    Derived from the live schema rather than hard-coded, so a later column
    addition does not quietly turn this fixture into a much older database
    than the one the migration actually has to handle.
    """
    return [name for name in PortalStorage.DB_SCHEMA if name != "course_id"]


def create_pre_phase3_database(db_path: Path, rows: list[dict]) -> None:
    """Build a submissions table with no course_id and put *rows* in it."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    columns = pre_phase3_columns()

    defs = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
    defs += [f"{name} {PortalStorage.DB_SCHEMA[name]}" for name in columns]

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"CREATE TABLE submissions ({', '.join(defs)})")
        placeholders = ", ".join(f":{name}" for name in columns)
        for row in rows:
            record = {name: row.get(name) for name in columns}
            conn.execute(
                f"INSERT INTO submissions ({', '.join(columns)}) VALUES ({placeholders})",
                record,
            )
        conn.commit()
    finally:
        conn.close()


def read_rows(db_path: Path, columns: list[str] | None = None) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        selection = ", ".join(columns) if columns else "*"
        return [dict(row) for row in conn.execute(
            f"SELECT {selection} FROM submissions ORDER BY id"
        )]
    finally:
        conn.close()


def migration_rows(db_path: Path) -> list[tuple]:
    """The migration ledger, or [] when nothing has created it yet."""
    conn = sqlite3.connect(db_path)
    try:
        return list(conn.execute("SELECT name, detail FROM portal_migrations ORDER BY name"))
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


@pytest.fixture()
def legacy_storage(tmp_path: Path, monkeypatch) -> Path:
    """A storage disk carrying graded work, from before the column existed.

    ``<storage>/soln_pkg`` is the pre-registry package layout, so booting a
    registry against this tree exercises the same path the deployed portal
    takes: migrate the package into ``courses/<id>/``, settle on a default,
    then stamp the rows that came with it.
    """
    root = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(root))
    monkeypatch.delenv("LLMGRADER_MIGRATE_COURSE_ID", raising=False)

    shutil.copytree(LEGACY_PACKAGE, root / "soln_pkg")
    create_pre_phase3_database(root / "db" / "llmgrader.db", [LEGACY_ROW])
    return root


@pytest.fixture()
def legacy_db(legacy_storage: Path) -> Path:
    return legacy_storage / "db" / "llmgrader.db"


# ---------------------------------------------------------------------------
# The migration itself
# ---------------------------------------------------------------------------


def test_the_column_is_added_to_an_existing_database(legacy_storage: Path, legacy_db: Path) -> None:
    assert "course_id" not in read_rows(legacy_db)[0]

    CourseRegistry()

    assert "course_id" in read_rows(legacy_db)[0]


def test_existing_rows_keep_every_value_they_had(legacy_db: Path) -> None:
    """The row must come through the migration byte for byte."""
    before = read_rows(legacy_db)[0]

    CourseRegistry()

    after = read_rows(legacy_db)[0]
    for column, value in before.items():
        assert after[column] == value, f"{column} changed during the migration"


def test_existing_rows_gain_the_default_course_id(legacy_db: Path) -> None:
    registry = CourseRegistry()

    assert registry.default_course_id == LEGACY_COURSE_ID
    assert [row["course_id"] for row in read_rows(legacy_db)] == [LEGACY_COURSE_ID]


def test_the_course_index_is_created(legacy_db: Path) -> None:
    CourseRegistry()

    conn = sqlite3.connect(legacy_db)
    try:
        indexes = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'submissions'"
            )
        ]
    finally:
        conn.close()

    assert "idx_submissions_course" in indexes


def test_the_backfill_is_recorded(legacy_db: Path) -> None:
    """One ledger row, naming what it did, so the boot is auditable."""
    CourseRegistry()

    recorded = migration_rows(legacy_db)
    assert [name for name, _ in recorded] == [PortalStorage.MIGRATION_COURSE_ID_BACKFILL]
    assert LEGACY_COURSE_ID in recorded[0][1]


# ---------------------------------------------------------------------------
# Booting again
# ---------------------------------------------------------------------------


def test_a_second_boot_does_not_backfill_again(legacy_db: Path) -> None:
    CourseRegistry()
    first = read_rows(legacy_db)

    CourseRegistry()

    assert read_rows(legacy_db) == first
    assert len(migration_rows(legacy_db)) == 1


def test_a_second_boot_does_not_adopt_rows_written_since(legacy_db: Path) -> None:
    """The reason the backfill is once-per-database and not "every NULL row".

    A submission graded outside any course -- ``llmgrader_test``, the replay
    tool -- lands with course_id NULL deliberately.  Re-running the backfill on
    the next boot would file it under a course it was never graded against,
    and nothing downstream would ever flag that.
    """
    CourseRegistry()

    storage = PortalStorage()
    storage.insert_submission(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        unit_name="unit1",
        qtag="q1",
        student_soln="graded with no course",
    )

    CourseRegistry()

    by_answer = {row["student_soln"]: row["course_id"] for row in read_rows(legacy_db)}
    assert by_answer["An answer from before the upgrade"] == LEGACY_COURSE_ID
    assert by_answer["graded with no course"] is None


def test_a_fresh_database_is_born_with_nothing_to_backfill(tmp_path: Path, monkeypatch) -> None:
    """A table created from DB_SCHEMA has the column, so no row predates it."""
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))

    storage = PortalStorage()

    assert storage.migration_applied(PortalStorage.MIGRATION_COURSE_ID_BACKFILL)
    assert storage.backfill_course_id("intro_prob") == 0


def test_backfill_returns_zero_once_it_has_run(legacy_db: Path) -> None:
    """The count is the number of rows stamped, and it only counts once."""
    storage = PortalStorage()

    assert storage.backfill_course_id(LEGACY_COURSE_ID) == 1
    assert storage.backfill_course_id(LEGACY_COURSE_ID) == 0
    assert storage.backfill_course_id("some-other-course") == 0
    assert [row["course_id"] for row in read_rows(legacy_db)] == [LEGACY_COURSE_ID]


def test_backfill_without_a_course_stays_unmarked(legacy_db: Path) -> None:
    """A portal with no default course must not burn its one chance."""
    storage = PortalStorage()

    assert storage.backfill_course_id("") == 0
    assert migration_rows(legacy_db) == []

    assert storage.backfill_course_id(LEGACY_COURSE_ID) == 1


# ---------------------------------------------------------------------------
# Writing the column
# ---------------------------------------------------------------------------


class _FakeRawResponse:
    def model_dump(self):
        return {"result": "pass", "full_explanation": "ok", "feedback": "ok"}


class _FakeProcessedResult:
    def model_dump(self):
        return {
            "result": "pass",
            "full_explanation": "ok",
            "feedback": "ok",
            "point_parts": None,
            "max_point_parts": 1.0,
            "result_parts": "pass",
            "points": None,
            "max_points": 1.0,
        }


def _grade_once(grader: Grader) -> None:
    grader.grade(
        question_dict={
            "question_text": "Question",
            "solution": "Solution",
            "grading_notes": "Notes",
            "required": True,
            "partial_credit": False,
            "tools": [],
            "parts": [{"part_label": "all", "points": 1.0}],
            "rubrics": {},
            "rubric_total": None,
        },
        student_soln="My answer",
        unit_name="unit1",
        qtag="q1",
        provider="openai",
        model="gpt-5.4-mini",
        api_key="test-key",
        session_id="a1b2c3d4",
    )


@pytest.fixture()
def fake_grading(monkeypatch):
    monkeypatch.setattr(Grader, "load_unit_pkg", lambda self: None)
    monkeypatch.setattr(
        Grader,
        "build_task_prompt",
        lambda self, question_dict, student_soln, part_label="all": ("task", 1.0),
    )
    monkeypatch.setattr(
        Grader,
        "_make_llm_caller",
        lambda self, *args, **kwargs: (lambda: (_FakeRawResponse(), 11, 7, "")),
    )
    monkeypatch.setattr(
        Grader, "grade_post_process", lambda self, *args, **kwargs: _FakeProcessedResult()
    )


@pytest.mark.parametrize("course_id", ["intro_prob", None])
def test_the_grading_path_writes_the_graders_course(
    tmp_path: Path, monkeypatch, fake_grading, course_id
) -> None:
    """A Grader with a course stamps it; one without writes NULL, not a guess."""
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))

    grader = Grader(
        scratch_dir=str(tmp_path / "scratch"),
        soln_pkg=str(tmp_path / "pkg"),
        course_id=course_id,
    )
    _grade_once(grader)

    conn = sqlite3.connect(grader.db_path)
    try:
        row = conn.execute(
            "SELECT course_id FROM submissions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row == (course_id,)


def test_a_null_course_row_survives_a_later_backfill(
    tmp_path: Path, monkeypatch, fake_grading
) -> None:
    """End to end: grade with no course, then boot a registry over the same DB."""
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage_root))
    monkeypatch.delenv("LLMGRADER_MIGRATE_COURSE_ID", raising=False)
    shutil.copytree(LEGACY_PACKAGE, storage_root / "soln_pkg")

    grader = Grader(
        scratch_dir=str(tmp_path / "scratch"),
        soln_pkg=str(tmp_path / "pkg"),
        course_id=None,
    )
    _grade_once(grader)

    registry = CourseRegistry()
    assert registry.default_course_id == LEGACY_COURSE_ID

    rows = read_rows(storage_root / "db" / "llmgrader.db")
    assert [row["course_id"] for row in rows] == [None]


# ---------------------------------------------------------------------------
# The column reaches the Analytics view
# ---------------------------------------------------------------------------


def test_dbviewer_schema_offers_course_id(tmp_path: Path, monkeypatch) -> None:
    """The column reference reads the live table, so it needs no change here.

    Asserting it rather than assuming it: the endpoint's whole reason for
    reading PRAGMA table_info instead of DB_SCHEMA (routes/api.py) is that the
    two can disagree, and a new column is exactly when they might.
    """
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    app = create_app(scratch_dir=str(scratch), soln_pkg=str(LEGACY_PACKAGE))
    app.config["TESTING"] = True

    payload = app.test_client().get("/admin/dbviewer/schema").get_json()

    assert payload["error"] is None
    tables = {table["name"]: table["columns"] for table in payload["tables"]}
    assert "course_id" in tables["submissions"]


def test_the_served_course_id_reaches_the_page(tmp_path: Path, monkeypatch) -> None:
    """index.html carries the id the Analytics default query filters on."""
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    app = create_app(scratch_dir=str(scratch), soln_pkg=str(LEGACY_PACKAGE))
    app.config["TESTING"] = True

    # "/" now redirects into the course rather than rendering it, so follow it.
    html = app.test_client().get("/", follow_redirects=True).get_data(as_text=True)

    assert f'window.LLMGRADER_COURSE_ID = "{LEGACY_COURSE_ID}"' in html
