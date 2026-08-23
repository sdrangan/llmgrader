"""A built solution package must never carry a grading test file.

Test files hold known-wrong answers together with their expected scores.
Shipping them to a deployed grader would put the answer key next to the
questions.

``create_soln_pkg`` assembles from the explicit ``<unit><source>`` entries in
``llmgrader_config.xml`` rather than by globbing, so a ``tests/`` subdirectory
cannot be picked up by accident.  This test exists to keep that true: it
asserts on the property (no ``<unit_test>`` root anywhere in the package)
rather than on the mechanism, so it still holds if the packaging changes.

The one way a test file can still leak is an ``<asset>`` source naming the
unit *directory*, which ``copy_asset_entry`` copies wholesale.  The
instructor docs warn against that; there is no code path that prevents it.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from llmgrader.scripts.create_soln_pkg import main as create_soln_pkg_main


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_UNIT = REPO_ROOT / "example_repo" / "unit1" / "calculus.xml"
EXAMPLE_TESTS = REPO_ROOT / "example_repo" / "unit1" / "tests" / "calculus_tests.xml"

CONFIG = """\
<llmgrader>
  <course>
    <name>Fixture Course</name>
    <semester>Fall 2026</semester>
  </course>
  <units>
    <unit>
      <name>Unit 1</name>
      <source>unit1/calculus.xml</source>
      <destination>unit1_calculus.xml</destination>
    </unit>
  </units>
</llmgrader>
"""


def _source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    unit_dir = source / "unit1"
    tests_dir = unit_dir / "tests"
    tests_dir.mkdir(parents=True)

    (unit_dir / "calculus.xml").write_text(EXAMPLE_UNIT.read_text(encoding="utf-8"), encoding="utf-8")
    (tests_dir / "calculus_tests.xml").write_text(
        EXAMPLE_TESTS.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (source / "llmgrader_config.xml").write_text(CONFIG, encoding="utf-8")
    return source


def _roots_in_zip(zip_path: Path) -> dict[str, str]:
    roots: dict[str, str] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".xml"):
                continue
            try:
                roots[name] = ET.fromstring(archive.read(name)).tag
            except ET.ParseError:  # pragma: no cover - a malformed package is a different bug
                roots[name] = "(unparseable)"
    return roots


def test_built_package_contains_no_unit_test_file(tmp_path: Path, monkeypatch) -> None:
    source = _source_repo(tmp_path)
    monkeypatch.setattr(sys, "argv", ["create_soln_pkg", "--config", "llmgrader_config.xml"])
    monkeypatch.chdir(source)

    assert create_soln_pkg_main() == 0

    zip_path = source / "soln_package.zip"
    roots = _roots_in_zip(zip_path)

    assert roots, "expected some XML in the package"
    assert "unit_test" not in roots.values(), roots
    assert set(roots) == {"llmgrader_config.xml", "unit1_calculus.xml"}

    # The extracted directory is what a deployment actually reads.
    pkg_dir = source / "soln_package"
    for path in pkg_dir.rglob("*.xml"):
        assert ET.parse(path).getroot().tag != "unit_test", path
