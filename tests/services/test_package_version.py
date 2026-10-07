"""Every course package carries a version (``plans/mcp_usage.md``, decision 4).

``create_soln_pkg`` writes ``package_info.json``; a package without one is
given a version computed from its contents when the Grader loads it; and the
version is stamped on every graded submission, so a grade traces to the rubric
that produced it.

The property the rest rests on is that the hash is reproducible: the same
files give the same version, and any change to them a different one.
"""

import json
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from llmgrader.scripts.create_soln_pkg import main as create_soln_pkg_main
from llmgrader.services.grader import Grader
from llmgrader.services.package_info import (
    PACKAGE_INFO_FILE,
    build_package_info,
    content_sha256,
    git_sources,
    package_version,
    write_package_info,
)
from llmgrader.services.portal_storage import PortalStorage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "unit_parser"
NOW = datetime(2026, 10, 7, 21, 40, 12, tzinfo=timezone.utc)

CONFIG_XML = """<llmgrader>
  <course>
    <name>Fixture Course</name>
    <semester>Fall 2026</semester>
  </course>
  <units>
    <unit>
      <name>Fixture Good Unit</name>
      <source>unit1/unit_good.xml</source>
      <destination>unit1_good.xml</destination>
    </unit>
  </units>
</llmgrader>
"""


def make_package(root: Path) -> Path:
    """A package as create_soln_pkg leaves it, before the version is written."""
    root.mkdir(parents=True)
    (root / "llmgrader_config.xml").write_text("<llmgrader/>", encoding="utf-8")
    (root / "unit.xml").write_text("<unit/>", encoding="utf-8")
    (root / "unit_images").mkdir()
    (root / "unit_images" / "fig.png").write_bytes(b"\x89PNG\r\n")
    return root


# ---------------------------------------------------------------------------
# The hash
# ---------------------------------------------------------------------------


def test_same_files_give_the_same_version(tmp_path: Path) -> None:
    one = make_package(tmp_path / "one")
    two = make_package(tmp_path / "two")
    assert content_sha256(one) == content_sha256(two)
    assert (build_package_info(one, now=NOW)["version"]
            == build_package_info(two, now=NOW)["version"])


@pytest.mark.parametrize("change", ["edit", "rename", "add", "remove"])
def test_any_changed_file_gives_a_different_version(tmp_path: Path, change: str) -> None:
    pkg = make_package(tmp_path / "pkg")
    before = content_sha256(pkg)

    fig = pkg / "unit_images" / "fig.png"
    if change == "edit":
        fig.write_bytes(b"\x89PNG\r\n!")
    elif change == "rename":
        fig.rename(fig.with_name("fig2.png"))
    elif change == "add":
        (pkg / "extra.xml").write_text("<unit/>", encoding="utf-8")
    else:
        fig.unlink()

    assert content_sha256(pkg) != before


def test_the_info_file_is_not_part_of_the_hash(tmp_path: Path) -> None:
    pkg = make_package(tmp_path / "pkg")
    before = content_sha256(pkg)
    write_package_info(pkg, now=NOW)
    assert content_sha256(pkg) == before


def test_the_version_is_the_build_date_and_the_hash_head(tmp_path: Path) -> None:
    pkg = make_package(tmp_path / "pkg")
    info = build_package_info(pkg, now=NOW)
    assert info["version"] == "2026-10-07." + content_sha256(pkg)[:7]
    assert info["built_at"] == "2026-10-07T21:40:12Z"
    assert info["content_sha256"] == content_sha256(pkg)


# ---------------------------------------------------------------------------
# Reading the version back
# ---------------------------------------------------------------------------


def test_a_package_with_info_reports_its_written_version(tmp_path: Path) -> None:
    pkg = make_package(tmp_path / "pkg")
    info = write_package_info(pkg, now=NOW)
    assert package_version(pkg) == info["version"]


def test_a_package_without_info_gets_a_computed_version(tmp_path: Path) -> None:
    pkg = make_package(tmp_path / "pkg")
    assert package_version(pkg) == "computed." + content_sha256(pkg)[:7]


def test_an_unreadable_info_file_falls_back_to_computed(tmp_path: Path) -> None:
    pkg = make_package(tmp_path / "pkg")
    (pkg / PACKAGE_INFO_FILE).write_text("{not json", encoding="utf-8")
    assert package_version(pkg).startswith("computed.")


