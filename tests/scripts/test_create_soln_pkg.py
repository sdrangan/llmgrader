"""Tests for create_soln_pkg: packaging script that assembles the solution ZIP."""

import sys
import zipfile
from pathlib import Path

import pytest

from llmgrader.scripts.create_soln_pkg import main as create_soln_pkg_main


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "unit_parser"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_source_repo(tmp_path: Path, *, with_images: bool, assets_xml: str = "") -> Path:
    """Create a minimal instructor source repo under tmp_path/source/."""
    source = tmp_path / "source"

    unit_dir = source / "unit1"
    unit_dir.mkdir(parents=True)

    # Copy a valid unit XML from the existing test fixtures
    unit_xml = unit_dir / "unit_good.xml"
    unit_xml.write_text((RESOURCE_DIR / "unit_good.xml").read_text(encoding="utf-8"), encoding="utf-8")

    config = source / "llmgrader_config.xml"
    config.write_text(
                f"""\
<llmgrader>
    <course>
        <name>Fixture Course</name>
        <term>Fall 2026</term>
    </course>
  <units>
    <unit>
      <name>Fixture Good Unit</name>
      <source>unit1/unit_good.xml</source>
      <destination>unit1_good.xml</destination>
    </unit>
  </units>
    {assets_xml}
</llmgrader>
""",
        encoding="utf-8",
    )

    if with_images:
        images_dir = unit_dir / "images"
        images_dir.mkdir()
        (images_dir / "circuit.png").write_bytes(b"\x89PNG\r\n")
        (images_dir / "diagram.jpg").write_bytes(b"\xff\xd8\xff")

    return source


def _run_main(monkeypatch, config_path: Path) -> int:
    """Run create_soln_pkg_main with a fresh sys.argv and cwd set to config's parent."""
    monkeypatch.setattr(sys, "argv", ["create_soln_pkg", "--config", config_path.name])
    monkeypatch.chdir(config_path.parent)
    return create_soln_pkg_main()


# ---------------------------------------------------------------------------
# Tests – packaging without images (backward-compatibility)
# ---------------------------------------------------------------------------

def test_package_without_images_creates_zip(tmp_path: Path, monkeypatch) -> None:
    source = _build_source_repo(tmp_path, with_images=False)
    exit_code = _run_main(monkeypatch, source / "llmgrader_config.xml")

    assert exit_code == 0
    zip_path = source / "soln_package.zip"
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()

    assert "llmgrader_config.xml" in names
    assert "unit1_good.xml" in names
    # No image directories should appear
    assert not any("_images" in n for n in names)


# ---------------------------------------------------------------------------
# Tests – packaging with images
# ---------------------------------------------------------------------------

def test_package_with_images_copies_images_to_namespaced_directory(
    tmp_path: Path, monkeypatch
) -> None:
    source = _build_source_repo(tmp_path, with_images=True)
    exit_code = _run_main(monkeypatch, source / "llmgrader_config.xml")

    assert exit_code == 0

    # Check the extracted output directory
    pkg_dir = source / "soln_package"
    images_dest = pkg_dir / "unit1_good_images"
    assert images_dest.is_dir(), "Expected unit1_good_images/ in soln_package/"
    assert (images_dest / "circuit.png").exists()
    assert (images_dest / "diagram.jpg").exists()


def test_package_with_images_includes_images_in_zip(
    tmp_path: Path, monkeypatch
) -> None:
    source = _build_source_repo(tmp_path, with_images=True)
    exit_code = _run_main(monkeypatch, source / "llmgrader_config.xml")

    assert exit_code == 0

    zip_path = source / "soln_package.zip"
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())

    assert "unit1_good_images/circuit.png" in names
    assert "unit1_good_images/diagram.jpg" in names


