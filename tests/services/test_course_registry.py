"""The registry of courses on one portal: ids, paths and shared storage.

The properties pinned here are the ones the rest of multi-course support will
lean on (``plans/multicourse.md``, phase 2):

* an id is *resolved* once -- authored ``<course_id>`` first, a slug of
  ``<name>`` + ``<semester>`` second -- and *recorded*, never re-derived on a
  later boot;
* every course's ``Grader`` shares one ``PortalStorage``, so the database is
  opened and migrated once per process;
* scratch is per course *and* per process, because ``claim_scratch_dir`` is a
  process-global set and says nothing about a second gunicorn worker;
* ``--soln_pkg`` still means what it means today: that package is the sole
  course and no registry file is written.
"""

import json
import os
import zipfile
from pathlib import Path

import pytest

from llmgrader.services.course_registry import (
    COURSE_ID_PATTERN,
    FALLBACK_COURSE_ID,
    ID_SOURCE_AUTHORED,
    ID_SOURCE_DERIVED,
    ID_SOURCE_FALLBACK,
    ID_SOURCE_RECOVERED,
    CourseRegistry,
    read_course_block,
    resolve_course_id,
    slugify_course_id,
)
from llmgrader.services.grader import UPLOAD_RETENTION, Grader, prune_uploads
from llmgrader.services.portal_storage import PortalStorage
from llmgrader.services.unit_parser import UnitParser

FIXTURE_PKG = Path(__file__).resolve().parents[1] / "ui" / "fixtures"


