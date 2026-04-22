from __future__ import annotations

import os
from pathlib import Path
from xml.etree import ElementTree as ET

from llmgrader.mcp.description_utils import (
    make_element_description,
    make_text_content_description,
)
from llmgrader.services.unit_parser import UnitParser


def get_llmgrader_config_structure() -> dict:
    """Return a JSON-serializable nested schema description of llmgrader_config.xml.

    The returned object describes the XML hierarchy, child elements, text content,
    semantic rules, and example documents for llmgrader_config.xml authoring.
    """
    return {
        "summary": (
            "llmgrader_config.xml defines course metadata, unit XML files to include in the "
            "package, and optional asset files or directories."
        ),
        "structure": {"llmgrader": _llmgrader_structure()},
        "semantic_rules": [
            "At least one <unit> is required under <units>.",
            "Destination paths must be relative to the package root.",
            "Destination paths must not contain '..'.",
            "Source paths should usually be relative to the workspace root.",
        ],
        "examples": {
            "minimal_document": (
                "<llmgrader>\n"
                "  <course>\n"
                "    <name>Probability</name>\n"
                "    <term>Fall 2026</term>\n"
                "  </course>\n"
                "  <units>\n"
                "    <unit>\n"
                "      <name>combinatorics</name>\n"
                "      <source>units/combinatorics.xml</source>\n"
                "      <destination>combinatorics.xml</destination>\n"
                "    </unit>\n"
                "  </units>\n"
                "</llmgrader>"
            ),
            "with_assets": (
                "<llmgrader>\n"
                "  <course>\n"
                "    <name>Probability</name>\n"
                "    <term>Fall 2026</term>\n"
                "  </course>\n"
                "  <units>\n"
                "    <unit>\n"
                "      <name>combinatorics</name>\n"
                "      <source>units/combinatorics.xml</source>\n"
                "      <destination>combinatorics.xml</destination>\n"
                "    </unit>\n"
                "  </units>\n"
                "  <assets>\n"
                "    <asset>\n"
                "      <source>figures</source>\n"
                "      <destination>probability_assets</destination>\n"
                "    </asset>\n"
                "  </assets>\n"
                "</llmgrader>"
            ),
        },
    }


def create_config_skeleton(
    *,
    course_name: str,
    term: str,
    units: list[dict[str, str]],
    assets: list[dict[str, str]] | None = None,
) -> str:
    if not units:
        raise ValueError("At least one unit is required to build a config skeleton.")

    root = ET.Element("llmgrader")
    course_elem = ET.SubElement(root, "course")
    ET.SubElement(course_elem, "name").text = (course_name or "").strip()
    ET.SubElement(course_elem, "term").text = (term or "").strip()

    units_elem = ET.SubElement(root, "units")
    for unit in units:
        unit_elem = ET.SubElement(units_elem, "unit")
        ET.SubElement(unit_elem, "name").text = (unit.get("name") or "").strip()
        ET.SubElement(unit_elem, "source").text = (unit.get("source") or "").strip()
        ET.SubElement(unit_elem, "destination").text = (unit.get("destination") or "").strip()

    cleaned_assets = assets or []
    if cleaned_assets:
        assets_elem = ET.SubElement(root, "assets")
        for asset in cleaned_assets:
            asset_elem = ET.SubElement(assets_elem, "asset")
            ET.SubElement(asset_elem, "source").text = (asset.get("source") or "").strip()
            ET.SubElement(asset_elem, "destination").text = (asset.get("destination") or "").strip()

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode")