def test_package_images_dir_namespaced_by_destination_stem(
    tmp_path: Path, monkeypatch
) -> None:
    """Two units whose source images/ directories contain the same filename
    must not collide: each gets its own <dest_stem>_images/ directory."""
    source = tmp_path / "source"
    source.mkdir()

    for unit_name, dest in (("unit1", "pkg_unit1.xml"), ("unit2", "pkg_unit2.xml")):
        unit_dir = source / unit_name
        unit_dir.mkdir()
        xml_text = (RESOURCE_DIR / "unit_good.xml").read_text(encoding="utf-8")
        (unit_dir / f"{unit_name}.xml").write_text(xml_text, encoding="utf-8")
        images_dir = unit_dir / "images"
        images_dir.mkdir()
        (images_dir / "figure.png").write_bytes(b"\x89PNG\r\n")  # same filename in both

    config = source / "llmgrader_config.xml"
    config.write_text(
        """\
<llmgrader>
    <course>
        <name>Fixture Course</name>
        <term>Fall 2026</term>
    </course>
  <units>
    <unit>
      <name>Unit 1</name>
      <source>unit1/unit1.xml</source>
      <destination>pkg_unit1.xml</destination>
    </unit>
    <unit>
      <name>Unit 2</name>
      <source>unit2/unit2.xml</source>
      <destination>pkg_unit2.xml</destination>
    </unit>
  </units>
</llmgrader>
""",
        encoding="utf-8",
    )

    exit_code = _run_main(monkeypatch, config)
    assert exit_code == 0

    pkg_dir = source / "soln_package"
    assert (pkg_dir / "pkg_unit1_images" / "figure.png").exists()
    assert (pkg_dir / "pkg_unit2_images" / "figure.png").exists()


def test_package_with_explicit_asset_directory_copies_to_destination(
        tmp_path: Path, monkeypatch
) -> None:
        assets_xml = """\
<assets>
    <asset>
        <source>unit1/images</source>
        <destination>unit1_assets</destination>
    </asset>
</assets>
"""
        source = _build_source_repo(tmp_path, with_images=True, assets_xml=assets_xml)

        exit_code = _run_main(monkeypatch, source / "llmgrader_config.xml")

        assert exit_code == 0

        pkg_dir = source / "soln_package"
        assert (pkg_dir / "unit1_assets" / "circuit.png").exists()
        assert (pkg_dir / "unit1_assets" / "diagram.jpg").exists()


def test_package_with_explicit_asset_file_copies_to_exact_destination(
        tmp_path: Path, monkeypatch
) -> None:
        assets_xml = """\
<assets>
    <asset>
        <source>shared/func.png</source>
        <destination>unit1_assets/func.png</destination>
    </asset>
</assets>
"""
        source = _build_source_repo(tmp_path, with_images=False, assets_xml=assets_xml)
        shared_dir = source / "shared"
        shared_dir.mkdir()
        (shared_dir / "func.png").write_bytes(b"\x89PNG\r\n")

        exit_code = _run_main(monkeypatch, source / "llmgrader_config.xml")

        assert exit_code == 0

        pkg_dir = source / "soln_package"
        assert (pkg_dir / "unit1_assets" / "func.png").exists()

        zip_path = source / "soln_package.zip"
        with zipfile.ZipFile(zip_path) as z:
                names = set(z.namelist())

        assert "unit1_assets/func.png" in names


def test_package_rejects_asset_destination_path_traversal(
        tmp_path: Path, monkeypatch
) -> None:
        assets_xml = """\
<assets>
    <asset>
        <source>unit1/images</source>
        <destination>../escape</destination>
    </asset>
</assets>
"""
        source = _build_source_repo(tmp_path, with_images=True, assets_xml=assets_xml)

        exit_code = _run_main(monkeypatch, source / "llmgrader_config.xml")

        assert exit_code == 1
        assert not (source / "soln_package").exists()


def test_package_warns_for_empty_asset_directory(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    assets_xml = """\
<assets>
    <asset>
    <source>unit1/images</source>
    <destination>unit1_assets</destination>
    </asset>
</assets>
"""
    source = _build_source_repo(tmp_path, with_images=False, assets_xml=assets_xml)
    (source / "unit1" / "images").mkdir()

    exit_code = _run_main(monkeypatch, source / "llmgrader_config.xml")
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Warning: Asset directory is empty:" in captured.out
    assert (source / "soln_package" / "unit1_assets").is_dir()

