import os
import re
import textwrap
import xml.etree.ElementTree as ET

from dataclasses import dataclass
from datetime import datetime
from importlib import resources

import xmlschema


def strip_code_block_leading_newlines(html_text: str) -> str:
    def strip_newlines_match(match):
        code_content = match.group(1)
        stripped_code = code_content.lstrip("\n")
        return f"<pre><code>{stripped_code}</code></pre>"

    pattern = r"<pre><code>(.*?)</code></pre>"
    return re.sub(pattern, strip_newlines_match, html_text, flags=re.DOTALL)


def clean_cdata(text: str) -> str:
    if not text:
        return ""
    if text.startswith("\n"):
        text = text[1:]
    text = textwrap.dedent(text).strip()
    return strip_code_block_leading_newlines(text)


@dataclass
class UnitPackageData:
    units: dict
    units_order: list[dict]
    units_list: list[str]
    xml_path_list: list[str]
    soln_pkg_path: str
    validation_errors: list[str]
    validation_alert: str | None


class UnitParser:
    def __init__(
        self,
        *,
        scratch_dir: str,
        soln_pkg: str | None = None,
        supported_tools: list[str] | None = None,
    ):
        self.scratch_dir = scratch_dir
        self.soln_pkg = soln_pkg
        self.supported_tools = supported_tools or []

    def _empty_package(self, soln_pkg_path: str) -> UnitPackageData:
        return UnitPackageData(
            units={},
            units_order=[],
            units_list=[],
            xml_path_list=[],
            soln_pkg_path=soln_pkg_path,
            validation_errors=[],
            validation_alert=None,
        )

    @staticmethod
    def _schema_path(schema_name: str) -> str:
        return str(resources.files("llmgrader.schemas").joinpath(schema_name))

    @classmethod
    def _load_schema(cls, schema_name: str) -> xmlschema.XMLSchema:
        return xmlschema.XMLSchema(cls._schema_path(schema_name))

    @staticmethod
    def _format_schema_errors(xml_path: str, errors) -> list[str]:
        formatted_errors = []
        for error in errors:
            location = getattr(error, "path", None) or "/"
            reason = getattr(error, "reason", None) or str(error)
            formatted_errors.append(f"{xml_path}: {location}: {reason}")
        return formatted_errors

    @staticmethod
    def _build_validation_alert(validation_errors: list[str]) -> str | None:
        if not validation_errors:
            return None

        unit_count = len({error.split(":", 1)[0] for error in validation_errors})
        noun = "file" if unit_count == 1 else "files"
        verb = "was" if unit_count == 1 else "were"
        return (
            f"Errors in units detected. {unit_count} XML {noun} failed validation and {verb} not loaded. "
            "Run create_soln_pkg to obtain a full error report."
        )

    @classmethod
    def validate_config_file(cls, config_path: str) -> list[str]:
        schema = cls._load_schema("llmgrader_config.xsd")
        return cls._format_schema_errors(config_path, list(schema.iter_errors(config_path)))

    @classmethod
    def validate_unit_file(cls, unit_path: str) -> list[str]:
        schema = cls._load_schema("unit.xsd")
        return cls._format_schema_errors(unit_path, list(schema.iter_errors(unit_path)))

    @classmethod
    def validate_course_package_config(cls, config_path: str) -> list[str]:
        config_path = os.path.abspath(config_path)
        validation_errors = cls.validate_config_file(config_path)
        if validation_errors:
            return validation_errors

        try:
            config_root = ET.parse(config_path).getroot()
        except Exception as exc:
            return [f"{config_path}: /: Failed to parse XML: {exc}"]

        units_elem = config_root.find("units")
        if units_elem is None:
            return [f"{config_path}: /llmgrader: Missing <units> section."]

        config_dir = os.path.dirname(config_path)
        collected_errors: list[str] = []
        for unit_elem in units_elem.findall("unit"):
            unit_name = unit_elem.findtext("name") or "(unnamed unit)"
            source_path = unit_elem.findtext("source")
            destination_path = unit_elem.findtext("destination")

            if not source_path:
                if destination_path:
                    source_path = destination_path
                else:
                    collected_errors.append(
                        f"{config_path}: /llmgrader/units: Unit '{unit_name}' is missing both <source> and <destination>."
                    )
                    continue

            xml_path = os.path.abspath(os.path.join(config_dir, source_path))
            if not os.path.exists(xml_path):
                collected_errors.append(f"{xml_path}: /: File referenced by unit '{unit_name}' does not exist.")
                continue

            collected_errors.extend(cls.validate_unit_file(xml_path))

        return collected_errors

    def _resolve_solution_package_path(self) -> str:
        if self.soln_pkg is not None:
            soln_pkg_path = self.soln_pkg
        else:
            storage_root = os.environ.get("LLMGRADER_STORAGE_PATH")

            if storage_root:
                soln_pkg_path = os.path.join(storage_root, "soln_pkg")
            else:
                local_root = os.path.join(os.getcwd(), "local_data")
                os.makedirs(local_root, exist_ok=True)
                soln_pkg_path = os.path.join(local_root, "soln_pkg")

        soln_pkg_path = os.path.abspath(soln_pkg_path)
        os.makedirs(soln_pkg_path, exist_ok=True)
        return soln_pkg_path

    def _log_question_warning(self, log, unit_name: str, qtag: str, message: str):
        log.write(f"Warning: question {qtag} in unit {unit_name} {message}\n")

    def _parse_rubric_total(
        self,
        question: ET.Element,
        *,
        partial_credit: bool,
        has_rubrics: bool,
        unit_name: str,
        qtag: str,
        log,
    ) -> str | None:
        rubric_total_elem = question.find("rubric_total")
        rubric_total = None
        if rubric_total_elem is not None and rubric_total_elem.text:
            rubric_total = rubric_total_elem.text.strip()

        allowed_values = {"sum_positive", "sum_negative", "flexible"}
        if rubric_total and rubric_total not in allowed_values:
            self._log_question_warning(
                log,
                unit_name,
                qtag,
                f"has invalid rubric_total '{rubric_total}'; defaulting to 'sum_positive'.",
            )
            rubric_total = None

        if not has_rubrics:
            if rubric_total is not None:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    "defines rubric_total without any rubrics; ignoring it.",
                )
            return None

        if not partial_credit:
            if rubric_total is not None:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    "defines rubric_total on a non-partial-credit question; ignoring it.",
                )
            return None

        return rubric_total or "sum_positive"

    def _parse_rubric_item(
        self,
        rubric_item: ET.Element,
        *,
        partial_credit: bool,
        unit_name: str,
        qtag: str,
        log,
    ) -> tuple[str | None, dict | None]:
        item_id = (rubric_item.get("id") or "").strip()
        if not item_id:
            self._log_question_warning(log, unit_name, qtag, "has rubric item without an id; ignoring.")
            return None, None

        allowed_attrs = {"id", "part"}
        if partial_credit:
            allowed_attrs.update({"point_adjustment"})
        else:
            allowed_attrs.update({"condition_type", "action"})

        for attr_name in sorted(rubric_item.attrib):
            if attr_name not in allowed_attrs:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has rubric item {item_id} with unexpected attribute '{attr_name}'; ignoring it.",
                )

        allowed_child_tags = {"display_text", "condition", "notes", "part"}
        for child in rubric_item:
            if child.tag not in allowed_child_tags:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has rubric item {item_id} with unexpected element <{child.tag}>; ignoring it.",
                )

        part = (rubric_item.get("part") or "").strip()
        if not part:
            part_elem = rubric_item.find("part")
            if part_elem is not None and part_elem.text:
                part = part_elem.text.strip()
        if not part:
            part = "all"

        condition_elem = rubric_item.find("condition")
        condition = clean_cdata(condition_elem.text if condition_elem is not None else "")

        display_text_elem = rubric_item.find("display_text")
        display_text = clean_cdata(display_text_elem.text if display_text_elem is not None else "")
        if not display_text:
            display_text = condition

        notes_elem = rubric_item.find("notes")
        notes = clean_cdata(notes_elem.text if notes_elem is not None else "")

        rubric_data = {
            "condition": condition,
            "display_text": display_text,
            "notes": notes,
            "part": part,
        }

        if partial_credit:
            if rubric_item.get("condition_type") is not None:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has partial-credit rubric item {item_id} with attribute 'condition_type', which is only used for binary grading; ignoring it.",
                )
            if rubric_item.get("action") is not None:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has partial-credit rubric item {item_id} with attribute 'action', which is only used for binary grading; ignoring it.",
                )

            point_adjustment_attr = rubric_item.get("point_adjustment")
            if point_adjustment_attr is None:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has partial-credit rubric item {item_id} without a point_adjustment; using 0.0.",
                )
                point_adjustment = 0.0
            else:
                try:
                    point_adjustment = float(point_adjustment_attr)
                except (TypeError, ValueError):
                    self._log_question_warning(
                        log,
                        unit_name,
                        qtag,
                        f"has partial-credit rubric item {item_id} with invalid point adjustment '{point_adjustment_attr}'; using 0.0.",
                    )
                    point_adjustment = 0.0

            rubric_data["point_adjustment"] = point_adjustment
        else:
            if rubric_item.get("point_adjustment") is not None:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has binary rubric item {item_id} with point_adjustment, which is only used for partial-credit grading; ignoring it.",
                )

            condition_type = (rubric_item.get("condition_type") or "").strip().lower()
            if condition_type not in {"positive", "negative"}:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has binary rubric item {item_id} with missing or invalid condition_type; defaulting to 'positive'.",
                )
                condition_type = "positive"

            action = (rubric_item.get("action") or "").strip().lower()
            if action not in {"fail", "feedback"}:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has binary rubric item {item_id} with missing or invalid action; defaulting to 'fail'.",
                )
                action = "fail"

            rubric_data["condition_type"] = condition_type
            rubric_data["action"] = action

        return item_id, rubric_data

    def _parse_rubric_groups(
        self,
        rubrics_elem: ET.Element,
        rubric_ids: set[str],
        *,
        unit_name: str,
        qtag: str,
        log,
    ) -> list[dict]:
        groups: list[dict] = []

        for group_elem in rubrics_elem.findall("group"):
            for attr_name in sorted(group_elem.attrib):
                if attr_name != "type":
                    self._log_question_warning(
                        log,
                        unit_name,
                        qtag,
                        f"has rubric group with unexpected attribute '{attr_name}'; ignoring it.",
                    )

            group_type = (group_elem.get("type") or "").strip()
            if not group_type:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    "has rubric group without a type; ignoring it.",
                )
                continue

            if group_type != "one_of":
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has rubric group with unsupported type '{group_type}'; ignoring it.",
                )
                continue

            group_ids: list[str] = []
            for child in group_elem:
                if child.tag != "id":
                    self._log_question_warning(
                        log,
                        unit_name,
                        qtag,
                        f"has rubric group of type '{group_type}' with unexpected element <{child.tag}>; ignoring it.",
                    )
                    continue

                child_id = (child.text or "").strip()
                if not child_id:
                    self._log_question_warning(
                        log,
                        unit_name,
                        qtag,
                        f"has rubric group of type '{group_type}' with an empty <id>; ignoring it.",
                    )
                    continue
                if child_id in group_ids:
                    self._log_question_warning(
                        log,
                        unit_name,
                        qtag,
                        f"has rubric group of type '{group_type}' with duplicate id '{child_id}'; ignoring the duplicate.",
                    )
                    continue
                if child_id not in rubric_ids:
                    self._log_question_warning(
                        log,
                        unit_name,
                        qtag,
                        f"has rubric group of type '{group_type}' referencing unknown rubric id '{child_id}'; ignoring that reference.",
                    )
                    continue
                group_ids.append(child_id)

            if len(group_ids) < 2:
                self._log_question_warning(
                    log,
                    unit_name,
                    qtag,
                    f"has rubric group of type '{group_type}' with fewer than two valid ids; ignoring it.",
                )
                continue

            groups.append({"type": group_type, "ids": group_ids})

        return groups

    def parse(self) -> UnitPackageData:
        soln_pkg_path = self._resolve_solution_package_path()
        log_path = os.path.join(self.scratch_dir, "load_unit_pkg_log.txt")
        validation_errors: list[str] = []

        with open(log_path, "w", encoding="utf-8") as log:
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log.write(f"Loading unit package at {now}\n")
                log.write(f"Using solution package path: {soln_pkg_path}\n")

                llmgrader_config_path = os.path.join(soln_pkg_path, "llmgrader_config.xml")
                if not os.path.exists(llmgrader_config_path):
                    log.write(f"[ERROR] llmgrader_config.xml not found in solution package: {llmgrader_config_path}\n")
                    package = self._empty_package(soln_pkg_path)
                    package.validation_errors = [f"{llmgrader_config_path}: /: File does not exist."]
                    package.validation_alert = self._build_validation_alert(package.validation_errors)
                    return package

                config_validation_errors = self.validate_config_file(llmgrader_config_path)
                if config_validation_errors:
                    log.write("[ERROR] llmgrader_config.xml failed schema validation.\n")
                    validation_errors.extend(config_validation_errors)
                    for error in config_validation_errors:
                        log.write(f"Validation error: {error}\n")
                    package = self._empty_package(soln_pkg_path)
                    package.validation_errors = validation_errors
                    package.validation_alert = self._build_validation_alert(validation_errors)
                    return package

                try:
                    config_tree = ET.parse(llmgrader_config_path)
                    config_root = config_tree.getroot()
                    log.write("Successfully parsed llmgrader_config.xml\n")
                except Exception as exc:
                    log.write(f"Failed to parse llmgrader_config.xml: {exc}\n")
                    package = self._empty_package(soln_pkg_path)
                    package.validation_errors = [f"{llmgrader_config_path}: /: Failed to parse XML: {exc}"]
                    package.validation_alert = self._build_validation_alert(package.validation_errors)
                    return package

                units_elem = config_root.find("units")
                if units_elem is None:
                    log.write("No <units> section found in llmgrader_config.xml\n")
                    package = self._empty_package(soln_pkg_path)
                    package.validation_errors = [f"{llmgrader_config_path}: /llmgrader: Missing <units> section."]
                    package.validation_alert = self._build_validation_alert(package.validation_errors)
                    return package

                units_order: list[dict] = []
                units_list: list[str] = []
                xml_path_list: list[str] = []

                for child in units_elem:
                    if child.tag == "section":
                        section_name = (child.text or "").strip()
                        units_order.append({"type": "section", "name": section_name})
                        log.write(f"Found section: {section_name}\n")
                    elif child.tag == "unit":
                        name = child.findtext("name")
                        destination = child.findtext("destination")
                        if not name or not destination:
                            log.write("Skipping unit: missing <name> or <destination> element\n")
                            continue
                        units_order.append({"type": "unit", "name": name})
                        units_list.append(name)
                        xml_path_list.append(destination)
                        log.write(f"Found unit in config: {name} -> {destination}\n")

                if not units_list:
                    log.write("No <unit> elements found in llmgrader_config.xml\n")
                    return self._empty_package(soln_pkg_path)

                units = {}

                for name, xml_path in zip(units_list, xml_path_list):
                    xml_path = os.path.normpath(xml_path)
                    xml_path = os.path.join(soln_pkg_path, xml_path)

                    log.write(f"Processing unit: {name}\n")
                    log.write(f"  XML file: {xml_path}\n")

                    if not os.path.exists(xml_path):
                        error = f"{xml_path}: /: File does not exist."
                        validation_errors.append(error)
                        log.write(f"Validation error: {error}\n")
                        continue

                    unit_validation_errors = self.validate_unit_file(xml_path)
                    if unit_validation_errors:
                        validation_errors.extend(unit_validation_errors)
                        log.write(f"Skipping unit {name}: XML schema validation failed.\n")
                        for error in unit_validation_errors:
                            log.write(f"Validation error: {error}\n")
                        continue

                    try:
                        tree = ET.parse(xml_path)
                        root = tree.getroot()
                    except Exception as exc:
                        error = f"{xml_path}: /: Failed to parse XML: {exc}"
                        validation_errors.append(error)
                        log.write(f"Validation error: {error}\n")
                        continue

                    unit_dict = {}

                    for question in root.findall("question"):
                        qtag = question.get("qtag")
                        if not qtag:
                            log.write(f"Skipping question in unit {name}: missing qtag attribute\n")
                            continue

                        preferred_model = question.get("preferred_model", "")

                        question_text_elem = question.find("question_text")
                        question_text = clean_cdata(question_text_elem.text if question_text_elem is not None else "")

                        solution_elem = question.find("solution")
                        solution = clean_cdata(solution_elem.text if solution_elem is not None else "")

                        grading_notes_elem = question.find("grading_notes")
                        grading_notes = clean_cdata(grading_notes_elem.text if grading_notes_elem is not None else "")

                        required_elem = question.find("required")
                        if required_elem is None:
                            required_elem = question.find("grade")
                        if required_elem is not None and required_elem.text:
                            required = required_elem.text.strip().lower() == "true"
                        else:
                            required = True

                        partial_credit_elem = question.find("partial_credit")
                        if partial_credit_elem is not None and partial_credit_elem.text:
                            partial_credit = partial_credit_elem.text.strip().lower() == "true"
                        else:
                            partial_credit = False

                        tools = []
                        for tool_elem in question.findall("tool"):
                            if tool_elem.text is None:
                                continue
                            tool_name = tool_elem.text.strip()
                            if not tool_name:
                                continue
                            if tool_name not in self.supported_tools:
                                log.write(
                                    f"Warning: question {qtag} in unit {name} requested unsupported tool '{tool_name}'; ignoring.\n"
                                )
                                continue
                            tools.append(tool_name)

                        rubrics = {}
                        rubric_groups = []
                        rubrics_elem = question.find("rubrics")
                        if rubrics_elem is not None:
                            for child in rubrics_elem:
                                if child.tag not in {"item", "group"}:
                                    self._log_question_warning(
                                        log,
                                        name,
                                        qtag,
                                        f"has unexpected element <{child.tag}> inside <rubrics>; ignoring it.",
                                    )

                            for rubric_item in rubrics_elem.findall("item"):
                                item_id, rubric_data = self._parse_rubric_item(
                                    rubric_item,
                                    partial_credit=partial_credit,
                                    unit_name=name,
                                    qtag=qtag,
                                    log=log,
                                )
                                if item_id is None or rubric_data is None:
                                    continue
                                rubrics[item_id] = rubric_data

                            rubric_groups = self._parse_rubric_groups(
                                rubrics_elem,
                                set(rubrics.keys()),
                                unit_name=name,
                                qtag=qtag,
                                log=log,
                            )

                        rubric_total = self._parse_rubric_total(
                            question,
                            partial_credit=partial_credit,
                            has_rubrics=bool(rubrics),
                            unit_name=name,
                            qtag=qtag,
                            log=log,
                        )

                        parts = []
                        parts_elem = question.find("parts")
                        if parts_elem is not None:
                            for part in parts_elem.findall("part"):
                                part_id = part.get("id")
                                part_label_elem = part.find("part_label")
                                points_elem = part.find("points")

                                if part_label_elem is not None and part_label_elem.text:
                                    part_label = part_label_elem.text.strip()
                                elif part_id:
                                    part_label = part_id
                                else:
                                    part_label = "all"

                                if points_elem is not None and points_elem.text:
                                    try:
                                        points = float(points_elem.text.strip())
                                    except ValueError:
                                        points = 0.0
                                elif part.get("points"):
                                    try:
                                        points = float(part.get("points"))
                                    except ValueError:
                                        points = 0.0
                                else:
                                    points = 0.0

                                parts.append({"part_label": part_label, "points": points})

                        question_dict = {
                            "qtag": qtag,
                            "question_text": question_text,
                            "solution": solution,
                            "grading_notes": grading_notes,
                            "parts": parts,
                            "required": required,
                            "partial_credit": partial_credit,
                            "tools": tools,
                            "rubrics": rubrics,
                            "rubric_total": rubric_total,
                            "rubric_groups": rubric_groups,
                            "preferred_model": preferred_model,
                        }

                        unit_dict[qtag] = question_dict

                    required_fields = [
                        "qtag",
                        "question_text",
                        "solution",
                        "grading_notes",
                        "parts",
                        "required",
                    ]

                    valid_questions = {}
                    for qtag, qdict in unit_dict.items():
                        missing_fields = [field for field in required_fields if field not in qdict]
                        if missing_fields:
                            log.write(
                                f"Skipping question {qtag} in unit {name}: missing required fields: {missing_fields}\n"
                            )
                            continue
                        valid_questions[qtag] = qdict

                    unit_dict = valid_questions

                    if len(unit_dict) == 0:
                        log.write(f"Skipping unit {name}: no valid questions found\n")
                        continue

                    log.write(f"Unit {name} successfully loaded with questions:\n")
                    for qtag in unit_dict:
                        log.write(f"  qtag={qtag} \n")

                    units[name] = unit_dict

                if len(units) == 0:
                    log.write("No valid directories units found.\n")

                valid_unit_names = set(units.keys())
                filtered_units_order = [
                    item for item in units_order if item["type"] == "section" or item["name"] in valid_unit_names
                ]
                filtered_units_list = [name for name in units_list if name in valid_unit_names]
                filtered_xml_path_list = [
                    xml_path for name, xml_path in zip(units_list, xml_path_list) if name in valid_unit_names
                ]

                return UnitPackageData(
                    units=units,
                    units_order=filtered_units_order,
                    units_list=filtered_units_list,
                    xml_path_list=filtered_xml_path_list,
                    soln_pkg_path=soln_pkg_path,
                    validation_errors=validation_errors,
                    validation_alert=self._build_validation_alert(validation_errors),
                )
            except Exception as exc:
                log.write(f"[ERROR] Exception during unit parsing: {exc}\n")
                package = self._empty_package(soln_pkg_path)
                package.validation_errors = [f"Exception during unit parsing: {exc}"]
                package.validation_alert = self._build_validation_alert(package.validation_errors)
                return package
