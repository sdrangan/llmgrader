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

from llmgrader.services.course_registry import ID_SOURCE_DERIVED, CourseRegistry
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