def test_no_package_has_no_version(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert package_version(tmp_path / "empty") is None
    assert package_version(None) is None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "course-src"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (repo / "unit.xml").write_text("<unit/>", encoding="utf-8")
    git("add", "unit.xml")
    git("commit", "-q", "-m", "initial")
    return repo


def test_clean_inputs_are_marked_clean(git_repo: Path) -> None:
    assert git_sources([git_repo / "unit.xml"]) == {"course-src": _head(git_repo) + " (clean)"}


def test_changes_outside_the_inputs_are_not_counted(git_repo: Path) -> None:
    """A stray file elsewhere in the repository does not touch the package."""
    (git_repo / "notes.txt").write_text("stray", encoding="utf-8")
    (git_repo / "other.xml").write_text("<unit/>", encoding="utf-8")
    assert git_sources([git_repo / "unit.xml"])["course-src"].endswith("(clean)")


def test_changed_and_untracked_inputs_are_counted(git_repo: Path) -> None:
    (git_repo / "unit.xml").write_text("<unit>changed</unit>", encoding="utf-8")
    images = git_repo / "images"
    images.mkdir()
    (images / "a.png").write_bytes(b"a")
    (images / "b.png").write_bytes(b"b")
    state = git_sources([git_repo / "unit.xml", images])["course-src"]
    assert state.endswith("(1 uncommitted change, 2 files not in git)")


def test_an_ignored_input_counts_as_not_in_git(git_repo: Path) -> None:
    (git_repo / ".gitignore").write_text("*.pdf\n", encoding="utf-8")
    (git_repo / "deck.pdf").write_bytes(b"%PDF")
    state = git_sources([git_repo / "deck.pdf"])["course-src"]
    assert state.endswith("(1 file not in git)")


def test_inputs_reached_twice_are_counted_once(git_repo: Path) -> None:
    (git_repo / "unit.xml").write_text("<unit>changed</unit>", encoding="utf-8")
    state = git_sources([git_repo / "unit.xml", git_repo / "unit.xml"])["course-src"]
    assert state.endswith("(1 uncommitted change)")


def test_an_input_outside_git_has_no_source(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    outside = tmp_path / "plain"
    outside.mkdir()
    (outside / "unit.xml").write_text("<unit/>", encoding="utf-8")
    # tmp_path may itself sit inside a repository on some machines; only a
    # directory git does not recognise is expected to give nothing.
    probe = subprocess.run(["git", "rev-parse"], cwd=outside, capture_output=True)
    if probe.returncode == 0:
        pytest.skip("tmp_path is inside a git repository")
    assert git_sources([outside / "unit.xml"]) == {}


def _head(repo: Path) -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                          capture_output=True, text=True, check=True).stdout.strip()


# ---------------------------------------------------------------------------
# create_soln_pkg writes it, the Grader reads it
# ---------------------------------------------------------------------------


@pytest.fixture()
def built_package(tmp_path: Path, monkeypatch) -> Path:
    source = tmp_path / "source"
    (source / "unit1").mkdir(parents=True)
    shutil.copy(FIXTURES / "unit_good.xml", source / "unit1" / "unit_good.xml")
    (source / "llmgrader_config.xml").write_text(CONFIG_XML, encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["create_soln_pkg", "--config", "llmgrader_config.xml"])
    monkeypatch.chdir(source)
    assert create_soln_pkg_main() == 0
    return source


def test_create_soln_pkg_writes_the_info_into_the_archive(built_package: Path) -> None:
    with zipfile.ZipFile(built_package / "soln_package.zip") as archive:
        info = json.loads(archive.read(PACKAGE_INFO_FILE))

    pkg = built_package / "soln_package"
    assert info["content_sha256"] == content_sha256(pkg)
    assert isinstance(info["sources"], dict)
    assert info["version"].endswith("." + info["content_sha256"][:7])


def test_the_grader_loads_the_written_version(built_package: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    pkg = built_package / "soln_package"
    grader = Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(pkg))

    written = json.loads((pkg / PACKAGE_INFO_FILE).read_text(encoding="utf-8"))["version"]
    assert grader.units
    assert grader.package_version == written


def test_the_grader_computes_a_version_for_an_unversioned_package(
    built_package: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    pkg = built_package / "soln_package"
    (pkg / PACKAGE_INFO_FILE).unlink()
    grader = Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(pkg))
    assert grader.package_version == "computed." + content_sha256(pkg)[:7]


# ---------------------------------------------------------------------------
# submissions.package_version
# ---------------------------------------------------------------------------


def submission_columns(db_path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(submissions)")]
    finally:
        conn.close()


def test_the_column_is_added_once_to_an_existing_database(tmp_path: Path, monkeypatch) -> None:
    storage = tmp_path / "storage"
    (storage / "db").mkdir(parents=True)
    db_path = storage / "db" / "llmgrader.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "timestamp TEXT NOT NULL, student_soln TEXT)")
    conn.execute("INSERT INTO submissions (timestamp, student_soln) VALUES ('t', 'old')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage))

    PortalStorage()
    PortalStorage()  # a second boot must not try to add it again

    assert submission_columns(db_path).count("package_version") == 1
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT student_soln, package_version FROM submissions").fetchall() \
            == [("old", None)]
    finally:
        conn.close()


def test_a_fresh_database_has_the_column(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    storage = PortalStorage()
    assert "package_version" in submission_columns(storage.db_path)


class _FakeRawResponse:
    def model_dump(self):
        return {"result": "pass", "full_explanation": "ok", "feedback": "ok"}


class _FakeProcessedResult:
    def model_dump(self):
        return {"result": "pass", "full_explanation": "ok", "feedback": "ok",
                "point_parts": None, "max_point_parts": 1.0, "result_parts": "pass",
                "points": None, "max_points": 1.0}


def test_grading_stamps_the_package_version(
    built_package: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(Grader, "build_task_prompt",
                        lambda self, question_dict, student_soln, part_label="all": ("task", 1.0))
    monkeypatch.setattr(Grader, "_make_llm_caller",
                        lambda self, *args, **kwargs: (lambda: (_FakeRawResponse(), 11, 7, "")))
    monkeypatch.setattr(Grader, "grade_post_process",
                        lambda self, *args, **kwargs: _FakeProcessedResult())

    grader = Grader(scratch_dir=str(tmp_path / "scratch"),
                    soln_pkg=str(built_package / "soln_package"))
    assert grader.package_version

    grader.grade(
        question_dict={"question_text": "Q", "solution": "S", "grading_notes": "N",
                       "required": True, "partial_credit": False, "tools": [],
                       "parts": [{"part_label": "all", "points": 1.0}],
                       "rubrics": {}, "rubric_total": None},
        student_soln="My answer", unit_name="unit1", qtag="q1", provider="openai",
        model="gpt-5.4-mini", api_key="test-key", session_id="a1b2c3d4",
    )

    conn = sqlite3.connect(grader.db_path)
    try:
        row = conn.execute(
            "SELECT package_version FROM submissions ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row == (grader.package_version,)
