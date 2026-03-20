import json
import shutil
from pathlib import Path

from llmgrader.services.unit_parser import UnitParser


RESOURCE_DIR = Path(__file__).parent / "fixtures" / "unit_parser"


def _make_parser(tmp_path: Path) -> UnitParser:
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    return UnitParser(scratch_dir=str(scratch_dir), soln_pkg=str(tmp_path), supported_tools=["web_search"])


def _stage_package(tmp_path: Path, config_name: str) -> Path:
    shutil.copy2(RESOURCE_DIR / config_name, tmp_path / "llmgrader_config.xml")
    for xml_path in RESOURCE_DIR.glob("*.xml"):
        if xml_path.name.startswith("config_"):
            continue
        shutil.copy2(xml_path, tmp_path / xml_path.name)
    return tmp_path


def _load_expected(name: str) -> dict:
    return json.loads((RESOURCE_DIR / name).read_text(encoding="utf-8"))


def _package_snapshot(package) -> dict:
    return {
        "units": package.units,
        "units_order": package.units_order,
        "units_list": package.units_list,
        "xml_path_list": package.xml_path_list,
        "validation_errors": package.validation_errors,
        "validation_alert": package.validation_alert,
    }


def test_validate_unit_file_accepts_demo_unit() -> None:
    errors = UnitParser.validate_unit_file("soln_repos/demo_unit.xml")
    assert errors == []


def test_parse_matches_expected_snapshot_for_valid_package(tmp_path: Path) -> None:
    _stage_package(tmp_path, "config_good.xml")

    package = _make_parser(tmp_path).parse()
    expected = _load_expected("expected_good.json")

    assert _package_snapshot(package) == expected


def test_parse_skips_invalid_units_and_sets_alert(tmp_path: Path) -> None:
    _stage_package(tmp_path, "config_broken_unit.xml")

    package = _make_parser(tmp_path).parse()

    assert sorted(package.units.keys()) == ["Fixture Good Unit"]
    assert package.units_order == [{"type": "unit", "name": "Fixture Good Unit"}]
    assert package.units_list == ["Fixture Good Unit"]
    assert package.xml_path_list == ["unit_good.xml"]
    assert package.validation_alert is not None
    assert "failed validation" in package.validation_alert
    assert len(package.validation_errors) == 1
    assert "unit_broken.xml" in package.validation_errors[0]