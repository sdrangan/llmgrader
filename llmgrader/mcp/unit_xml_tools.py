from __future__ import annotations

import os
from pathlib import Path
from xml.etree import ElementTree as ET

from llmgrader.mcp.description_utils import (
    make_attribute_description,
    make_element_description,
    make_related_tool_description,
    make_text_content_description,
)
from llmgrader.services.unit_parser import UnitParser


def get_unit_xml_structure() -> dict:
    """Return a JSON-serializable nested schema description of the unit XML format.

    The returned object is intended for MCP tool output and describes the XML
    element hierarchy, attributes, child elements, text content, semantic rules,
    and examples for the unit XML authoring format.
    """
    return {
        "summary": (
            "A unit XML file describes one unit and its questions, including prompt text, "
            "reference solutions, parts, grading behavior, and optional rubric guidance."
        ),
        "structure": {"unit": _unit_structure()},
        "semantic_rules": [
            "The root element should be <unit> and should include a non-empty id attribute.",
            "A unit should contain at least one <question> element.",
            "Each question should have a unique qtag within the unit.",
            "Each question should include question_text, solution, and parts.",
            "Each part should identify a part_label and points value.",
            "If partial_credit is true and rubrics are used, rubric items should use point_adjustment.",
            "If partial_credit is false and rubrics are used, rubric items should use condition_type and action.",
            "For multi-part questions with rubric_total sum_positive or sum_negative, rubric items should reference concrete part labels rather than part='all'.",
            "For multi-part questions with rubric_total sum_positive, positive rubric items for each part should sum to that part's max points.",
            "Question text may reference packaged assets using /pkg_assets/... URLs after those assets are declared in llmgrader_config.xml.",
        ],
        "examples": {
            "minimal_unit_xml": (
                "<unit id=\"probability_intro\" title=\"Probability Intro\" version=\"1.0\">\n"
                "  <question qtag=\"q1\">\n"
                "    <question_text><![CDATA[\n"
                "    <p>State the sample space for a fair coin toss.</p>\n"
                "    ]]></question_text>\n"
                "    <solution><![CDATA[\n"
                "    <p>The sample space is {H, T}.</p>\n"
                "    ]]></solution>\n"
                "    <required>true</required>\n"
                "    <partial_credit>false</partial_credit>\n"
                "    <parts>\n"
                "      <part>\n"
                "        <part_label>all</part_label>\n"
                "        <points>1</points>\n"
                "      </part>\n"
                "    </parts>\n"
                "  </question>\n"
                "</unit>"
            ),
            "rubric_item_example": {
                "binary": {
                    "condition_type": "positive",
                    "action": "fail",
                    "display_text": "Correct final answer",
                },
                "partial_credit": {
                    "part": "all",
                    "point_adjustment": "+2",
                    "display_text": "Correct setup",
                },
            },
        },
    }


def _question_text_structure() -> dict:
    return make_element_description(
        "Prompt shown to the student; it should be wrapped in CDATA and may contain HTML markup.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Question prompt body, typically stored in CDATA and optionally written as HTML.",
            required=True,
            type="html_or_text",
            example="<p>State the sample space for a fair coin toss.</p>",
        ),
    )


def _solution_structure() -> dict:
    return make_element_description(
        "Reference solution used during grading; it should be wrapped in CDATA and may contain HTML markup.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Reference answer body, typically stored in CDATA and optionally written as HTML.",
            required=True,
            type="html_or_text",
            example="<p>The sample space is {H, T}.</p>",
        ),
    )


def _required_structure() -> dict:
    return make_element_description(
        "Whether the question must be answered.",
        required=False,
        multiple=False,
        text_content=make_text_content_description(
            "Boolean required flag.",
            required=False,
            type="boolean",
            example="true",
            allowed_values=["true", "false"],
        ),
    )


def _partial_credit_structure() -> dict:
    return make_element_description(
        "Whether the question uses partial-credit rubric scoring.",
        required=False,
        multiple=False,
        text_content=make_text_content_description(
            "Boolean partial-credit flag.",
            required=False,
            type="boolean",
            example="false",
            allowed_values=["true", "false"],
        ),
    )


def _tool_structure() -> dict:
    return make_element_description(
        "Optional built-in tool request for the grader.",
        required=False,
        multiple=False,
        text_content=make_text_content_description(
            "Built-in tool name.",
            required=False,
            type="string",
            example="web_search",
            allowed_values=["web_search"],
        ),
    )


def _grading_notes_structure() -> dict:
    return make_element_description(
        "Instructor notes that guide grading interpretation.",
        required=False,
        multiple=False,
        text_content=make_text_content_description(
            "Free-form grading guidance.",
            required=False,
            type="text",
            example="Accept equivalent notation.",
        ),
    )