def validate_config_xml(
    *,
    config_xml: str,
    workspace_root: str | None = None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        root = ET.fromstring(config_xml)
    except ET.ParseError as exc:
        return {"valid": False, "errors": [f"Failed to parse XML: {exc}"], "warnings": []}

    errors.extend(_validate_config_shape(root))

    course_elem = root.find("course")
    if course_elem is None:
        errors.append("Missing required <course> section.")
    else:
        if not (course_elem.findtext("name") or "").strip():
            errors.append("Missing required <course>/<name> value.")
        if not (course_elem.findtext("term") or "").strip():
            errors.append("Missing required <course>/<term> value.")

    units_elem = root.find("units")
    unit_elems = units_elem.findall("unit") if units_elem is not None else []

    for index, unit_elem in enumerate(unit_elems, start=1):
        unit_name = (unit_elem.findtext("name") or "").strip() or f"unit[{index}]"
        source_value = (unit_elem.findtext("source") or "").strip()
        destination_value = (unit_elem.findtext("destination") or "").strip()

        if not source_value:
            errors.append(f"Unit '{unit_name}' is missing <source>.")
        if destination_value:
            destination_error = UnitParser._validate_package_destination(destination_value)
            if destination_error:
                errors.append(f"Unit '{unit_name}' has invalid <destination>: {destination_error}")

        _warn_missing_source(
            source_value=source_value,
            workspace_root=workspace_root,
            label=f"Unit '{unit_name}'",
            warnings=warnings,
        )

    assets_elem = root.find("assets")
    if assets_elem is not None:
        for index, asset_elem in enumerate(assets_elem.findall("asset"), start=1):
            source_value = (asset_elem.findtext("source") or "").strip()
            destination_value = (asset_elem.findtext("destination") or "").strip()
            asset_label = destination_value or f"asset[{index}]"

            if destination_value:
                destination_error = UnitParser._validate_package_destination(destination_value)
                if destination_error:
                    errors.append(f"Asset '{asset_label}' has invalid <destination>: {destination_error}")

            _warn_missing_source(
                source_value=source_value,
                workspace_root=workspace_root,
                label=f"Asset '{asset_label}'",
                warnings=warnings,
            )

    return {"valid": not errors, "errors": errors, "warnings": warnings}


def scan_repo_for_config_inputs(*, workspace_root: str) -> dict:
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists():
        return {"workspace_root": str(root), "error": "Workspace root does not exist."}

    xml_candidates: list[str] = []
    asset_dirs: list[str] = []
    ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache"}
    likely_asset_dir_names = {"images", "image", "assets", "figures", "static"}

    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignored]

        current_path = Path(current_root)
        rel_current = "." if current_path == root else current_path.relative_to(root).as_posix()
        if current_path.name.lower() in likely_asset_dir_names:
            asset_dirs.append(rel_current)

        for filename in files:
            if not filename.lower().endswith(".xml"):
                continue
            rel_path = (current_path / filename).relative_to(root).as_posix()
            if filename == "llmgrader-config.xml":
                continue
            xml_candidates.append(rel_path)

    return {
        "workspace_root": str(root),
        "unit_xml_candidates": sorted(xml_candidates)[:50],
        "asset_directories": sorted(asset_dirs)[:50],
    }


def _llmgrader_structure() -> dict:
    return make_element_description(
        "Root element for one llmgrader solution package configuration.",
        required=True,
        multiple=False,
        children={
            "course": _course_structure(),
            "units": _units_structure(),
            "assets": _assets_structure(),
        },
    )


def _course_structure() -> dict:
    return make_element_description(
        "Course metadata for the packaged course.",
        required=True,
        multiple=False,
        children={
            "name": _course_name_structure(),
            "term": _course_term_structure(),
        },
    )


def _course_name_structure() -> dict:
    return make_element_description(
        "Course name.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Human-readable course name.",
            required=True,
            type="string",
            example="Probability",
        ),
    )


def _course_term_structure() -> dict:
    return make_element_description(
        "Academic term for the package.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Term label.",
            required=True,
            type="string",
            example="Fall 2026",
        ),
    )


def _units_structure() -> dict:
    return make_element_description(
        "Collection of packaged unit XML entries.",
        required=True,
        multiple=False,
        children={"unit": _unit_entry_structure()},
    )


def _unit_entry_structure() -> dict:
    return make_element_description(
        "One packaged unit XML entry.",
        required=True,
        multiple=True,
        children={
            "name": _unit_name_structure(),
            "source": _source_structure(
                "Relative path to the source unit XML file in the workspace.",
                "units/combinatorics.xml",
            ),
            "destination": _destination_structure("Destination filename inside the package.", "combinatorics.xml"),
        },
    )


def _unit_name_structure() -> dict:
    return make_element_description(
        "Short unit identifier used in the package manifest.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Unit name.",
            required=True,
            type="string",
            example="combinatorics",
        ),
    )


def _assets_structure() -> dict:
    return make_element_description(
        "Optional asset mappings for files or directories copied into the package.",
        required=False,
        multiple=False,
        children={"asset": _asset_structure()},
    )


def _asset_structure() -> dict:
    return make_element_description(
        "One asset file or directory to copy into the package.",
        required=False,
        multiple=True,
        children={
            "source": _source_structure(
                "Relative path to the asset file or directory in the workspace.",
                "figures",
            ),
            "destination": _destination_structure(
                "Relative destination path inside the package.",
                "probability_assets",
            ),
        },
    )


def _source_structure(description: str, example: str) -> dict:
    return make_element_description(
        description,
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Workspace-relative source path.",
            required=True,
            type="path",
            example=example,
        ),
    )


def _destination_structure(description: str, example: str) -> dict:
    return make_element_description(
        description,
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Package-relative destination path.",
            required=True,
            type="path",
            example=example,
        ),
    )


def _validate_config_shape(root: ET.Element) -> list[str]:
    schema = UnitParser._load_schema("llmgrader_config.xsd")
    schema_errors: list[str] = []

    for error in schema.iter_errors(root):
        location = getattr(error, "path", None) or "/"
        reason = getattr(error, "reason", None) or str(error)
        schema_errors.append(f"{location}: {reason}")

    return schema_errors


def _warn_missing_source(*, source_value: str, workspace_root: str | None, label: str, warnings: list[str]) -> None:
    if not workspace_root or not source_value:
        return
    root = Path(workspace_root).expanduser().resolve()
    source_path = (root / source_value).resolve()
    if not source_path.is_relative_to(root):
        warnings.append(f"{label} source path points outside workspace root: {source_value}")
        return
    if not source_path.exists():
        warnings.append(f"{label} source path does not exist under workspace root: {source_value}")