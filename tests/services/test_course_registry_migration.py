"""Booting a portal that was deployed before courses existed.

The live portal's storage disk holds ``<storage>/soln_pkg`` and nothing under
``<storage>/courses/``.  Merging phase 2 must bring it back up with its course
intact and no admin action (``plans/multicourse.md``, decision 3), so these
tests run against a realistic legacy tree rather than a stub: ``soln_repos/``
is a real extracted package -- the flat, destination-named layout a
``soln_package.zip`` unzips into -- with two units, no ``<course_id>``, and a
database with a submission row already in it.

That missing ``<course_id>`` is the point.  The package predates the field by
definition, so the migration is exactly where the ``<name>`` + ``<semester>``
fallback has to work.
"""

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from llmgrader.services.course_registry import (
    ID_SOURCE_AUTHORED,
    ID_SOURCE_DERIVED,
    ID_SOURCE_ENV,
    MIGRATE_COURSE_ID_ENV,
    CourseRegistry,
)
from llmgrader.services.portal_storage import PortalStorage

LEGACY_PACKAGE = Path(__file__).resolve().parents[2] / "soln_repos"

# soln_repos/llmgrader_config.xml: <name>Demo Class</name>, <semester>Spring 2026</semester>,
# and no <course_id>.
LEGACY_COURSE_ID = "demo-class-spring-2026"


@pytest.fixture()
def legacy_storage(tmp_path: Path, monkeypatch) -> Path:
    """A storage disk as a deployed portal leaves it before this change.

    ``<storage>/soln_pkg`` extracted in place, the global database with a row
    in it, admin preferences and the student image store -- all of which must
    come through untouched.
    """
    root = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(root))

    shutil.copytree(LEGACY_PACKAGE, root / "soln_pkg")

    storage = PortalStorage()
    storage.insert_submission(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        client_id="a1b2c3d4",
        unit_name="Unit 1:  Calculus Review",
        qtag="Exponential derivative",
        student_soln="An answer from before the upgrade",
        model="gpt-5.6-luna",
        points=1.0,
        max_points=1.0,
    )
    Path(storage.get_admin_pref_path()).write_text(
        json.dumps({"tokenLimit": 5000}), encoding="utf-8"
    )
    Path(storage.get_soln_images_path(), "keep_me.png").write_bytes(b"not really a png")

    return root


def test_the_legacy_package_becomes_a_registered_course(legacy_storage: Path) -> None:
    registry = CourseRegistry()

    assert registry.default_course_id == LEGACY_COURSE_ID
    entry = registry.get(LEGACY_COURSE_ID)
    assert entry.name == "Demo Class"
    assert entry.semester == "Spring 2026"
    assert entry.id_source == ID_SOURCE_DERIVED   # no <course_id> to author from

    payload = json.loads((legacy_storage / "courses" / "courses.json").read_text())
    assert payload["default"] == LEGACY_COURSE_ID
    assert [row["id"] for row in payload["courses"]] == [LEGACY_COURSE_ID]


def test_the_package_is_moved_not_copied(legacy_storage: Path) -> None:
    CourseRegistry()

    moved = legacy_storage / "courses" / LEGACY_COURSE_ID / "soln_pkg"
    assert (moved / "llmgrader_config.xml").exists()
    assert (moved / "unit1_calculus.xml").exists()
    assert not (legacy_storage / "soln_pkg").exists()


def test_the_course_still_serves_its_units(legacy_storage: Path) -> None:
    """The one assertion the deploy actually rests on."""
    grader = CourseRegistry().default_grader()

    assert list(grader.units) == ["Unit 1:  Calculus Review", "Unit 2:  Python and ML"]
    assert grader.unit_validation_errors == []
    assert grader.course_info["name"] == "Demo Class"
    assert grader.soln_pkg == str(
        legacy_storage / "courses" / LEGACY_COURSE_ID / "soln_pkg"
    )