def _part_label_structure() -> dict:
    return make_element_description(
        "Logical label for the part.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Part identifier.",
            required=True,
            type="string",
            example="all",
        ),
    )


def _points_structure() -> dict:
    return make_element_description(
        "Maximum score for the part.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Point value for the part.",
            required=True,
            type="number",
            example="1",
        ),
    )


def _part_structure() -> dict:
    return make_element_description(
        "One scoring part within the question.",
        required=True,
        multiple=True,
        children={
            "part_label": _part_label_structure(),
            "points": _points_structure(),
        },
    )


def _parts_structure() -> dict:
    return make_element_description(
        "Point structure for the question.",
        required=True,
        multiple=False,
        children={"part": _part_structure()},
    )


def _rubric_display_text_structure() -> dict:
    return make_element_description(
        "Short rubric label shown in feedback.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Rubric item title.",
            required=True,
            type="text",
            example="Correct final answer",
        ),
    )


def _rubric_condition_structure() -> dict:
    return make_element_description(
        "Concrete evidence check for the rubric item.",
        required=True,
        multiple=False,
        text_content=make_text_content_description(
            "Rubric condition text.",
            required=True,
            type="text",
            example="Student gives the correct final answer.",
        ),
    )


def _rubric_notes_structure() -> dict:
    return make_element_description(
        "Optional internal rubric notes.",
        required=False,
        multiple=False,
        text_content=make_text_content_description(
            "Additional rubric note.",
            required=False,
            type="text",
            example="Accept algebraically equivalent forms.",
        ),
    )


def _rubric_item_structure() -> dict:
    return make_element_description(
        "One rubric condition or scoring rule.",
        required=False,
        multiple=True,
        attributes={
            "id": make_attribute_description(
                "Unique rubric item identifier within the question.",
                required=True,
                type="string",
                example="final_answer",
            ),
            "part": make_attribute_description(
                "Part label affected by the rubric item.",
                required=False,
                type="string",
                example="all",
            ),
            "condition_type": make_attribute_description(
                "Binary rubric polarity.",
                required=False,
                type="string",
                example="positive",
                allowed_values=["positive", "negative"],
            ),
            "action": make_attribute_description(
                "Binary rubric action.",
                required=False,
                type="string",
                example="fail",
                allowed_values=["fail", "feedback"],
            ),
            "point_adjustment": make_attribute_description(
                "Partial-credit score adjustment.",
                required=False,
                type="string",
                example="+2",
            ),
        },
        children={
            "display_text": _rubric_display_text_structure(),
            "condition": _rubric_condition_structure(),
            "notes": _rubric_notes_structure(),
        },
    )


def _rubric_group_id_structure() -> dict:
    return make_element_description(
        "Reference to a rubric item id.",
        required=True,
        multiple=True,
        text_content=make_text_content_description(
            "Referenced rubric id.",
            required=True,
            type="string",
            example="method_a",
        ),
    )


def _rubric_group_structure() -> dict:
    return make_element_description(
        "Optional rubric group, typically for alternatives.",
        required=False,
        multiple=True,
        attributes={
            "type": make_attribute_description(
                "Grouping mode.",
                required=True,
                type="string",
                example="one_of",
                allowed_values=["one_of"],
            )
        },
        children={"id": _rubric_group_id_structure()},
    )


def _rubrics_structure() -> dict:
    return make_element_description(
        "Optional rubric items and grouping rules for grading.",
        required=False,
        multiple=False,
        children={
            "item": _rubric_item_structure(),
            "group": _rubric_group_structure(),
        },
        related_tools=[
            make_related_tool_description(
                "llmgrader_explain_rubric_rules",
                when_to_use="Use this tool for more detailed rubric authoring guidance, including binary versus partial-credit rubric rules and rubric_total behavior.",
            )
        ],
    )


def _rubric_total_structure() -> dict:
    return make_element_description(
        "Optional score aggregation mode when partial-credit rubrics are present.",
        required=False,
        multiple=False,
        text_content=make_text_content_description(
            "Rubric aggregation mode.",
            required=False,
            type="string",
            example="sum_positive",
            allowed_values=["sum_positive", "sum_negative", "flexible"],
        ),
    )


def _question_structure() -> dict:
    return make_element_description(
        "One gradeable question in the unit.",
        required=True,
        multiple=True,
        attributes={
            "qtag": make_attribute_description(
                "Question identifier unique within the unit.",
                required=True,
                type="string",
                example="q1",
            ),
            "preferred_model": make_attribute_description(
                "Optional model hint for grading this question.",
                required=False,
                type="string",
                example="gpt-4.1-mini",
            ),
        },
        children={
            "question_text": _question_text_structure(),
            "solution": _solution_structure(),
            "required": _required_structure(),
            "partial_credit": _partial_credit_structure(),
            "tool": _tool_structure(),
            "grading_notes": _grading_notes_structure(),
            "parts": _parts_structure(),
            "rubrics": _rubrics_structure(),
            "rubric_total": _rubric_total_structure(),
        },
    )


