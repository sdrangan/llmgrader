from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from llmgrader.mcp.config_xml_tools import (
    create_config_skeleton,
    get_llmgrader_config_structure,
    scan_repo_for_config_inputs,
    validate_config_xml,
)
from llmgrader.mcp.example_tools import (
    get_question_example,
    list_question_examples,
)
from llmgrader.mcp.unit_xml_tools import (
    create_unit_xml_skeleton,
    explain_rubric_rules,
    get_unit_xml_structure,
    plan_question_draft,
    scan_repo_for_unit_inputs,
    validate_unit_xml,
)


mcp = FastMCP("llmgrader")


@mcp.tool(name="llmgrader_get_llmgrader_config_structure")
def llmgrader_get_llmgrader_config_structure() -> dict:
    """Return a nested schema object for the llmgrader_config.xml structure.

    The response is JSON-serializable and organized with top-level summary,
    structure, semantic_rules, and examples fields. Under structure, each XML
    element describes its child elements, text content, and whether it is
    required or repeatable.
    """
    return get_llmgrader_config_structure()


@mcp.tool(name="llmgrader_create_config_skeleton")
def llmgrader_create_config_skeleton(
    course_name: str,
    term: str,
    units: list[dict[str, str]],
    assets: list[dict[str, str]] | None = None,
) -> dict:
    """Generate a llmgrader-config.xml skeleton from structured inputs."""
    xml_text = create_config_skeleton(
        course_name=course_name,
        term=term,
        units=units,
        assets=assets,
    )
    return {"xml": xml_text}


@mcp.tool(name="llmgrader_validate_config_xml")
def llmgrader_validate_config_xml(config_xml: str, workspace_root: str | None = None) -> dict:
    """Validate llmgrader-config.xml content and return errors/warnings."""
    return validate_config_xml(config_xml=config_xml, workspace_root=workspace_root)


@mcp.tool(name="llmgrader_scan_repo_for_config_inputs")
def llmgrader_scan_repo_for_config_inputs(workspace_root: str) -> dict:
    """Scan a workspace root for likely unit XMLs and asset directories."""
    return scan_repo_for_config_inputs(workspace_root=workspace_root)


@mcp.tool(name="llmgrader_list_question_examples")
def llmgrader_list_question_examples() -> dict:
    """Return a curated catalog of question XML examples with short summaries and feature hints.

    Use this before authoring a unit XML question so you can inspect
    a valid example with similar structure, such as multipart, partial-credit,
    rubric-heavy, or image-based questions.
    """
    return list_question_examples()


@mcp.tool(name="llmgrader_get_question_example")
def llmgrader_get_question_example(example_id: str) -> dict:
    """Return one curated question XML example by ID.

    The response includes the source filename, qtag, and serialized <question>
    XML snippet so the caller can inspect a valid authoring pattern before
    drafting similar unit XML.
    """
    return get_question_example(example_id)


@mcp.tool(name="llmgrader_get_unit_xml_structure")
def llmgrader_get_unit_xml_structure() -> dict:
    """Return a nested schema object for the unit XML structure.

    The response is JSON-serializable and organized with top-level summary,
    structure, semantic_rules, and examples fields. Under structure, each XML
    element describes its attributes, child elements, text content, and whether
    it is required or repeatable.
    """
    return get_unit_xml_structure()


@mcp.tool(name="llmgrader_plan_question_draft")
def llmgrader_plan_question_draft(
    task: str | None = None,
    workspace_root: str | None = None,
) -> dict:
    """Return a recommended workflow for drafting a new unit XML question.

    Use this before calling llmgrader_create_unit_xml_skeleton when the caller
    needs guidance on example selection, schema review, and validation order.
    """
    return plan_question_draft(task=task, workspace_root=workspace_root)


@mcp.tool(name="llmgrader_explain_rubric_rules")
def llmgrader_explain_rubric_rules() -> dict:
    """Provide guidance for authoring binary and partial-credit rubrics."""
    return explain_rubric_rules()


@mcp.tool(name="llmgrader_create_unit_xml_skeleton")
def llmgrader_create_unit_xml_skeleton(
    unit_id: str,
    title: str | None = None,
    version: str | None = "1.0",
    questions: list[dict] | None = None,
) -> dict:
    """Generate a starter unit XML from structured inputs."""
    xml_text = create_unit_xml_skeleton(
        unit_id=unit_id,
        title=title,
        version=version,
        questions=questions,
    )
    return {"xml": xml_text}


@mcp.tool(name="llmgrader_validate_unit_xml")
def llmgrader_validate_unit_xml(unit_xml: str, workspace_root: str | None = None) -> dict:
    """Validate unit XML content using schema, semantic, and authoring checks."""
    return validate_unit_xml(unit_xml=unit_xml, workspace_root=workspace_root)


@mcp.tool(name="llmgrader_scan_repo_for_unit_inputs")
def llmgrader_scan_repo_for_unit_inputs(workspace_root: str) -> dict:
    """Scan a workspace root for likely unit XML files, rubric examples, assets, and adjacent authoring files."""
    return scan_repo_for_unit_inputs(workspace_root=workspace_root)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