def test_global_storage_is_untouched(legacy_storage: Path) -> None:
    """Migrating a course must not disturb what every course shares."""
    registry = CourseRegistry()
    storage = registry.storage

    conn = sqlite3.connect(storage.db_path)
    rows = conn.execute("SELECT unit_name, student_soln FROM submissions").fetchall()
    conn.close()

    assert rows == [("Unit 1:  Calculus Review", "An answer from before the upgrade")]
    assert json.loads(Path(storage.get_admin_pref_path()).read_text())["tokenLimit"] == 5000
    assert Path(storage.get_soln_images_path(), "keep_me.png").exists()


def test_the_second_boot_re_reads_rather_than_re_migrating(legacy_storage: Path) -> None:
    first = CourseRegistry()
    created_at = first.get(LEGACY_COURSE_ID).created_at

    second = CourseRegistry()

    assert second.default_course_id == LEGACY_COURSE_ID
    assert second.get(LEGACY_COURSE_ID).created_at == created_at   # not re-registered
    assert second.default_grader().units


def test_a_stray_legacy_directory_never_overwrites_a_live_registry(
    legacy_storage: Path,
) -> None:
    """Once courses.json exists, <storage>/soln_pkg is left alone, not merged."""
    CourseRegistry()
    (legacy_storage / "soln_pkg").mkdir()
    (legacy_storage / "soln_pkg" / "llmgrader_config.xml").write_text("<llmgrader/>")

    registry = CourseRegistry()

    assert registry.migrate_legacy_layout() is None
    assert (legacy_storage / "soln_pkg" / "llmgrader_config.xml").exists()
    assert registry.default_grader().units


# ---------------------------------------------------------------------------
# LLMGRADER_MIGRATE_COURSE_ID -- naming the course at the upgrade deploy
# ---------------------------------------------------------------------------
#
# Without it the live portal's id is slugged from display text, and that slug
# is permanent: it goes into the URL, into submissions.course_id and into every
# student's localStorage key, and changing it later is a three-store migration.
# The deployed package cannot author a <course_id> -- it predates the field --
# so the upgrade deploy is the only chance to name the course properly.


def test_env_var_names_the_migrated_course(legacy_storage: Path, monkeypatch) -> None:
    monkeypatch.setenv(MIGRATE_COURSE_ID_ENV, "hwdesign")

    registry = CourseRegistry()

    assert registry.default_course_id == "hwdesign"
    assert registry.get("hwdesign").id_source == ID_SOURCE_ENV
    # The display name still comes from the package; only the id is overridden.
    assert registry.get("hwdesign").name == "Demo Class"
    assert (legacy_storage / "courses" / "hwdesign" / "soln_pkg").is_dir()
    assert not (legacy_storage / "courses" / LEGACY_COURSE_ID).exists()


def test_env_var_is_read_once_and_then_ignored(legacy_storage: Path, monkeypatch) -> None:
    """Once recorded, courses.json wins -- so the var can be left set or removed."""
    monkeypatch.setenv(MIGRATE_COURSE_ID_ENV, "hwdesign")
    CourseRegistry()

    monkeypatch.setenv(MIGRATE_COURSE_ID_ENV, "something_else_entirely")
    registry = CourseRegistry()

    assert registry.default_course_id == "hwdesign"
    assert not (legacy_storage / "courses" / "something_else_entirely").exists()


def test_an_authored_course_id_beats_the_env_var(legacy_storage: Path, monkeypatch) -> None:
    """A package that names itself is the authority; the var is for ones that cannot."""
    config = legacy_storage / "soln_pkg" / "llmgrader_config.xml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "<course>", "<course>\n    <course_id>authored_id</course_id>", 1
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(MIGRATE_COURSE_ID_ENV, "hwdesign")

    registry = CourseRegistry()

    assert registry.default_course_id == "authored_id"
    assert registry.get("authored_id").id_source == ID_SOURCE_AUTHORED


def test_an_invalid_env_var_is_ignored_rather_than_fatal(
    legacy_storage: Path, monkeypatch, capsys
) -> None:
    """A typo in an env var must not stop a live portal coming back up."""
    monkeypatch.setenv(MIGRATE_COURSE_ID_ENV, "Not A Valid Id")

    registry = CourseRegistry()

    assert registry.default_course_id == LEGACY_COURSE_ID
    assert registry.get(LEGACY_COURSE_ID).id_source == ID_SOURCE_DERIVED
    assert MIGRATE_COURSE_ID_ENV in capsys.readouterr().out