def _unit_structure() -> dict:
    return make_element_description(
        "Root element for one authoring unit.",
        required=True,
        multiple=False,
        attributes={
            "id": make_attribute_description(
                "Unique unit identifier.",
                required=True,
                type="string",
                example="probability_intro",
            ),
            "title": make_attribute_description(
                "Human-readable unit title.",
                required=False,
                type="string",
                example="Probability Intro",
            ),
            "version": make_attribute_description(
                "Optional authoring version string.",
                required=False,
                type="string",
                example="1.0",
            ),
        },
        children={"question": _question_structure()},
    )


def explain_rubric_rules() -> dict:
    return {
        "summary": (
            "Rubrics give the grader explicit evidence checks. Binary questions use rubric items as gates or feedback flags, while partial-credit questions use rubric items as score adjustments."
        ),
        "binary_grading_fields": {
            "required_item_fields": ["id", "condition_type", "action", "display_text", "condition"],
            "optional_item_fields": ["notes", "part"],
            "allowed_condition_type_values": ["positive", "negative"],
            "allowed_action_values": ["fail", "feedback"],
        },
        "partial_credit_fields": {
            "required_item_fields": ["id", "point_adjustment", "display_text", "condition"],
            "optional_item_fields": ["notes", "part"],
            "allowed_rubric_total_values": ["sum_positive", "sum_negative", "flexible"],
        },
        "group_rules": {
            "supported_group_types": ["one_of"],
            "description": "Use groups only for rare cases such as alternative valid methods where one listed rubric item should be enough.",
            "minimum_ids": 2,
        },
        "common_mistakes": [
            "Awarding or deducting credit twice for the same evidence.",
            "Using binary fail items for many small details, which makes grading brittle.",
            "Mixing partial-credit point_adjustment with binary-only fields like action and condition_type on the same question mode.",
            "Using part='all' on multi-part sum_positive or sum_negative questions.",
            "Choosing positive partial-credit items whose total does not match the part's max points under sum_positive.",
            "Creating rubric groups that reference unknown ids or only one valid item.",
        ],
        "minimal_examples": {
            "binary": (
                "<rubrics>\n"
                "  <item id=\"final_answer\" condition_type=\"positive\" action=\"fail\">\n"
                "    <display_text>Correct final answer</display_text>\n"
                "    <condition>Student gives the correct final answer.</condition>\n"
                "  </item>\n"
                "</rubrics>"
            ),
            "partial_credit": (
                "<rubrics>\n"
                "  <item id=\"setup\" part=\"all\" point_adjustment=\"+2\">\n"
                "    <display_text>Correct setup</display_text>\n"
                "    <condition>Student sets up the probability expression correctly.</condition>\n"
                "  </item>\n"
                "</rubrics>\n"
                "<rubric_total>sum_positive</rubric_total>"
            ),
        },
        "validation_rules": [
            "Rubric item ids should be unique within a question.",
            "Each rubric item's part should be 'all' or a known part label for the question.",
            "Binary rubric items should use condition_type and action.",
            "Partial-credit rubric items should use point_adjustment.",
            "Group type one_of should include at least two valid rubric ids.",
        ],
        "scope_limitations": [
            "The tool can validate structural and high-confidence semantic rules, but it cannot determine whether rubric items are pedagogically redundant except for a few explicit overlap patterns.",
        ],
    }


def create_unit_xml_skeleton(
    *,
    unit_id: str,
    title: str | None = None,
    version: str | None = "1.0",
    questions: list[dict] | None = None,
) -> str:
    root = ET.Element("unit")
    root.set("id", (unit_id or "").strip())
    if title is not None:
        root.set("title", (title or "").strip())
    if version is not None:
        root.set("version", (version or "").strip())

    question_specs = questions or [_default_question_spec()]
    for question_spec in question_specs:
        _append_question(root, question_spec)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode")


def validate_unit_xml(*, unit_xml: str, workspace_root: str | None = None) -> dict:
    result = UnitParser.validate_unit_text(unit_xml, workspace_root=workspace_root)
    result["checked_rules"] = [
        "XML parsing",
        "unit.xsd schema validation",
        "existing unit semantic validation from UnitParser",
        "high-confidence unit authoring checks from unitxml.md and rubrics.md",
    ]
    return result


