from __future__ import annotations

import os
from pathlib import Path
from xml.etree import ElementTree as ET

from mcp.server.fastmcp import FastMCP

from llmgrader.services.unit_parser import UnitParser


mcp = FastMCP("llmgrader")


def explain_config() -> dict:
    return {
        "required_shape": {
            "root": "llmgrader",
            "course": ["name", "term"],
            "units": ["unit(name, source, destination)"],
            "assets": ["asset(source, destination) (optional)"],
        },
        "notes": [
            "At least one <unit> is required.",
            "Destination paths must be relative to the package root.",
            "Destination paths must not contain '..'.",
            "Use <source> values relative to the workspace where possible.",
        ],
        "example_prompt": "Create a skeleton llmgrader_config.xml for Probability I, Fall 2026.",
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

    if root.tag != "llmgrader":
        errors.append("Root element must be <llmgrader>.")

    course_elem = root.find("course")
    if course_elem is None:
        errors.append("Missing required <course> section.")
    else:
        if not (course_elem.findtext("name") or "").strip():
            errors.append("Missing required <course>/<name> value.")
        if not (course_elem.findtext("term") or "").strip():
            errors.append("Missing required <course>/<term> value.")

    units_elem = root.find("units")
    if units_elem is None:
        errors.append("Missing required <units> section.")
        unit_elems: list[ET.Element] = []
    else:
        unit_elems = units_elem.findall("unit")
        if not unit_elems:
            errors.append("At least one <units>/<unit> entry is required.")

    for index, unit_elem in enumerate(unit_elems, start=1):
        unit_name = (unit_elem.findtext("name") or "").strip() or f"unit[{index}]"
        source_value = (unit_elem.findtext("source") or "").strip()
        destination_value = (unit_elem.findtext("destination") or "").strip()

        if not source_value:
            errors.append(f"Unit '{unit_name}' is missing <source>.")
        if not destination_value:
            errors.append(f"Unit '{unit_name}' is missing <destination>.")
        else:
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

            if not source_value:
                errors.append(f"Asset '{asset_label}' is missing <source>.")
            if not destination_value:
                errors.append(f"Asset '{asset_label}' is missing <destination>.")
            else:
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
        rel_current = "." if current_path == root else str(current_path.relative_to(root))
        if current_path.name.lower() in likely_asset_dir_names:
            asset_dirs.append(rel_current)

        for filename in files:
            if not filename.lower().endswith(".xml"):
                continue
            rel_path = str((current_path / filename).relative_to(root))
            if filename == "llmgrader_config.xml":
                continue
            xml_candidates.append(rel_path)

    return {
        "workspace_root": str(root),
        "unit_xml_candidates": sorted(xml_candidates)[:50],
        "asset_directories": sorted(asset_dirs)[:50],
    }


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


@mcp.tool(name="llmgrader_explain_config")
def llmgrader_explain_config() -> dict:
    """Provide guidance for authoring llmgrader_config.xml."""
    return explain_config()


@mcp.tool(name="llmgrader_create_config_skeleton")
def llmgrader_create_config_skeleton(
    course_name: str,
    term: str,
    units: list[dict[str, str]],
    assets: list[dict[str, str]] | None = None,
) -> dict:
    """Generate a llmgrader_config.xml skeleton from structured inputs."""
    xml_text = create_config_skeleton(
        course_name=course_name,
        term=term,
        units=units,
        assets=assets,
    )
    return {"xml": xml_text}


@mcp.tool(name="llmgrader_validate_config_xml")
def llmgrader_validate_config_xml(config_xml: str, workspace_root: str | None = None) -> dict:
    """Validate llmgrader_config.xml content and return errors/warnings."""
    return validate_config_xml(config_xml=config_xml, workspace_root=workspace_root)


@mcp.tool(name="llmgrader_scan_repo_for_config_inputs")
def llmgrader_scan_repo_for_config_inputs(workspace_root: str) -> dict:
    """Scan a workspace root for likely unit XMLs and asset directories."""
    return scan_repo_for_config_inputs(workspace_root=workspace_root)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
