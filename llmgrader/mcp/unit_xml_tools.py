from __future__ import annotations

import os
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

from llmgrader.services.unit_parser import UnitParser


def explain_unit_xml() -> dict:
    return {
        "summary": (
            "A unit XML file describes one unit and its questions, including prompt text, "
            "reference solutions, parts, grading behavior, and optional rubric guidance."
        ),
        "required_sections": {
            "unit": {
                "description": "Root <unit> element for the authoring file.",
                "required_attributes": ["id"],
                "recommended_attributes": ["title", "version"],
            },
            "question": {
                "description": "Each <question> defines one gradeable item in the unit.",
                "required_attributes": ["qtag"],
                "required_elements": ["question_text", "solution", "parts"],
                "recommended_elements": ["required", "partial_credit", "grading_notes"],
            },
            "parts": {
                "description": "Defines the point structure for the question.",
                "required_elements": ["part"],
                "recommended_part_fields": ["part_label", "points"],
            },
        },
        "optional_sections": {
            "preferred_model": "Optional model hint for one question.",
            "tool": "Optional built-in tool request. Currently only 'web_search' is supported.",
            "rubrics": "Optional rubric items and one_of groups used to guide grading.",
            "rubric_total": "Optional partial-credit score aggregation mode when rubrics are present.",
            "grading_notes": "Optional instructor notes with interpretation guidance for the grader.",
        },
        "validation_rules": [
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
        "common_authoring_mistakes": [
            "Omitting the unit id or a question qtag.",
            "Leaving question_text or solution blank in an otherwise complete skeleton.",
            "Using partial-credit rubric fields on binary questions or binary rubric fields on partial-credit questions.",
            "Referencing a rubric part that does not exist in <parts>.",
            "Creating overlapping rubric items that double-count the same evidence.",
            "Using unsupported tool values instead of the currently supported web_search tool.",
        ],
        "follow_up_questions": [
            "What unit id and title should be used?",
            "What questions belong in this unit, and what qtags should identify them?",
            "Is each question binary or partial-credit?",
            "What part labels and point values should be used for each question?",
            "Do you want rubric items or grading notes for any question?",
            "Do any questions need packaged assets referenced from /pkg_assets/?",
        ],
        "minimal_example_xml": (
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
        "scope_limitations": [
            "The validator reuses the repo's existing unit schema and semantic checks, then adds a small set of high-confidence authoring checks from the docs.",
            "It does not attempt to judge the quality of question wording or whether a rubric is pedagogically optimal.",
        ],
    }


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
    try:
        root = ET.fromstring(unit_xml)
    except ET.ParseError as exc:
        return {
            "valid": False,
            "errors": [f"Failed to parse XML: {exc}"],
            "warnings": [],
            "checked_rules": [],
        }

    parser_errors = _validate_unit_xml_with_parser(unit_xml)
    authoring_errors, authoring_warnings = _validate_unit_authoring_conventions(root, workspace_root=workspace_root)
    errors = parser_errors + authoring_errors

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": authoring_warnings,
        "checked_rules": [
            "XML parsing",
            "unit.xsd schema validation",
            "existing unit semantic validation from UnitParser",
            "high-confidence unit authoring checks from unitxml.md and rubrics.md",
        ],
    }


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


def _validate_unit_xml_with_parser(unit_xml: str) -> list[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "candidate_unit.xml"
        temp_path.write_text(unit_xml, encoding="utf-8")
        return [
            error.replace(str(temp_path), "<unit_xml>")
            for error in UnitParser.validate_unit_file(str(temp_path))
        ]


def _validate_unit_authoring_conventions(root: ET.Element, *, workspace_root: str | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if root.tag != "unit":
        errors.append("Root element must be <unit>.")
        return errors, warnings

    unit_id = (root.get("id") or "").strip()
    if not unit_id:
        errors.append("Missing required unit id attribute on <unit>.")

    questions = root.findall("question")
    if not questions:
        errors.append("A unit XML should contain at least one <question> element.")
        return errors, warnings

    seen_qtags: set[str] = set()
    supported_tools = {"web_search"}

    for index, question in enumerate(questions, start=1):
        qtag = (question.get("qtag") or "").strip() or f"question[{index}]"
        question_path = f"/unit/question[@qtag='{qtag}']"

        if qtag in seen_qtags:
            errors.append(f"{question_path}: Duplicate qtag '{qtag}'.")
        seen_qtags.add(qtag)

        question_text = (question.findtext("question_text") or "").strip()
        if not question_text:
            errors.append(f"{question_path}: Missing or empty <question_text>.")

        solution = (question.findtext("solution") or "").strip()
        if not solution:
            errors.append(f"{question_path}: Missing or empty <solution>.")

        partial_credit_text = (question.findtext("partial_credit") or "").strip().lower()
        partial_credit = partial_credit_text == "true"
        if partial_credit_text and partial_credit_text not in {"true", "false"}:
            errors.append(f"{question_path}: <partial_credit> must be 'true' or 'false'.")

        tool_value = (question.findtext("tool") or "").strip()
        if tool_value and tool_value not in supported_tools:
            warnings.append(
                f"{question_path}: Unsupported tool '{tool_value}'. The current grader only supports web_search."
            )

        part_labels = _extract_part_labels(question)
        rubric_ids: set[str] = set()
        rubrics_elem = question.find("rubrics")
        rubric_items = rubrics_elem.findall("item") if rubrics_elem is not None else []

        for rubric_index, rubric_item in enumerate(rubric_items, start=1):
            rubric_id = (rubric_item.get("id") or "").strip() or f"rubric[{rubric_index}]"
            rubric_path = f"{question_path}/rubrics/item[@id='{rubric_id}']"

            if rubric_id in rubric_ids:
                errors.append(f"{rubric_path}: Duplicate rubric item id '{rubric_id}'.")
            rubric_ids.add(rubric_id)

            rubric_part = (rubric_item.get("part") or "").strip()
            if not rubric_part:
                part_elem = rubric_item.find("part")
                rubric_part = (part_elem.text or "").strip() if part_elem is not None and part_elem.text else "all"

            if rubric_part != "all" and rubric_part not in part_labels:
                errors.append(f"{rubric_path}: References unknown part '{rubric_part}'.")

            if partial_credit:
                if rubric_item.get("point_adjustment") is None:
                    errors.append(
                        f"{rubric_path}: Partial-credit rubric items should include point_adjustment."
                    )
                if rubric_item.get("condition_type") is not None:
                    warnings.append(
                        f"{rubric_path}: condition_type is ignored for partial-credit rubric items."
                    )
                if rubric_item.get("action") is not None:
                    warnings.append(f"{rubric_path}: action is ignored for partial-credit rubric items.")
            else:
                if rubric_item.get("point_adjustment") is not None:
                    warnings.append(
                        f"{rubric_path}: point_adjustment is ignored for binary rubric items."
                    )
                condition_type = (rubric_item.get("condition_type") or "").strip().lower()
                if condition_type not in {"positive", "negative"}:
                    warnings.append(
                        f"{rubric_path}: Binary rubric items should set condition_type to 'positive' or 'negative'."
                    )
                action = (rubric_item.get("action") or "").strip().lower()
                if action not in {"fail", "feedback"}:
                    warnings.append(
                        f"{rubric_path}: Binary rubric items should set action to 'fail' or 'feedback'."
                    )

        rubric_total = (question.findtext("rubric_total") or "").strip()
        if rubric_total and not rubric_items:
            warnings.append(f"{question_path}: rubric_total is ignored when there are no rubric items.")
        if rubric_total and not partial_credit:
            warnings.append(f"{question_path}: rubric_total is ignored on non-partial-credit questions.")

        if rubrics_elem is not None:
            for group_index, group_elem in enumerate(rubrics_elem.findall("group"), start=1):
                group_path = f"{question_path}/rubrics/group[{group_index}]"
                group_type = (group_elem.get("type") or "").strip()
                if group_type != "one_of":
                    warnings.append(
                        f"{group_path}: Unsupported group type '{group_type or '(missing)'}'; only one_of is supported."
                    )
                    continue

                valid_ids: list[str] = []
                seen_group_ids: set[str] = set()
                for child in group_elem.findall("id"):
                    child_id = (child.text or "").strip()
                    if not child_id:
                        warnings.append(f"{group_path}: Empty rubric group id is ignored.")
                        continue
                    if child_id in seen_group_ids:
                        warnings.append(f"{group_path}: Duplicate rubric group id '{child_id}' is ignored.")
                        continue
                    seen_group_ids.add(child_id)
                    if child_id not in rubric_ids:
                        warnings.append(f"{group_path}: Unknown rubric id '{child_id}' is ignored.")
                        continue
                    valid_ids.append(child_id)

                if len(valid_ids) < 2:
                    warnings.append(
                        f"{group_path}: one_of groups should contain at least two valid rubric ids."
                    )

        if workspace_root:
            warnings.extend(_warn_pkg_asset_references(question, question_path, workspace_root))

    return errors, warnings


def _extract_part_labels(question: ET.Element) -> set[str]:
    part_labels: set[str] = set()
    parts_elem = question.find("parts")
    if parts_elem is None:
        return part_labels

    for part_elem in parts_elem.findall("part"):
        part_label = (part_elem.findtext("part_label") or "").strip()
        if not part_label:
            part_label = (part_elem.get("id") or "").strip() or "all"
        part_labels.add(part_label)

    return part_labels


def _warn_pkg_asset_references(question: ET.Element, question_path: str, workspace_root: str) -> list[str]:
    warnings: list[str] = []
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists():
        return warnings

    for elem_name in ["question_text", "solution"]:
        elem = question.find(elem_name)
        text = ET.tostring(elem, encoding="unicode") if elem is not None else ""
        if "/pkg_assets/" in text:
            config_path = root / "llmgrader_config.xml"
            if not config_path.exists():
                warnings.append(
                    f"{question_path}: Found /pkg_assets/ reference in <{elem_name}> but no llmgrader_config.xml exists under the workspace root for cross-checking."
                )
    return warnings