def scan_repo_for_unit_inputs(*, workspace_root: str) -> dict:
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists():
        return {"workspace_root": str(root), "error": "Workspace root does not exist."}

    ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache"}
    likely_asset_dir_names = {"images", "image", "assets", "figures", "static"}
    authoring_suffixes = {".html", ".md", ".pdf", ".tex", ".ipynb"}

    unit_xml_candidates: list[str] = []
    rubric_example_candidates: list[str] = []
    asset_directories: list[str] = []
    authoring_files: list[str] = []

    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignored]

        current_path = Path(current_root)
        rel_current = "." if current_path == root else current_path.relative_to(root).as_posix()
        if current_path.name.lower() in likely_asset_dir_names:
            asset_directories.append(rel_current)

        for filename in files:
            file_path = current_path / filename
            rel_path = file_path.relative_to(root).as_posix()
            lower_name = filename.lower()

            if lower_name.endswith(".xml") and filename != "llmgrader_config.xml":
                unit_xml_candidates.append(rel_path)
                try:
                    file_text = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    file_text = ""
                if "<rubrics" in file_text:
                    rubric_example_candidates.append(rel_path)
                continue

            if file_path.suffix.lower() in authoring_suffixes:
                authoring_files.append(rel_path)

    return {
        "workspace_root": str(root),
        "unit_xml_candidates": sorted(unit_xml_candidates)[:50],
        "rubric_example_candidates": sorted(rubric_example_candidates)[:50],
        "asset_directories": sorted(asset_directories)[:50],
        "authoring_files": sorted(authoring_files)[:50],
    }


def _default_question_spec() -> dict:
    return {
        "qtag": "q1",
        "question_text": "Replace with the question prompt.",
        "solution": "Replace with the reference solution.",
        "required": True,
        "partial_credit": False,
        "parts": [{"part_label": "all", "points": 1}],
        "grading_notes": "Add grading notes if needed.",
    }


def _append_question(root: ET.Element, question_spec: dict) -> None:
    question_elem = ET.SubElement(root, "question")
    question_elem.set("qtag", str(question_spec.get("qtag") or "q1").strip())

    preferred_model = question_spec.get("preferred_model")
    if preferred_model:
        question_elem.set("preferred_model", str(preferred_model).strip())

    ET.SubElement(question_elem, "question_text").text = str(
        question_spec.get("question_text") or "Replace with the question prompt."
    )
    ET.SubElement(question_elem, "solution").text = str(
        question_spec.get("solution") or "Replace with the reference solution."
    )

    grading_notes = question_spec.get("grading_notes")
    if grading_notes is not None:
        ET.SubElement(question_elem, "grading_notes").text = str(grading_notes)

    ET.SubElement(question_elem, "required").text = _bool_text(question_spec.get("required", True))
    partial_credit = bool(question_spec.get("partial_credit", False))
    ET.SubElement(question_elem, "partial_credit").text = _bool_text(partial_credit)

    tools = question_spec.get("tools") or []
    if tools:
        ET.SubElement(question_elem, "tool").text = str(tools[0]).strip()

    parts_elem = ET.SubElement(question_elem, "parts")
    for part_spec in question_spec.get("parts") or [{"part_label": "all", "points": 1}]:
        part_elem = ET.SubElement(parts_elem, "part")
        ET.SubElement(part_elem, "part_label").text = str(part_spec.get("part_label") or "all").strip()
        ET.SubElement(part_elem, "points").text = str(part_spec.get("points") or 0)

    rubric_items = question_spec.get("rubrics") or []
    rubric_groups = question_spec.get("rubric_groups") or []
    if rubric_items or rubric_groups:
        rubrics_elem = ET.SubElement(question_elem, "rubrics")
        for rubric_spec in rubric_items:
            item_elem = ET.SubElement(rubrics_elem, "item")
            item_elem.set("id", str(rubric_spec.get("id") or "rubric_item").strip())

            for attr_name in ["part", "condition_type", "action", "point_adjustment"]:
                attr_value = rubric_spec.get(attr_name)
                if attr_value is not None:
                    item_elem.set(attr_name, str(attr_value).strip())

            ET.SubElement(item_elem, "display_text").text = str(
                rubric_spec.get("display_text") or rubric_spec.get("id") or "Rubric item"
            )
            ET.SubElement(item_elem, "condition").text = str(
                rubric_spec.get("condition") or "Replace with a concrete grading condition."
            )
            notes = rubric_spec.get("notes")
            if notes is not None:
                ET.SubElement(item_elem, "notes").text = str(notes)

        for group_spec in rubric_groups:
            group_elem = ET.SubElement(rubrics_elem, "group")
            group_elem.set("type", str(group_spec.get("type") or "one_of").strip())
            for rubric_id in group_spec.get("ids") or []:
                ET.SubElement(group_elem, "id").text = str(rubric_id).strip()

    rubric_total = question_spec.get("rubric_total")
    if rubric_total is not None:
        ET.SubElement(question_elem, "rubric_total").text = str(rubric_total).strip()


def _bool_text(value: object) -> str:
    return "true" if bool(value) else "false"