def write_package(directory: Path, *, name: str, semester: str, course_id: str | None = None) -> Path:
    """A minimal but real course package: config plus the unit it names."""
    directory.mkdir(parents=True, exist_ok=True)
    id_line = f"    <course_id>{course_id}</course_id>\n" if course_id else ""
    (directory / "llmgrader_config.xml").write_text(
        "<llmgrader>\n"
        "  <course>\n"
        f"{id_line}"
        f"    <name>{name}</name>\n"
        f"    <semester>{semester}</semester>\n"
        "  </course>\n"
        "  <units>\n"
        "    <unit>\n"
        "      <name>Test Unit</name>\n"
        "      <source>test_unit.xml</source>\n"
        "      <destination>test_unit.xml</destination>\n"
        "    </unit>\n"
        "  </units>\n"
        "</llmgrader>\n",
        encoding="utf-8",
    )
    (directory / "test_unit.xml").write_text(
        (FIXTURE_PKG / "test_unit.xml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return directory


@pytest.fixture()
def storage_root(tmp_path: Path, monkeypatch) -> Path:
    """Keep the database, registry and scratch out of the developer's local_data."""
    root = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(root))
    return root


# ---------------------------------------------------------------------------
# Id resolution
# ---------------------------------------------------------------------------

def test_authored_course_id_wins(tmp_path: Path) -> None:
    pkg = write_package(tmp_path / "pkg", name="Intro to Probability", semester="Spring 2026",
                        course_id="intro_prob")

    course_id, id_source = resolve_course_id(read_course_block(str(pkg)))

    assert course_id == "intro_prob"
    assert id_source == ID_SOURCE_AUTHORED


def test_id_is_derived_from_name_and_semester_when_unauthored(tmp_path: Path) -> None:
    """The path every package written before <course_id> existed takes."""
    pkg = write_package(tmp_path / "pkg", name="Demo Class", semester="Spring 2026")

    course_id, id_source = resolve_course_id(read_course_block(str(pkg)))

    assert course_id == "demo-class-spring-2026"
    assert id_source == ID_SOURCE_DERIVED


def test_unreadable_package_falls_back_rather_than_failing_boot(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert read_course_block(str(empty)) == {}
    assert resolve_course_id({}) == (FALLBACK_COURSE_ID, ID_SOURCE_FALLBACK)


@pytest.mark.parametrize(
    "parts, expected",
    [
        (("ECE-GY 6201 Introduction to Probability", "Spring 2026"),
         "ece-gy-6201-introduction-to-probability-spring-2026"),
        (("Demo Class", "Spring 2026"), "demo-class-spring-2026"),
        (("Señor Álgebra", "Otoño 2026"), "se-or-lgebra-oto-o-2026"),
        (("  Spaces  ", ""), "spaces"),
        (("2026 Course", "Fall"), "2026-course-fall"),
        (("...", "!!!"), ""),
        (("", ""), ""),
    ],
)
def test_slugify_course_id(parts, expected) -> None:
    assert slugify_course_id(*parts) == expected


def test_slug_is_capped_at_the_schema_length(tmp_path: Path) -> None:
    """The slug has to satisfy the same pattern an authored id is checked against."""
    slug = slugify_course_id("A" * 200, "Spring 2026")

    assert len(slug) <= 64
    assert COURSE_ID_PATTERN.match(slug)


def test_an_unauthorable_course_id_is_not_trusted(tmp_path: Path) -> None:
    """A hand-edited id that the schema would reject falls through to the slug."""
    block = {"course_id": "../escape", "name": "Demo Class", "semester": "Spring 2026"}

    assert resolve_course_id(block) == ("demo-class-spring-2026", ID_SOURCE_DERIVED)


# ---------------------------------------------------------------------------
# The registry file
# ---------------------------------------------------------------------------

def test_registration_records_the_id_and_its_source(storage_root: Path) -> None:
    write_package(storage_root / "courses" / "intro_prob" / "soln_pkg",
                  name="Intro to Probability", semester="Spring 2026", course_id="intro_prob")

    registry = CourseRegistry()
    registry.register_package(registry.soln_pkg_path("intro_prob"), make_default=True)

    payload = json.loads((storage_root / "courses" / "courses.json").read_text())
    entry = [row for row in payload["courses"] if row["id"] == "intro_prob"][0]
    assert entry["name"] == "Intro to Probability"
    assert entry["semester"] == "Spring 2026"
    assert entry["id_source"] == ID_SOURCE_AUTHORED
    assert entry["created_at"]
    assert payload["default"] == "intro_prob"


def test_the_id_is_read_back_and_never_re_derived(storage_root: Path) -> None:
    """A later edit to <name> must not rename the course out from under its data."""
    pkg = write_package(storage_root / "courses" / "demo-class-spring-2026" / "soln_pkg",
                        name="Demo Class", semester="Spring 2026")

    first = CourseRegistry()
    first.register_package(str(pkg), make_default=True)
    assert first.default_course_id == "demo-class-spring-2026"

    # The instructor fixes a typo in the display name and re-uploads.
    write_package(pkg, name="Demo Class II", semester="Fall 2027")

    second = CourseRegistry()

    assert second.default_course_id == "demo-class-spring-2026"
    assert second.get("demo-class-spring-2026").name == "Demo Class"


def test_a_corrupt_registry_file_is_set_aside_rather_than_bricking_the_portal(
    storage_root: Path,
) -> None:
    courses_dir = storage_root / "courses"
    courses_dir.mkdir(parents=True)
    (courses_dir / "courses.json").write_text("{ not json", encoding="utf-8")

    registry = CourseRegistry()

    assert registry.default_course_id == FALLBACK_COURSE_ID
    assert list(courses_dir.glob("courses.json.bad-*"))


def test_a_lost_registry_is_rebuilt_from_the_directories_on_disk(storage_root: Path) -> None:
    """The directory name is the id -- re-deriving it would orphan the package."""
    package = write_package(storage_root / "courses" / "intro_prob" / "soln_pkg",
                            name="Intro to Probability", semester="Spring 2026",
                            course_id="renamed_since")

    registry = CourseRegistry()

    assert registry.default_course_id == "intro_prob"
    assert registry.get("intro_prob").id_source == ID_SOURCE_RECOVERED
    assert registry.get("intro_prob").name == "Intro to Probability"
    assert registry.soln_pkg_path("intro_prob") == str(package)
    assert registry.default_grader().units


def test_a_fresh_portal_registers_somewhere_for_an_upload_to_land(storage_root: Path) -> None:
    """Nothing deployed yet: one course, the fallback id, and a real directory."""
    registry = CourseRegistry()

    assert registry.default_course_id == FALLBACK_COURSE_ID
    assert registry.get(FALLBACK_COURSE_ID).id_source == ID_SOURCE_FALLBACK
    assert (storage_root / "courses" / "courses.json").exists()

    grader = registry.default_grader()
    assert grader.soln_pkg == str(storage_root / "courses" / FALLBACK_COURSE_ID / "soln_pkg")


# ---------------------------------------------------------------------------
# Per-course paths
# ---------------------------------------------------------------------------

def test_paths_are_scoped_to_the_course(storage_root: Path) -> None:
    registry = CourseRegistry()
    course_dir = storage_root / "courses" / "intro_prob"

    assert registry.soln_pkg_path("intro_prob") == str(course_dir / "soln_pkg")
    assert registry.uploads_path("intro_prob") == str(course_dir / "uploads")
    assert registry.scratch_path("intro_prob").startswith(str(course_dir / "scratch"))


def test_scratch_is_per_course_and_per_process(storage_root: Path) -> None:
    """claim_scratch_dir guards one process; the path itself guards the others."""
    registry = CourseRegistry()

    a = registry.scratch_path("course_a")
    b = registry.scratch_path("course_b")

    assert a != b
    assert os.path.basename(a) == f"pid-{os.getpid()}"
    assert os.path.basename(b) == f"pid-{os.getpid()}"


def test_scratch_of_a_dead_process_is_pruned_and_a_live_one_is_not(storage_root: Path) -> None:
    registry = CourseRegistry()
    scratch_root = Path(registry.scratch_root("intro_prob"))
    scratch_root.mkdir(parents=True)

    dead = scratch_root / "pid-2147480000"       # no process has this pid
    live = scratch_root / f"pid-{os.getppid()}"  # the test runner's parent
    mine = Path(registry.scratch_path("intro_prob"))
    other = scratch_root / "not-a-pid-dir"
    for directory in (dead, live, mine, other):
        directory.mkdir(parents=True, exist_ok=True)

    removed = registry.prune_stale_scratch("intro_prob")

    assert [Path(path) for path in removed] == [dead]
    assert not dead.exists()
    assert live.exists() and mine.exists() and other.exists()


def test_unit_parser_resolves_the_package_under_the_course(storage_root: Path, tmp_path) -> None:
    """_resolve_solution_package_path takes an id; without one it stays legacy."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    scoped = UnitParser(scratch_dir=str(scratch), course_id="intro_prob")
    legacy = UnitParser(scratch_dir=str(scratch))

    assert scoped._resolve_solution_package_path() == str(
        storage_root / "courses" / "intro_prob" / "soln_pkg"
    )
    assert legacy._resolve_solution_package_path() == str(storage_root / "soln_pkg")


# ---------------------------------------------------------------------------
# Graders
# ---------------------------------------------------------------------------

def test_every_course_shares_one_portal_storage(storage_root: Path) -> None:
    """The seam phase 1 built: one database, opened and migrated once."""
    storage = PortalStorage()
    registry = CourseRegistry(storage=storage)
    write_package(Path(registry.soln_pkg_path("course_a")), name="Course A", semester="Spring 2026",
                  course_id="course_a")
    write_package(Path(registry.soln_pkg_path("course_b")), name="Course B", semester="Spring 2026",
                  course_id="course_b")
    registry.register(course_id="course_a", name="Course A", semester="Spring 2026",
                      id_source=ID_SOURCE_AUTHORED, make_default=True)
    registry.register(course_id="course_b", name="Course B", semester="Spring 2026",
                      id_source=ID_SOURCE_AUTHORED)

    first = registry.grader_for("course_a")
    second = registry.grader_for("course_b")

    assert first.storage is storage is second.storage
    assert first is registry.grader_for("course_a")   # built once, then cached
    assert first.scratch_dir != second.scratch_dir
    assert first.units and second.units


def test_building_the_second_course_does_not_wipe_the_first(storage_root: Path) -> None:
    """The failure that made a second Grader unsafe before phase 1."""
    registry = CourseRegistry()
    registry.register(course_id="course_a", name="A", semester="S", id_source=ID_SOURCE_AUTHORED)
    registry.register(course_id="course_b", name="B", semester="S", id_source=ID_SOURCE_AUTHORED)

    first = registry.grader_for("course_a")
    staged = Path(first.scratch_dir) / "in_progress.zip"
    staged.write_text("course A's work")

    registry.grader_for("course_b")

    assert staged.read_text() == "course A's work"


# ---------------------------------------------------------------------------
# Single-package mode: run.py --soln_pkg
# ---------------------------------------------------------------------------

def test_single_package_mode_writes_no_registry_file(storage_root: Path, tmp_path: Path) -> None:
    pkg = write_package(tmp_path / "pkg", name="Local Course", semester="Spring 2026",
                        course_id="local_course")
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    registry = CourseRegistry(soln_pkg=str(pkg), scratch_dir=str(scratch))
    grader = registry.default_grader()

    assert registry.default_course_id == "local_course"
    assert not (storage_root / "courses" / "courses.json").exists()
    assert grader.soln_pkg == str(pkg)
    assert grader.scratch_dir == str(scratch)   # the caller's path, verbatim
    assert grader.uploads_dir is None
    assert grader.units


def test_single_package_mode_identifies_an_unauthored_package_too(
    storage_root: Path, tmp_path: Path
) -> None:
    pkg = write_package(tmp_path / "pkg", name="Local Course", semester="Spring 2026")
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    registry = CourseRegistry(soln_pkg=str(pkg), scratch_dir=str(scratch))

    assert registry.default_course_id == "local-course-spring-2026"
    assert not (storage_root / "courses").exists() or not (
        storage_root / "courses" / "courses.json"
    ).exists()


# ---------------------------------------------------------------------------
# uploads/
# ---------------------------------------------------------------------------

class _FakeUpload:
    """The slice of werkzeug's FileStorage that save_uploaded_file uses."""

    def __init__(self, filename: str, payload: bytes):
        self.filename = filename
        self._payload = payload

    def save(self, path: str) -> None:
        with open(path, "wb") as handle:
            handle.write(self._payload)


def _package_zip(tmp_path: Path, *, name: str) -> bytes:
    pkg = write_package(tmp_path / f"src_{name}", name=name, semester="Spring 2026")
    archive = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for path in sorted(pkg.iterdir()):
            handle.write(path, path.name)
    return archive.read_bytes()


def test_uploads_are_kept_under_the_course_newest_three(storage_root: Path, tmp_path: Path) -> None:
    registry = CourseRegistry()
    course_id = registry.default_course_id
    grader = registry.default_grader()

    for index in range(UPLOAD_RETENTION + 2):
        result = grader.save_uploaded_file(
            _FakeUpload("soln_package.zip", _package_zip(tmp_path, name=f"Course{index}"))
        )
        assert result["status"] == "ok", result

    uploads = sorted(Path(registry.uploads_path(course_id)).iterdir())

    assert len(uploads) == UPLOAD_RETENTION
    assert all(path.name.endswith("_soln_package.zip") for path in uploads)
    # The retained ones are the newest: the last upload is still there.
    assert grader.units
    assert not list(Path(grader.scratch_dir).glob("*.zip"))


def test_upload_without_an_uploads_dir_still_lands_in_scratch(tmp_path: Path, monkeypatch) -> None:
    """Every caller outside the registry keeps today's behaviour."""
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    grader = Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(pkg))

    grader.save_uploaded_file(_FakeUpload("soln_package.zip", _package_zip(tmp_path, name="Solo")))

    assert (Path(grader.scratch_dir) / "soln_package.zip").exists()


def test_prune_uploads_keeps_the_newest(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    for index in range(5):
        path = uploads / f"2026010{index}T000000.000_soln_package.zip"
        path.write_text(str(index))
        os.utime(path, (index, index))

    removed = prune_uploads(str(uploads), keep=2)

    assert len(removed) == 3
    assert sorted(path.name for path in uploads.iterdir()) == [
        "20260103T000000.000_soln_package.zip",
        "20260104T000000.000_soln_package.zip",
    ]


# ---------------------------------------------------------------------------
# The schema constrains <course_id>, because it becomes a path segment
# ---------------------------------------------------------------------------

def _config_with_course_id(directory: Path, course_id: str | None) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    write_package(directory, name="Demo Class", semester="Spring 2026", course_id=course_id)
    return str(directory / "llmgrader_config.xml")


def test_an_authored_course_id_validates(tmp_path: Path) -> None:
    path = _config_with_course_id(tmp_path / "authored", "intro_prob-2")

    assert UnitParser.validate_config_file(path) == []


def test_course_id_stays_optional(tmp_path: Path) -> None:
    """Eight config files in this repo predate the field, as does every
    deployed package -- and the boot migration runs against exactly one."""
    path = _config_with_course_id(tmp_path / "unauthored", None)

    assert UnitParser.validate_config_file(path) == []


@pytest.mark.parametrize(
    "course_id",
    [
        "Intro_Prob",     # uppercase: two ids that differ only by case on a
                          # case-insensitive filesystem are one directory
        "../escape",      # path traversal
        "intro.prob",     # dots
        "-leading-dash",  # must start alphanumeric
        "x" * 65,         # over the 64-character cap
    ],
)
def test_the_schema_rejects_an_id_that_is_unsafe_as_a_path_segment(
    tmp_path: Path, course_id: str
) -> None:
    path = _config_with_course_id(tmp_path / "bad", course_id)

    assert UnitParser.validate_config_file(path) != []


def test_the_parser_surfaces_the_authored_id(tmp_path: Path) -> None:
    """_parse_course_info carries <course_id> through to course_info."""
    pkg = write_package(tmp_path / "pkg", name="Demo Class", semester="Spring 2026",
                        course_id="demo_class")
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    package = UnitParser(scratch_dir=str(scratch), soln_pkg=str(pkg)).parse()

    assert package.course_info["course_id"] == "demo_class"
