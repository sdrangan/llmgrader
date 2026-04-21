import base64
import json
import shutil
from pathlib import Path

from llmgrader.services.unit_parser import UnitParser


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "unit_parser"


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


def test_validate_unit_file_reports_line_number_for_schema_error() -> None:
    errors = UnitParser.validate_unit_file(str(RESOURCE_DIR / "unit_broken.xml"))

    assert len(errors) == 1
    assert "line 6" in errors[0]
    assert "/unit/question/required" in errors[0]


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


def test_parse_skips_semantically_invalid_rubric_units_and_sets_alert(tmp_path: Path) -> None:
    _stage_package(tmp_path, "config_semantic_broken_unit.xml")

    package = _make_parser(tmp_path).parse()

    assert sorted(package.units.keys()) == ["Fixture Good Unit"]
    assert package.units_order == [{"type": "unit", "name": "Fixture Good Unit"}]
    assert package.units_list == ["Fixture Good Unit"]
    assert package.xml_path_list == ["unit_good.xml"]
    assert package.validation_alert is not None
    assert "failed validation" in package.validation_alert
    assert any("unit_semantic_broken.xml" in error for error in package.validation_errors)
    assert any("does not allow rubric item" in error for error in package.validation_errors)
    assert any("requires positive rubric items" in error for error in package.validation_errors)


def _stage_image_package(tmp_path: Path) -> Path:
    """Stage the image-unit test package, including the PNG fixture."""
    shutil.copy2(RESOURCE_DIR / "config_image_unit.xml", tmp_path / "llmgrader_config.xml")
    shutil.copy2(RESOURCE_DIR / "unit_with_image.xml", tmp_path / "unit_with_image.xml")
    shutil.copy2(RESOURCE_DIR / "soln_img.png", tmp_path / "soln_img.png")
    # Also place the image where /pkg_assets/unit_images/ would resolve to.
    unit_images_dir = tmp_path / "unit_images"
    unit_images_dir.mkdir()
    shutil.copy2(RESOURCE_DIR / "soln_img.png", unit_images_dir / "soln_img.png")
    return tmp_path


def test_solution_images_extracted_from_relative_src(tmp_path: Path) -> None:
    """solution_images contains a data URI when the solution has a relative <img> src."""
    _stage_image_package(tmp_path)

    package = _make_parser(tmp_path).parse()
    unit = package.units["Fixture Image Unit"]

    images = unit["q_with_image"]["solution_images"]
    assert len(images) == 1
    assert images[0].startswith("data:image/png;base64,")

    # Decoded content must match the original PNG bytes.
    original = (RESOURCE_DIR / "soln_img.png").read_bytes()
    _, encoded = images[0].split(",", 1)
    assert base64.b64decode(encoded) == original


def test_solution_images_extracted_from_pkg_assets_src(tmp_path: Path) -> None:
    """solution_images contains a data URI when the solution uses a /pkg_assets/ src."""
    _stage_image_package(tmp_path)

    package = _make_parser(tmp_path).parse()
    unit = package.units["Fixture Image Unit"]

    images = unit["q_pkg_assets_image"]["solution_images"]
    assert len(images) == 1
    assert images[0].startswith("data:image/png;base64,")


def test_solution_images_empty_when_no_img_tags(tmp_path: Path) -> None:
    """solution_images is an empty list when the solution contains no <img> tags."""
    _stage_image_package(tmp_path)

    package = _make_parser(tmp_path).parse()
    unit = package.units["Fixture Image Unit"]

    assert unit["q_no_image"]["solution_images"] == []


def test_solution_images_skips_missing_file(tmp_path: Path) -> None:
    """A missing image file is silently skipped; solution_images stays empty."""
    _stage_image_package(tmp_path)
    # Remove the PNG so it cannot be found.
    (tmp_path / "soln_img.png").unlink()

    package = _make_parser(tmp_path).parse()
    unit = package.units["Fixture Image Unit"]

    # Relative-src question: image file is gone → empty list.
    assert unit["q_with_image"]["solution_images"] == []