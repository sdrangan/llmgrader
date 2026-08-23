"""build_autograder must tolerate a unit directory that holds grading tests.

Grading test files live in a ``tests/`` subdirectory of the unit directory,
and the reason is here: ``build_autograder`` with no ``--schema`` globs
``*.xml`` in the current directory and hard-errors on more than one match.  A
subdirectory does not match that glob, so the convention keeps the script
working -- but nothing enforced that until this test.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from llmgrader.scripts.build_autograder import main as build_autograder_main


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_UNIT = REPO_ROOT / "example_repo" / "unit1" / "calculus.xml"
EXAMPLE_TESTS = REPO_ROOT / "example_repo" / "unit1" / "tests" / "calculus_tests.xml"


def _unit_dir(tmp_path: Path, *, with_tests: bool) -> Path:
    unit_dir = tmp_path / "unit1"
    unit_dir.mkdir()
    (unit_dir / "calculus.xml").write_text(EXAMPLE_UNIT.read_text(encoding="utf-8"), encoding="utf-8")

    if with_tests:
        tests_dir = unit_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "calculus_tests.xml").write_text(
            EXAMPLE_TESTS.read_text(encoding="utf-8"), encoding="utf-8"
        )

    return unit_dir


def test_unit_directory_with_a_tests_subdir_still_resolves(tmp_path: Path, monkeypatch) -> None:
    unit_dir = _unit_dir(tmp_path, with_tests=True)
    monkeypatch.setattr(sys, "argv", ["build_autograder"])
    monkeypatch.chdir(unit_dir)

    build_autograder_main()

    zip_path = unit_dir / "autograder.zip"
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as archive:
        packaged = archive.read("grade_schema.xml").decode("utf-8")

    # The unit was packaged, not the test file that sits beside it.
    assert ET.fromstring(packaged).tag == "unit"
    assert packaged.splitlines() == EXAMPLE_UNIT.read_text(encoding="utf-8").splitlines()


def test_two_unit_files_in_the_same_directory_still_error(tmp_path: Path, monkeypatch) -> None:
    """The control: the ambiguity the tests/ convention exists to avoid."""
    unit_dir = _unit_dir(tmp_path, with_tests=False)
    (unit_dir / "calculus_tests.xml").write_text(
        EXAMPLE_TESTS.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(sys, "argv", ["build_autograder"])
    monkeypatch.chdir(unit_dir)

    with pytest.raises(SystemExit) as excinfo:
        build_autograder_main()

    assert excinfo.value.code == 1
