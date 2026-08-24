"""Instructor-authored grading tests: parsing and static checking.

A grading test file (``<unit_test>``) pairs fake student solutions with a
statement of what the grader should do with them.  This module is the one
place that logic lives; the ``llmgrader_test`` console script and both pytest
suites sit on top of it and add nothing of their own.

Two halves, matching the two cost profiles:

* **static** -- :func:`load_test_file`, :func:`load_unit`, :func:`check_file`.
  Parses the test file, loads the unit it targets, and cross-references the
  two.  No API calls, no key, no :class:`~llmgrader.services.grader.Grader`.
* **runtime** -- the ``run`` half, which grades each case.  See
  ``llmgrader/scripts/llmgrader_test.py``.

The static half carries more of the validation than the XSD does, and that is
by design: which assertion elements are legal in a case depends on the
question's ``<partial_credit>`` mode, which lives in the *unit* file.  A schema
cannot see across files, so ``unit_test.xsd`` type-checks attributes and
:func:`check_file` enforces the pairing.
"""

from __future__ import annotations

import base64
import glob as _glob
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import StringIO
from pathlib import PurePosixPath

from llmgrader.services.unit_parser import UnitParser, clean_cdata


#: Findings at this level fail a `check` run.
LEVEL_ERROR = "error"
#: Findings at this level fail only under ``--strict``.
LEVEL_WARNING = "warning"


class GradeTestError(Exception):
    """A test file or unit could not be read at all.

    Distinct from a :class:`CheckFinding`: a finding is something to report
    about a file that parsed, this is the file refusing to parse.
    """


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class CheckFinding:
    """One problem found by :func:`check_file`.

    ``line`` points into ``file`` when the offending element could be located;
    ``case_id`` names the case it belongs to, so the CLI can group findings.
    """

    level: str
    message: str
    file: str
    line: int | None = None
    case_id: str | None = None

    @property
    def is_error(self) -> bool:
        return self.level == LEVEL_ERROR

    def format(self) -> str:
        """``path: line N: message`` -- the shape the rest of the repo uses."""
        if self.line is not None:
            return f"{self.file}: line {self.line}: {self.message}"
        return f"{self.file}: {self.message}"


# ---------------------------------------------------------------------------
# Test file model
# ---------------------------------------------------------------------------


@dataclass
class RubricExpectation:
    """An assertion about one rubric item's evaluation.

    ``expect`` is the binary-mode form (pins ``rubric_eval[id]["result"]``);
    ``min``/``max`` are the partial-credit form (band on
    ``rubric_eval[id]["point_awarded"]``).  Exactly one form is legal for a
    given question, decided by its grading mode.
    """

    item_id: str
    expect: str | None = None
    min: float | None = None
    max: float | None = None
    line: int | None = None

    @property
    def has_band(self) -> bool:
        return self.min is not None or self.max is not None


@dataclass
class PartExpectation:
    """A band on one part's awarded score."""

    label: str
    min: float | None = None
    max: float | None = None
    line: int | None = None


@dataclass
class TestCase:
    """One fake student solution plus what the grader should do with it."""

    case_id: str
    qtag: str
    description: str
    solution: str
    images: list[str] = field(default_factory=list)
    expected_points: list[PartExpectation] = field(default_factory=list)
    expected_result: str | None = None
    expected_rubrics: list[RubricExpectation] = field(default_factory=list)
    line: int | None = None

    @property
    def has_assertions(self) -> bool:
        return bool(self.expected_points or self.expected_result or self.expected_rubrics)


@dataclass
class UnitTestFile:
    """A parsed ``<unit_test>`` document."""

    path: str
    unit_attr: str | None
    cases: list[TestCase] = field(default_factory=list)

    @property
    def unit_path(self) -> str | None:
        """The unit this file targets, resolved relative to the file itself."""
        if not self.unit_attr:
            return None
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(self.path)), self.unit_attr))


# ---------------------------------------------------------------------------
# Unit model (the half of the check that comes from the course content)
# ---------------------------------------------------------------------------


@dataclass
class QuestionInfo:
    """What a check needs to know about one question in a unit."""

    qtag: str
    partial_credit: bool
    parts: list[dict] = field(default_factory=list)
    rubric_items: dict[str, dict] = field(default_factory=dict)
    rubric_groups: list[dict] = field(default_factory=list)

    @property
    def part_points(self) -> dict[str, float]:
        return {part["part_label"]: float(part["points"]) for part in self.parts}

    @property
    def max_points(self) -> float:
        return sum(float(part["points"]) for part in self.parts)

    def grouped_ids(self) -> set[str]:
        ids: set[str] = set()
        for group in self.rubric_groups:
            ids.update(group.get("ids", []))
        return ids


@dataclass
class UnitInfo:
    """The questions of one unit XML file, keyed by qtag."""

    path: str
    questions: dict[str, QuestionInfo] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return os.path.basename(self.path)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _element_content(elem: ET.Element | None) -> str:
    """Text of an element, preserving inline markup when there is any.

    ``<solution>`` is normally CDATA, in which case this is just the cleaned
    text -- the same treatment ``UnitParser`` gives a question's own solution.
    When markup was written inline instead, it is serialized back so the
    student answer reaches the grader intact.
    """
    if elem is None:
        return ""
    if len(elem) == 0:
        return clean_cdata(elem.text or "")

    inner = elem.text or ""
    for child in elem:
        inner += ET.tostring(child, encoding="unicode")
    return clean_cdata(inner)


def _float_attr(elem: ET.Element, name: str) -> float | None:
    raw = elem.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # The XSD types these as xs:decimal, so a non-numeric value is already
        # a schema error; treating it as absent here keeps parsing from
        # raising on a file the caller is about to report on anyway.
        return None


def _line_lookup(path: str) -> dict[str, int]:
    try:
        return UnitParser._build_xml_line_lookup(path)
    except Exception:
        return {}


def validate_test_file(path: str) -> list[CheckFinding]:
    """Schema-validate a test file against ``unit_test.xsd``.

    Errors come back with line numbers, formatted the way unit validation
    errors are.
    """
    if not os.path.exists(path):
        raise GradeTestError(f"{path}: file does not exist.")

    schema = UnitParser._load_schema("unit_test.xsd")
    try:
        errors = UnitParser._format_schema_errors(path, list(schema.iter_errors(path)))
    except ET.ParseError as exc:
        # Not well-formed XML at all.  That is a file the caller cannot check,
        # not a finding about a file that parsed, so it is raised rather than
        # returned.
        raise GradeTestError(f"{path}: failed to parse XML: {exc}") from exc
    return [CheckFinding(level=LEVEL_ERROR, message=error, file=path) for error in errors]


def load_test_file(path: str) -> UnitTestFile:
    """Parse a ``<unit_test>`` file into a :class:`UnitTestFile`.

    Does not schema-validate -- call :func:`validate_test_file` for that, or
    :func:`check_path`, which does both in the right order.

    Raises
    ------
    GradeTestError
        If the file is missing, is not XML, or is not rooted at ``unit_test``.
    """
    if not os.path.exists(path):
        raise GradeTestError(f"{path}: file does not exist.")

    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        raise GradeTestError(f"{path}: failed to parse XML: {exc}") from exc

    if root.tag != "unit_test":
        raise GradeTestError(f"{path}: root element must be <unit_test>, found <{root.tag}>.")

    lines = _line_lookup(path)
    test_file = UnitTestFile(path=path, unit_attr=(root.get("unit") or "").strip() or None)

    for case_index, case_elem in enumerate(root.findall("case"), start=1):
        case_path = f"/unit_test[1]/case[{case_index}]"
        case = TestCase(
            case_id=(case_elem.get("id") or "").strip(),
            qtag=(case_elem.get("qtag") or "").strip(),
            description=_element_content(case_elem.find("description")),
            solution=_element_content(case_elem.find("solution")),
            line=lines.get(case_path),
        )

        images_elem = case_elem.find("images")
        if images_elem is not None:
            for image_elem in images_elem.findall("image"):
                image = (image_elem.text or "").strip()
                if image:
                    case.images.append(image)

        points_elem = case_elem.find("expected_points")
        if points_elem is not None:
            for part_index, part_elem in enumerate(points_elem.findall("part"), start=1):
                case.expected_points.append(
                    PartExpectation(
                        label=(part_elem.get("label") or "").strip(),
                        min=_float_attr(part_elem, "min"),
                        max=_float_attr(part_elem, "max"),
                        line=lines.get(f"{case_path}/expected_points[1]/part[{part_index}]"),
                    )
                )

        result_elem = case_elem.find("expected_result")
        if result_elem is not None and result_elem.text:
            case.expected_result = result_elem.text.strip()

        rubrics_elem = case_elem.find("expected_rubrics")
        if rubrics_elem is not None:
            for item_index, item_elem in enumerate(rubrics_elem.findall("item"), start=1):
                case.expected_rubrics.append(
                    RubricExpectation(
                        item_id=(item_elem.get("id") or "").strip(),
                        expect=(item_elem.get("expect") or "").strip() or None,
                        min=_float_attr(item_elem, "min"),
                        max=_float_attr(item_elem, "max"),
                        line=lines.get(f"{case_path}/expected_rubrics[1]/item[{item_index}]"),
                    )
                )

        test_file.cases.append(case)

    return test_file


def load_unit(path: str) -> UnitInfo:
    """Read the questions of a unit XML file, for checking against.

    Everything here goes through the ``UnitParser`` helpers the app itself
    uses -- notably ``_parse_partial_credit_for_validation``, which normalizes
    ``<partial_credit>`` from the ``xs:string`` the schema declares.  Reading
    that element directly would risk this module and the grader disagreeing
    about what ``"True"`` means.

    Raises
    ------
    GradeTestError
        If the unit is missing, is not XML, or is not rooted at ``unit``.
    """
    if not os.path.exists(path):
        raise GradeTestError(f"{path}: unit file does not exist.")

    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        raise GradeTestError(f"{path}: failed to parse XML: {exc}") from exc

    if root.tag != "unit":
        raise GradeTestError(f"{path}: root element must be <unit>, found <{root.tag}>.")

    unit = UnitInfo(path=path)
    # _parse_rubric_groups is an instance method that reports malformed groups
    # to a log handle; a throwaway parser plus an in-memory handle reuses it
    # without touching the filesystem.
    group_parser = UnitParser(scratch_dir="")
    sink = StringIO()

    for question in root.findall("question"):
        qtag = (question.get("qtag") or "").strip()
        if not qtag:
            continue

        rubric_items = {
            item["id"]: item
            for item in UnitParser._parse_rubric_items_for_validation(question)
        }

        rubrics_elem = question.find("rubrics")
        if rubrics_elem is not None:
            rubric_groups = group_parser._parse_rubric_groups(
                rubrics_elem,
                set(rubric_items.keys()),
                unit_name=os.path.basename(path),
                qtag=qtag,
                log=sink,
            )
        else:
            rubric_groups = []

        unit.questions[qtag] = QuestionInfo(
            qtag=qtag,
            partial_credit=UnitParser._parse_partial_credit_for_validation(question),
            parts=UnitParser._parse_question_parts_for_validation(question),
            rubric_items=rubric_items,
            rubric_groups=rubric_groups,
        )

    return unit


# ---------------------------------------------------------------------------
# Static checking
# ---------------------------------------------------------------------------


def _band_text(low: float | None, high: float | None) -> str:
    low_text = "-inf" if low is None else _num(low)
    high_text = "+inf" if high is None else _num(high)
    return f"[{low_text}, {high_text}]"


def _num(value: float) -> str:
    """Format a band edge without a trailing ``.0`` on whole numbers."""
    if value == int(value):
        return str(int(value))
    return str(value)


def _achievable_band(point_adjustment: float) -> tuple[float, float]:
    """The range ``point_awarded`` can take for a given ``point_adjustment``.

    A positive adjustment is awarded anywhere in ``[0, adj]`` (the template
    permits partial recognition); a negative one is all-or-nothing, so it is
    either ``adj`` or ``0``.
    """
    if point_adjustment > 0:
        return 0.0, point_adjustment
    if point_adjustment < 0:
        return point_adjustment, 0.0
    return 0.0, 0.0


def unit_authoring_findings(unit_data: UnitInfo) -> list[CheckFinding]:
    """Authoring-convention warnings about the unit the test file targets.

    `check` already has the unit open, and a rubric an instructor is about to
    write tests against is exactly when a convention slip is cheapest to fix.
    Only warnings are carried over: authoring *errors* belong to whatever
    validates the unit itself, and repeating them here would blame the test
    file for a problem it does not have.
    """
    try:
        root = ET.parse(unit_data.path).getroot()
    except (ET.ParseError, OSError):
        # The unit already failed to load, and that is reported elsewhere.
        return []

    _, warnings = UnitParser._validate_unit_authoring_conventions(
        root,
        source_label=unit_data.label,
        workspace_root=None,
    )
    return [
        CheckFinding(level=LEVEL_WARNING, message=warning, file=unit_data.path)
        for warning in warnings
    ]


def check_file(test_file: UnitTestFile, unit_data: UnitInfo, *, coverage: bool = True) -> list[CheckFinding]:
    """Cross-reference a parsed test file against the unit it targets.

    Returns every finding, errors and warnings together, in file order.  The
    caller decides which levels are fatal -- ``--strict`` promotes warnings.
    """
    findings: list[CheckFinding] = []
    path = test_file.path

    def report(level: str, message: str, *, line: int | None = None, case_id: str | None = None) -> None:
        findings.append(
            CheckFinding(level=level, message=message, file=path, line=line, case_id=case_id)
        )

    findings.extend(unit_authoring_findings(unit_data))

    seen_ids: dict[str, int | None] = {}
    # qtag -> rubric ids some case asserts on, for the coverage report
    exercised: dict[str, set[str]] = {}

    for case in test_file.cases:
        case_id = case.case_id or "(missing id)"

        if not case.case_id:
            report(LEVEL_ERROR, "case is missing an id attribute.", line=case.line)
        elif case.case_id in seen_ids:
            first = seen_ids[case.case_id]
            where = f" (first defined on line {first})" if first is not None else ""
            report(
                LEVEL_ERROR,
                f"case `{case_id}`: duplicate case id{where}; ids must be unique within a file.",
                line=case.line,
                case_id=case_id,
            )
        else:
            seen_ids[case.case_id] = case.line

        if not case.description.strip():
            report(
                LEVEL_ERROR,
                f"case `{case_id}`: <description> is empty. It is printed whenever the case "
                "fails, so write it for the person reading the failure.",
                line=case.line,
                case_id=case_id,
            )
        if not case.solution.strip():
            report(
                LEVEL_ERROR,
                f"case `{case_id}`: <solution> is empty; an empty solution grades as a blank "
                "submission and the result means nothing.",
                line=case.line,
                case_id=case_id,
            )

        question = unit_data.questions.get(case.qtag)
        if question is None:
            known = ", ".join(sorted(unit_data.questions)) or "(none)"
            report(
                LEVEL_ERROR,
                f"case `{case_id}`: qtag '{case.qtag}' does not exist in {unit_data.label}. "
                f"Questions in that unit: {known}.",
                line=case.line,
                case_id=case_id,
            )
            continue

        exercised.setdefault(case.qtag, set())

        if not case.has_assertions:
            report(
                LEVEL_WARNING,
                f"case `{case_id}`: no assertions; the case grades but claims nothing.",
                line=case.line,
                case_id=case_id,
            )

        mode = "partial-credit" if question.partial_credit else "binary"
        findings.extend(
            _check_case_against_question(
                case,
                question,
                unit_data=unit_data,
                path=path,
                mode=mode,
                exercised=exercised[case.qtag],
            )
        )

    if coverage:
        findings.extend(_coverage_findings(test_file, unit_data, exercised))

    return findings


def _check_case_against_question(
    case: TestCase,
    question: QuestionInfo,
    *,
    unit_data: UnitInfo,
    path: str,
    mode: str,
    exercised: set[str],
) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    case_id = case.case_id or "(missing id)"

    def report(level: str, message: str, *, line: int | None = None) -> None:
        findings.append(
            CheckFinding(
                level=level,
                message=f"case `{case_id}`: {message}",
                file=path,
                line=line,
                case_id=case_id,
            )
        )

    # -- overall-outcome assertions must match the question's grading mode ---
    if question.partial_credit and case.expected_result is not None:
        report(
            LEVEL_ERROR,
            f"asserts <expected_result> but '{question.qtag}' is {mode}; use <expected_points>.",
            line=case.line,
        )
    if not question.partial_credit and case.expected_points:
        report(
            LEVEL_ERROR,
            f"asserts <expected_points> but '{question.qtag}' is {mode} and has no points to "
            "band; use <expected_result>.",
            line=case.expected_points[0].line or case.line,
        )

    # -- part bands ---------------------------------------------------------
    part_points = question.part_points
    for band in case.expected_points:
        if band.label not in part_points:
            known = ", ".join(part_points) or "(none)"
            report(
                LEVEL_ERROR,
                f"<part label=\"{band.label}\"> does not exist in '{question.qtag}'. "
                f"Parts of that question: {known}.",
                line=band.line,
            )
            continue

        maximum = part_points[band.label]
        if band.min is not None and band.max is not None and band.min > band.max:
            report(
                LEVEL_ERROR,
                f"part '{band.label}' has min {_num(band.min)} above max {_num(band.max)}; "
                "the band can never be satisfied.",
                line=band.line,
            )
        if band.min is not None and band.min < 0:
            report(
                LEVEL_ERROR,
                f"part '{band.label}' has min {_num(band.min)} below 0; scores are never negative.",
                line=band.line,
            )
        if band.max is not None and band.max > maximum:
            report(
                LEVEL_ERROR,
                f"part '{band.label}' has max {_num(band.max)} above the part total "
                f"{_num(maximum)}; the band can never be satisfied.",
                line=band.line,
            )
        if (band.min is None or band.min <= 0) and (band.max is None or band.max >= maximum):
            report(
                LEVEL_WARNING,
                f"part '{band.label}' band {_band_text(band.min, band.max)} spans the whole "
                f"range [0, {_num(maximum)}] and so asserts nothing; tighten it or drop it.",
                line=band.line,
            )

    # -- rubric assertions --------------------------------------------------
    for expectation in case.expected_rubrics:
        item = question.rubric_items.get(expectation.item_id)
        if item is None:
            known = ", ".join(sorted(question.rubric_items)) or "(none)"
            report(
                LEVEL_ERROR,
                f"rubric item '{expectation.item_id}' does not exist in '{question.qtag}'. "
                f"Rubric items of that question: {known}.",
                line=expectation.line,
            )
            continue

        exercised.add(expectation.item_id)

        if question.partial_credit:
            if expectation.expect is not None:
                report(
                    LEVEL_ERROR,
                    f"rubric item '{expectation.item_id}' uses expect=\"{expectation.expect}\" but "
                    f"'{question.qtag}' is {mode}, so the grader returns point_awarded, not a "
                    "result; use min/max.",
                    line=expectation.line,
                )
            if not expectation.has_band:
                report(
                    LEVEL_WARNING,
                    f"rubric item '{expectation.item_id}' has neither min nor max and so asserts "
                    "nothing.",
                    line=expectation.line,
                )
            findings.extend(
                _check_rubric_band(expectation, item, question, path=path, case_id=case_id)
            )
        else:
            if expectation.has_band:
                report(
                    LEVEL_ERROR,
                    f"rubric item '{expectation.item_id}' uses a min/max band but "
                    f"'{question.qtag}' is {mode}, so the grader returns a pass/fail/feedback/n-a "
                    "result, not points; use expect.",
                    line=expectation.line,
                )
            if expectation.expect is None:
                report(
                    LEVEL_WARNING,
                    f"rubric item '{expectation.item_id}' has no expect attribute and so asserts "
                    "nothing.",
                    line=expectation.line,
                )
            elif expectation.expect == "feedback":
                report(
                    LEVEL_WARNING,
                    f"rubric item '{expectation.item_id}' asserts expect=\"feedback\". The binary "
                    "template defines that as useful context but not decisive, which is close to "
                    "a judgment about tone; such cases tend to be unstable across runs.",
                    line=expectation.line,
                )

    return findings


def _check_rubric_band(
    expectation: RubricExpectation,
    item: dict,
    question: QuestionInfo,
    *,
    path: str,
    case_id: str,
) -> list[CheckFinding]:
    """Check a partial-credit rubric band against the item's point_adjustment."""
    findings: list[CheckFinding] = []

    def report(message: str) -> None:
        findings.append(
            CheckFinding(
                level=LEVEL_ERROR,
                message=f"case `{case_id}`: {message}",
                file=path,
                line=expectation.line,
                case_id=case_id,
            )
        )

    if expectation.min is not None and expectation.max is not None and expectation.min > expectation.max:
        report(
            f"rubric item '{expectation.item_id}' has min {_num(expectation.min)} above max "
            f"{_num(expectation.max)}; the band can never be satisfied."
        )
        return findings

    adjustment = item.get("point_adjustment")
    if adjustment is None:
        return findings

    low, high = _achievable_band(float(adjustment))
    outside = (expectation.min is not None and (expectation.min < low or expectation.min > high)) or (
        expectation.max is not None and (expectation.max < low or expectation.max > high)
    )
    if outside:
        report(
            f"rubric item '{expectation.item_id}' band {_band_text(expectation.min, expectation.max)} "
            f"lies outside {_band_text(low, high)}, the range point_awarded can take for "
            f"point_adjustment={_num(float(adjustment))}; the band can never be satisfied."
        )

    return findings


def _coverage_findings(
    test_file: UnitTestFile,
    unit_data: UnitInfo,
    exercised: dict[str, set[str]],
) -> list[CheckFinding]:
    """Rubric items and questions that no case exercises.

    ``one_of`` groups are reported per branch, not per item: a correct
    solution satisfies exactly one branch, so "every item is covered" is the
    wrong completeness criterion for a group.  The right one is "every group
    has a case for each branch".
    """
    findings: list[CheckFinding] = []
    path = test_file.path
    targeted = {case.qtag for case in test_file.cases}

    for qtag, question in unit_data.questions.items():
        if qtag not in targeted:
            findings.append(
                CheckFinding(
                    level=LEVEL_WARNING,
                    message=f"question '{qtag}' in {unit_data.label} has no test cases.",
                    file=path,
                )
            )
            continue

        covered = exercised.get(qtag, set())
        grouped = question.grouped_ids()

        for item_id in question.rubric_items:
            if item_id in grouped or item_id in covered:
                continue
            findings.append(
                CheckFinding(
                    level=LEVEL_WARNING,
                    message=(
                        f"question '{qtag}': rubric item '{item_id}' is not asserted on by any "
                        "case. It is dead weight, a condition the grader cannot recognize, or a "
                        "case you have not written yet."
                    ),
                    file=path,
                )
            )

        for group in question.rubric_groups:
            missing = [item_id for item_id in group.get("ids", []) if item_id not in covered]
            if not missing:
                continue
            branches = ", ".join(group.get("ids", []))
            findings.append(
                CheckFinding(
                    level=LEVEL_WARNING,
                    message=(
                        f"question '{qtag}': one_of group ({branches}) has no case for "
                        f"{', '.join(missing)}. A group needs a case per branch, since a correct "
                        "solution satisfies exactly one."
                    ),
                    file=path,
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Everything a `check` run learned about one test file."""

    test_path: str
    unit_path: str | None
    findings: list[CheckFinding] = field(default_factory=list)
    test_file: UnitTestFile | None = None
    unit: UnitInfo | None = None

    @property
    def errors(self) -> list[CheckFinding]:
        return [finding for finding in self.findings if finding.is_error]

    @property
    def warnings(self) -> list[CheckFinding]:
        return [finding for finding in self.findings if not finding.is_error]

    @property
    def case_count(self) -> int:
        return len(self.test_file.cases) if self.test_file else 0


def resolve_unit_path(test_file: UnitTestFile, unit_override: str | None = None) -> str:
    """Where the unit under test lives.

    ``--unit`` wins; otherwise the ``unit`` attribute, resolved relative to the
    test file so a test file plus its unit move together.
    """
    if unit_override:
        return unit_override
    resolved = test_file.unit_path
    if resolved is None:
        raise GradeTestError(
            f"{test_file.path}: no unit to check against. Add a unit attribute to <unit_test> "
            "or pass --unit."
        )
    return resolved


def check_path(path: str, *, unit_path: str | None = None, coverage: bool = True) -> CheckResult:
    """Schema-validate, parse, and check one test file.

    Schema errors short-circuit: cross-referencing a file whose element names
    did not validate produces confusing follow-on findings.
    """
    schema_findings = validate_test_file(path)
    if schema_findings:
        return CheckResult(test_path=path, unit_path=unit_path, findings=schema_findings)

    test_file = load_test_file(path)
    resolved_unit = resolve_unit_path(test_file, unit_path)
    unit = load_unit(resolved_unit)

    return CheckResult(
        test_path=path,
        unit_path=resolved_unit,
        findings=check_file(test_file, unit, coverage=coverage),
        test_file=test_file,
        unit=unit,
    )


def expand_paths(patterns: list[str]) -> list[str]:
    """Resolve command-line paths, expanding globs the shell may not have.

    ``llmgrader_test check "unit1/tests/*.xml"`` has to work on Windows, where
    the shell leaves the pattern alone, and with a quoted pattern anywhere.
    """
    resolved: list[str] = []
    for pattern in patterns:
        if any(char in pattern for char in "*?[") and not os.path.exists(pattern):
            matches = sorted(_glob.glob(pattern, recursive=True))
            if not matches:
                raise GradeTestError(f"{pattern}: no files match this pattern.")
            resolved.extend(matches)
        else:
            resolved.append(pattern)

    seen: set[str] = set()
    unique: list[str] = []
    for item in resolved:
        key = os.path.normcase(os.path.abspath(item))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# Solution packages
# ---------------------------------------------------------------------------


class PackageContext:
    """A built solution package (directory or ``.zip``) opened for testing.

    ``Grader`` grades against a *package*, not a loose unit file, so ``--pkg``
    is the direct path and the one the pytest suites use.  The only real work
    here is deciding which unit inside the package a given test file targets:
    a package keeps the authoring-time ``<source>`` path in its config even
    though it stores the unit under ``<destination>``, so the test file's
    ``unit`` attribute still matches.
    """

    def __init__(self, pkg_path: str, *, workdir: str | None = None):
        if not os.path.exists(pkg_path):
            raise GradeTestError(f"{pkg_path}: solution package does not exist.")

        self._tempdir: str | None = None
        if os.path.isfile(pkg_path):
            if not pkg_path.lower().endswith(".zip"):
                raise GradeTestError(
                    f"{pkg_path}: a solution package must be a directory or a .zip archive."
                )
            self._tempdir = workdir or tempfile.mkdtemp(prefix="llmgrader_test_pkg_")
            extract_root = os.path.join(self._tempdir, "pkg")
            os.makedirs(extract_root, exist_ok=True)
            try:
                with zipfile.ZipFile(pkg_path) as archive:
                    archive.extractall(extract_root)
            except zipfile.BadZipFile as exc:
                raise GradeTestError(f"{pkg_path}: not a readable zip archive: {exc}") from exc
            self.path = extract_root
        else:
            self.path = os.path.abspath(pkg_path)

        self.config_path = os.path.join(self.path, "llmgrader_config.xml")
        if not os.path.exists(self.config_path):
            raise GradeTestError(
                f"{self.config_path}: not found. --pkg expects a built solution package "
                "containing llmgrader_config.xml."
            )

        try:
            config_root = ET.parse(self.config_path).getroot()
        except Exception as exc:
            raise GradeTestError(f"{self.config_path}: failed to parse XML: {exc}") from exc

        self.entries: list[dict] = []
        units_elem = config_root.find("units")
        for unit_elem in [] if units_elem is None else units_elem.findall("unit"):
            name = (unit_elem.findtext("name") or "").strip()
            destination = (unit_elem.findtext("destination") or "").strip()
            source = (unit_elem.findtext("source") or "").strip()
            if not name or not destination:
                continue
            self.entries.append({"name": name, "source": source, "destination": destination})

        if not self.entries:
            raise GradeTestError(f"{self.config_path}: no <unit> entries with a name and destination.")

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        if self._tempdir is not None:
            shutil.rmtree(self._tempdir, ignore_errors=True)
            self._tempdir = None

    def __enter__(self) -> "PackageContext":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- unit resolution ---------------------------------------------------

    def entry_for(self, test_file: UnitTestFile, unit_override: str | None = None) -> dict:
        """The package unit entry a test file targets.

        Matching is by the config's ``<source>`` path first -- that is the
        authoring-time path the test file's ``unit`` attribute also names --
        then by file name, then by the package having only one unit.
        """
        target = unit_override or test_file.unit_attr
        if not target:
            if len(self.entries) == 1:
                return self.entries[0]
            raise GradeTestError(
                f"{test_file.path}: no unit attribute, and the package has "
                f"{len(self.entries)} units; add a unit attribute or pass --unit."
            )

        if unit_override:
            target_path = os.path.abspath(target)
        else:
            target_path = test_file.unit_path or os.path.abspath(target)
        target_parts = [part for part in PurePosixPath(target_path.replace(os.sep, "/")).parts if part]

        for entry in self.entries:
            source_parts = [
                part for part in PurePosixPath(entry["source"].replace(os.sep, "/")).parts if part
            ]
            if source_parts and target_parts[-len(source_parts):] == source_parts:
                return entry

        target_name = os.path.basename(target_path)
        for entry in self.entries:
            if os.path.basename(entry["destination"]) == target_name:
                return entry
            if entry["source"] and os.path.basename(entry["source"]) == target_name:
                return entry

        if len(self.entries) == 1:
            return self.entries[0]

        known = ", ".join(entry["source"] or entry["destination"] for entry in self.entries)
        raise GradeTestError(
            f"{test_file.path}: unit '{target}' does not match any unit in {self.config_path}. "
            f"Units in that package: {known}."
        )

    def unit_xml_path(self, entry: dict) -> str:
        return os.path.join(self.path, os.path.normpath(entry["destination"]))

    def unit_for(self, test_file: UnitTestFile, unit_override: str | None = None) -> UnitInfo:
        """Load the package unit a test file targets."""
        entry = self.entry_for(test_file, unit_override)
        return load_unit(self.unit_xml_path(entry))


# ---------------------------------------------------------------------------
# Running: options, environment, pricing
# ---------------------------------------------------------------------------


#: Generous next to the app's 20 s default, matching tests/live: these are
#: reasoning models, and a timeout here would read as a broken case.
DEFAULT_TIMEOUT = 90.0

#: `local_data/` is already gitignored, so a report lands somewhere harmless.
DEFAULT_REPORT_PATH = os.path.join("local_data", "gradetests", "report.json")

#: `long_context_threshold` in the registry is an unverified estimate, so any
#: call billed at the long-context rate is priced as a floor, not a figure to
#: quote.  This is why token counts are the default report and dollars are
#: opt-in behind --cost.
LONG_CONTEXT_CAVEAT = (
    "Costs are priced from ModelSpec rates. long_context_threshold is an "
    "unverified estimate, so any call billed at the long-context rate is a "
    "LOWER BOUND on true cost."
)

VERDICT_PASS = "PASS"
VERDICT_WARN = "WARN"
VERDICT_FAIL = "FAIL"
VERDICT_FLAKY = "FLAKY"
VERDICT_ERROR = "ERROR"

#: Verdicts that make the run exit non-zero.  FLAKY is one of them: a case
#: whose verdict depends on the run is not a working test, whichever way the
#: majority fell.
FAILING_VERDICTS = frozenset({VERDICT_FAIL, VERDICT_FLAKY, VERDICT_ERROR})

#: Float comparisons against authored bands; scores are small decimals.
_TOLERANCE = 1e-9


def price_call(spec, tokens_in: int, tokens_out: int) -> tuple[float, bool]:
    """Return ``(usd, used_long_rate)`` for one call, per the ModelSpec rates.

    The long-context pair is selected when the request's input exceeds
    ``long_context_threshold`` -- otherwise an estimate comes out roughly 2x
    optimistic on exactly the calls where the number matters most.
    """
    if spec is None:
        return 0.0, False

    long_rate = (
        spec.long_context_threshold is not None
        and tokens_in > spec.long_context_threshold
        and spec.usd_per_mtok_in_long is not None
        and spec.usd_per_mtok_out_long is not None
    )
    if long_rate:
        rate_in, rate_out = spec.usd_per_mtok_in_long, spec.usd_per_mtok_out_long
    else:
        rate_in, rate_out = spec.usd_per_mtok_in, spec.usd_per_mtok_out

    return (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000, bool(long_rate)


@dataclass
class RunOptions:
    """Everything a run needs that is not the test files themselves."""

    unit: str | None = None
    pkg: str | None = None
    model: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    api_key: str | None = None
    repeat: int = 1
    jobs: int = 4
    keep_db: bool = False
    fail_fast: bool = False
    dry_run: bool = False
    qtags: list[str] | None = None
    case_ids: list[str] | None = None
    max_calls: int | None = None
    out: str | None = DEFAULT_REPORT_PATH
    html: str | None = None
    cost: bool = False


class RunEnvironment:
    """Throwaway storage and scratch trees for one run.

    ``Grader.__init__`` deletes and recreates its scratch directory, opens a
    SQLite database at ``get_storage_path()``, and writes a submission row for
    every grade.  Left alone, a grading test run would fill the instructor's
    ``local_data/`` with fake submissions that then show up in the dashboard
    and in any later replay.  Redirecting ``LLMGRADER_STORAGE_PATH`` is the
    same fix ``tests/live/conftest.py`` uses.

    The variable is process-global, so it is restored on close, and the
    temporary tree is removed unless ``keep_db`` asks to keep it.
    """

    _ENV_VAR = "LLMGRADER_STORAGE_PATH"

    def __init__(self, *, keep_db: bool = False):
        self.keep_db = keep_db
        self.root = tempfile.mkdtemp(prefix="llmgrader_gradetests_")
        self.storage = os.path.join(self.root, "storage")
        self.scratch = os.path.join(self.root, "scratch")
        self.packages = os.path.join(self.root, "packages")
        for path in (self.storage, self.scratch, self.packages):
            os.makedirs(path, exist_ok=True)

        self._previous = os.environ.get(self._ENV_VAR)
        os.environ[self._ENV_VAR] = self.storage

    @property
    def db_path(self) -> str:
        return os.path.join(self.storage, "db", "llmgrader.db")

    def scratch_for(self, index: int) -> str:
        path = os.path.join(self.scratch, f"grader{index}")
        os.makedirs(path, exist_ok=True)
        return path

    def package_dir(self, index: int) -> str:
        return os.path.join(self.packages, f"unit{index}")

    def close(self) -> None:
        if self._previous is None:
            os.environ.pop(self._ENV_VAR, None)
        else:
            os.environ[self._ENV_VAR] = self._previous
        if not self.keep_db:
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "RunEnvironment":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Package synthesis for --unit (caveat 3)
# ---------------------------------------------------------------------------


_IMG_SRC_RE = re.compile(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)

#: How far up from a unit file to look for the course config, so a
#: synthesized package can replicate its /pkg_assets/ mappings.
_CONFIG_SEARCH_DEPTH = 4


def find_course_config(unit_path: str) -> str | None:
    """The nearest ``llmgrader_config.xml`` above a loose unit file, if any."""
    directory = os.path.dirname(os.path.abspath(unit_path))
    for _ in range(_CONFIG_SEARCH_DEPTH):
        candidate = os.path.join(directory, "llmgrader_config.xml")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return None


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _replay_assets(config_path: str, dest_dir: str) -> None:
    """Copy a course config's <assets> mappings into a synthesized package."""
    try:
        root = ET.parse(config_path).getroot()
    except Exception:
        return

    config_dir = os.path.dirname(os.path.abspath(config_path))
    package_root = os.path.abspath(dest_dir)
    assets_elem = root.find("assets")
    for asset in [] if assets_elem is None else assets_elem.findall("asset"):
        source = (asset.findtext("source") or "").strip()
        destination = (asset.findtext("destination") or "").strip()
        if not source or not destination:
            continue

        source_path = os.path.normpath(os.path.join(config_dir, source))
        dest_path = os.path.abspath(os.path.normpath(os.path.join(dest_dir, destination)))
        if os.path.commonpath([dest_path, package_root]) != package_root:
            continue  # a destination escaping the package is a packaging bug

        if os.path.isdir(source_path):
            shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
        elif os.path.isfile(source_path):
            os.makedirs(os.path.dirname(dest_path) or package_root, exist_ok=True)
            shutil.copy2(source_path, dest_path)


def synthesize_package(unit_path: str, dest_dir: str) -> tuple[str, str]:
    """Build a one-unit solution package around a loose unit file.

    ``Grader`` loads a package, not a unit file, so ``--unit`` has to make one.
    The subtlety is images: ``_extract_solution_images`` resolves a relative
    ``src`` against the unit's own directory and a ``/pkg_assets/<path>`` src
    against the *package root*, and the mapping from a source directory to its
    ``pkg_assets`` name lives in the course config rather than in the unit.  So
    sibling directories are carried across for the first case, and the course
    config's ``<assets>`` entries are replayed for the second.

    Returns ``(package_dir, unit_name)``.
    """
    unit_path = os.path.abspath(unit_path)
    if not os.path.isfile(unit_path):
        raise GradeTestError(f"{unit_path}: unit file does not exist.")

    os.makedirs(dest_dir, exist_ok=True)
    unit_dir = os.path.dirname(unit_path)
    unit_file = os.path.basename(unit_path)
    shutil.copy2(unit_path, os.path.join(dest_dir, unit_file))

    # Relative <img src="images/..."> resolves against the unit's directory.
    for entry in sorted(os.listdir(unit_dir)):
        source = os.path.join(unit_dir, entry)
        if not os.path.isdir(source) or entry.startswith(".") or entry == "tests":
            continue
        shutil.copytree(source, os.path.join(dest_dir, entry), dirs_exist_ok=True)

    # /pkg_assets/<name> resolves against the package root.
    config_path = find_course_config(unit_path)
    if config_path is not None:
        _replay_assets(config_path, dest_dir)

    try:
        title = ET.parse(unit_path).getroot().get("title") or ""
    except Exception:
        title = ""
    unit_name = " ".join(title.split()) or os.path.splitext(unit_file)[0]

    config = (
        "<llmgrader>\n"
        "  <course>\n"
        "    <name>Grading tests</name>\n"
        "    <semester>n/a</semester>\n"
        "  </course>\n"
        "  <units>\n"
        "    <unit>\n"
        f"      <name>{_xml_escape(unit_name)}</name>\n"
        f"      <source>{_xml_escape(unit_file)}</source>\n"
        f"      <destination>{_xml_escape(unit_file)}</destination>\n"
        "    </unit>\n"
        "  </units>\n"
        "</llmgrader>\n"
    )
    with open(os.path.join(dest_dir, "llmgrader_config.xml"), "w", encoding="utf-8") as handle:
        handle.write(config)

    return dest_dir, unit_name


def missing_reference_images(question_dict: dict) -> int:
    """How many ``<img>`` sources in a question's solution failed to resolve.

    A silently dropped reference image changes what the grader sees, so a
    synthesized package that loses one must say so rather than grade against
    less than the real thing.
    """
    solution = str(question_dict.get("solution") or "")
    declared = sum(1 for src in _IMG_SRC_RE.findall(solution) if not src.startswith("data:"))
    resolved = len(question_dict.get("solution_images") or [])
    return max(0, declared - resolved)


def load_case_images(case: TestCase, test_file_path: str) -> list[str]:
    """Turn a case's ``<images>`` entries into the data URIs the grader wants.

    Paths resolve relative to the test file, so a case and the image it
    attaches move together.
    """
    if not case.images:
        return []

    base = os.path.dirname(os.path.abspath(test_file_path))
    data_uris: list[str] = []
    for entry in case.images:
        if entry.startswith("data:"):
            data_uris.append(entry)
            continue

        path = os.path.normpath(os.path.join(base, entry))
        if not os.path.isfile(path):
            raise GradeTestError(
                f"{test_file_path}: case `{case.case_id}` attaches image '{entry}', "
                f"which does not exist at {path}."
            )
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
        data_uris.append(f"data:{mime};base64,{encoded}")

    return data_uris


# ---------------------------------------------------------------------------
# Evaluation: GradeResult against a case's expectations
# ---------------------------------------------------------------------------


def part_scores(question_dict: dict, grade: dict) -> dict[str, float]:
    """Awarded points per part label, from whichever shape ``grade`` used.

    ``point_parts`` is a list aligned with the question's parts when the whole
    question was graded, and a bare number for a single-part question.
    """
    labels = [part.get("part_label") for part in question_dict.get("parts") or []]
    point_parts = grade.get("point_parts")

    if isinstance(point_parts, list):
        return {
            label: float(value)
            for label, value in zip(labels, point_parts)
            if label is not None and value is not None
        }
    if point_parts is None or len(labels) != 1:
        return {}
    return {labels[0]: float(point_parts)}


def _band_margin(band: PartExpectation, actual: float, part_total: float | None) -> float | None:
    """How close a passing score sits to an edge the score could actually cross.

    An edge at 0 or at the part's own total is not a real edge: no score can
    fall below zero or rise above the maximum, so landing on it is not the
    flakiness signal a margin is meant to report.  A full-credit control
    banded ``[9, 10]`` on a 10-point part scoring 10 is exactly right, not one
    run from failing.  Only genuine ranges get a margin -- an exact band is a
    deliberate pin, not a range with no room in it.
    """
    if band.min is None or band.max is None or band.max <= band.min:
        return None

    distances = []
    if band.min > 0:
        distances.append(actual - band.min)
    if part_total is None or band.max < part_total:
        distances.append(band.max - actual)
    return min(distances) if distances else None


def evaluate_attempt(case: TestCase, question_dict: dict, grade: dict) -> tuple[list[str], float | None]:
    """Compare one graded result to a case's expectations.

    Returns ``(failures, margin)``.  Each failure is a line the terminal and
    both reports print verbatim, so it names the part or the rubric item and
    quotes both numbers.  ``margin`` is how close a passing score landed to the
    nearest edge of a *range* band -- an exact band has no margin to speak of,
    and a case sitting at margin 0 is the one that flakes next month.
    """
    failures: list[str] = []
    margins: list[float] = []
    rubric_eval = grade.get("rubric_eval") or {}

    def rubric_entry(item_id: str) -> dict | None:
        entry = rubric_eval.get(item_id)
        if entry is None:
            failures.append(f"rubric `{item_id}`: not evaluated by the grader")
            return None
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        return entry

    if question_dict.get("partial_credit"):
        scores = part_scores(question_dict, grade)
        totals = {
            part.get("part_label"): float(part.get("points") or 0.0)
            for part in question_dict.get("parts") or []
        }
        for band in case.expected_points:
            actual = scores.get(band.label)
            if actual is None:
                failures.append(f"part '{band.label}': not scored by the grader")
                continue

            expected = _band_text(band.min, band.max)
            if band.min is not None and actual < band.min - _TOLERANCE:
                failures.append(
                    f"part '{band.label}': scored {_num(actual)}, expected {expected}, "
                    f"under by {_num(round(band.min - actual, 6))}"
                )
            elif band.max is not None and actual > band.max + _TOLERANCE:
                failures.append(
                    f"part '{band.label}': scored {_num(actual)}, expected {expected}, "
                    f"over by {_num(round(actual - band.max, 6))}"
                )
            else:
                margin = _band_margin(band, actual, totals.get(band.label))
                if margin is not None:
                    margins.append(margin)

        for expectation in case.expected_rubrics:
            entry = rubric_entry(expectation.item_id)
            if entry is None:
                continue
            awarded = entry.get("point_awarded")
            if awarded is None:
                failures.append(
                    f"rubric `{expectation.item_id}`: the grader returned no point_awarded "
                    "for this item"
                )
                continue
            awarded = float(awarded)
            below = expectation.min is not None and awarded < expectation.min - _TOLERANCE
            above = expectation.max is not None and awarded > expectation.max + _TOLERANCE
            if below or above:
                failures.append(
                    f"rubric `{expectation.item_id}`: expected point_awarded in "
                    f"{_band_text(expectation.min, expectation.max)}, got {_num(awarded)}"
                )
    else:
        if case.expected_result is not None:
            actual = grade.get("result")
            if actual != case.expected_result:
                failures.append(f"result: expected '{case.expected_result}', got '{actual}'")

        for expectation in case.expected_rubrics:
            entry = rubric_entry(expectation.item_id)
            if entry is None or expectation.expect is None:
                continue
            actual = entry.get("result")
            if actual != expectation.expect:
                failures.append(
                    f"rubric `{expectation.item_id}`: expected result '{expectation.expect}', "
                    f"got '{actual}'"
                )

    return failures, (min(margins) if margins else None)


def rubric_evidence(grade: dict, item_id: str) -> str:
    """The evidence string the grader cited for one rubric item, if any."""
    entry = (grade.get("rubric_eval") or {}).get(item_id)
    if hasattr(entry, "model_dump"):
        entry = entry.model_dump()
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("evidence") or "")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class AttemptResult:
    """One grading call: what came back, and which expectations it broke."""

    case_id: str
    qtag: str
    unit_name: str
    file: str
    repeat_index: int
    session_id: str
    model: str
    description: str = ""
    solution: str = ""
    points: float | None = None
    max_points: float | None = None
    part_scores: dict = field(default_factory=dict)
    result: str | None = None
    feedback: str = ""
    full_explanation: str = ""
    rubric_eval: dict = field(default_factory=dict)
    expectations: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    margin: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None
    timed_out: bool = False
    reference_image_count: int = 0
    question_text: str = ""
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and not self.failures

    @property
    def verdict(self) -> str:
        if self.error is not None:
            return VERDICT_ERROR
        if self.failures:
            return VERDICT_FAIL
        if self.margin is not None and self.margin <= _TOLERANCE:
            return VERDICT_WARN
        return VERDICT_PASS

    def failed_rubric_ids(self) -> set[str]:
        """Rubric items an expectation failed on, for highlighting."""
        return {
            match.group(1)
            for match in (re.match(r"rubric `([^`]+)`", failure) for failure in self.failures)
            if match
        }

    def failed_part_labels(self) -> set[str]:
        return {
            match.group(1)
            for match in (re.match(r"part '([^']+)'", failure) for failure in self.failures)
            if match
        }

    def failure_lines(self) -> list[tuple[str, str]]:
        """Each failure paired with the evidence behind it, where there is one.

        A failing rubric assertion is only actionable next to the evidence the
        grader cited for that item, so the pairing happens here rather than in
        the terminal code.
        """
        lines: list[tuple[str, str]] = []
        for failure in self.failures:
            match = re.match(r"rubric `([^`]+)`", failure)
            evidence = ""
            if match:
                entry = self.rubric_eval.get(match.group(1))
                if hasattr(entry, "model_dump"):
                    entry = entry.model_dump()
                if isinstance(entry, dict):
                    evidence = str(entry.get("evidence") or "")
            lines.append((failure, evidence))
        return lines

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "case_id": self.case_id,
            "qtag": self.qtag,
            "unit_name": self.unit_name,
            "repeat": self.repeat_index,
            "session_id": self.session_id,
            "model": self.model,
            "description": self.description,
            "solution": self.solution,
            "points": self.points,
            "max_points": self.max_points,
            "part_scores": self.part_scores,
            "result": self.result,
            "feedback": self.feedback,
            "full_explanation": self.full_explanation,
            "rubric_eval": self.rubric_eval,
            "expectations": self.expectations,
            "failures": self.failures,
            "margin": self.margin,
            "verdict": self.verdict,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "timed_out": self.timed_out,
            "error": self.error,
        }


@dataclass
class CaseRun:
    """Every attempt at one case, and the verdict across them."""

    case_id: str
    qtag: str
    file: str
    description: str
    partial_credit: bool
    model: str
    attempts: list[AttemptResult] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if not self.attempts:
            return VERDICT_ERROR
        if any(attempt.error is not None for attempt in self.attempts):
            return VERDICT_ERROR

        passed = [attempt.passed for attempt in self.attempts]
        if all(passed):
            margins = [
                attempt.margin for attempt in self.attempts if attempt.margin is not None
            ]
            if margins and min(margins) <= _TOLERANCE:
                return VERDICT_WARN
            return VERDICT_PASS
        if not any(passed):
            return VERDICT_FAIL
        return VERDICT_FLAKY

    @property
    def failures(self) -> list[str]:
        seen: list[str] = []
        for attempt in self.attempts:
            for failure in attempt.failures:
                if failure not in seen:
                    seen.append(failure)
        return seen

    @property
    def scores(self) -> list[float | None]:
        return [attempt.points for attempt in self.attempts]

    @property
    def pass_count(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.passed)


@dataclass
class FileRun:
    """One test file's worth of cases."""

    path: str
    unit_label: str
    unit_file: str = ""
    cases: list[CaseRun] = field(default_factory=list)


@dataclass
class RunReport:
    """Everything one `run` invocation produced."""

    files: list[FileRun] = field(default_factory=list)
    storage_path: str = ""
    planned_calls: int = 0
    planned_by_model: dict = field(default_factory=dict)
    dry_run: bool = False
    elapsed_seconds: float = 0.0
    report_path: str | None = None
    html_path: str | None = None
    kept_db: bool = False

    @property
    def cases(self) -> list[CaseRun]:
        return [case for file_run in self.files for case in file_run.cases]

    @property
    def attempts(self) -> list[AttemptResult]:
        return [attempt for case in self.cases for attempt in case.attempts]

    @property
    def calls(self) -> int:
        return len(self.attempts)

    @property
    def verdicts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.verdict] = counts.get(case.verdict, 0) + 1
        return counts

    @property
    def failed(self) -> int:
        return sum(
            count for verdict, count in self.verdicts.items() if verdict in FAILING_VERDICTS
        )

    @property
    def warned(self) -> int:
        return self.verdicts.get(VERDICT_WARN, 0)

    @property
    def tokens_in(self) -> int:
        return sum(attempt.tokens_in or 0 for attempt in self.attempts)

    @property
    def tokens_out(self) -> int:
        return sum(attempt.tokens_out or 0 for attempt in self.attempts)

    def estimated_cost(self) -> tuple[float, bool]:
        """``(usd, any_long_context)`` from the registry rates. See --cost."""
        from llmgrader.services.models import get_spec

        total = 0.0
        long_rate_seen = False
        for attempt in self.attempts:
            usd, long_rate = price_call(
                get_spec(attempt.model), attempt.tokens_in or 0, attempt.tokens_out or 0
            )
            total += usd
            long_rate_seen = long_rate_seen or long_rate
        return total, long_rate_seen

    def to_dict(self) -> dict:
        usd, long_rate = self.estimated_cost()
        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "files": len(self.files),
                "cases": len(self.cases),
                "calls": self.calls,
                "verdicts": self.verdicts,
                "failed": self.failed,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "elapsed_seconds": round(self.elapsed_seconds, 3),
                "planned_calls": self.planned_calls,
                "planned_by_model": self.planned_by_model,
                "estimated_usd": usd,
                "estimated_usd_is_lower_bound": long_rate,
                "cost_note": LONG_CONTEXT_CAVEAT,
            },
            "cases": [
                {
                    "file": case.file,
                    "case_id": case.case_id,
                    "qtag": case.qtag,
                    "description": case.description,
                    "partial_credit": case.partial_credit,
                    "model": case.model,
                    "verdict": case.verdict,
                    "passed": case.pass_count,
                    "attempts": len(case.attempts),
                    "scores": case.scores,
                    "failures": case.failures,
                }
                for case in self.cases
            ],
            "results": [attempt.to_dict() for attempt in self.attempts],
        }


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


@dataclass
class _PlannedCase:
    """One case, bound to the grader and model that will run it."""

    case: TestCase
    case_run: CaseRun
    grader: object
    question_dict: dict
    unit_name: str
    model: str
    file_path: str


def submission_usage(db_path: str, session_id: str) -> dict:
    """Token counts and latency for one grading call, keyed by session id.

    ``Grader.grade`` returns only the GradeResult and records usage as a side
    effect, in the submission row it writes.  ``tests/live/conftest.py`` reads
    that row back with ``ORDER BY rowid DESC LIMIT 1``, which is correct for a
    serial suite and wrong under ``--jobs``: with concurrent calls the newest
    row is not necessarily the one that just finished.  ``session_id`` is
    stored as the row's ``client_id``, so the runner passes a synthetic one per
    attempt and looks the row up by that key instead.
    """
    if not os.path.exists(db_path):
        return {}

    connection = sqlite3.connect(db_path)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT model, tokens_in, tokens_out, latency_ms, timed_out "
            "FROM submissions WHERE client_id = ? ORDER BY rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        connection.close()
    return dict(row) if row is not None else {}


def _plain_rubric_eval(grade: dict) -> dict:
    plain: dict = {}
    for item_id, entry in (grade.get("rubric_eval") or {}).items():
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        plain[item_id] = entry
    return plain


def _expectations(case: TestCase) -> dict:
    return {
        "result": case.expected_result,
        "points": [
            {"label": band.label, "min": band.min, "max": band.max}
            for band in case.expected_points
        ],
        "rubrics": [
            {
                "id": expectation.item_id,
                "expect": expectation.expect,
                "min": expectation.min,
                "max": expectation.max,
            }
            for expectation in case.expected_rubrics
        ],
    }


def _select_cases(cases: list[TestCase], qtags, case_ids) -> list[TestCase]:
    if qtags:
        wanted = set(qtags)
        cases = [case for case in cases if case.qtag in wanted]
    if case_ids:
        wanted = set(case_ids)
        cases = [case for case in cases if case.case_id in wanted]
    return cases


def _plan_run(paths, options: RunOptions, env: RunEnvironment, pkg_context, model_override):
    """Resolve every case to a grader, a question and a model. No API calls."""
    from llmgrader.services.grader import Grader, preferred_model_for
    from llmgrader.services.models import DEFAULT_MODEL_SIMPLE

    graders: dict = {}
    files: list[FileRun] = []
    planned: list[_PlannedCase] = []

    for path in paths:
        if validate_test_file(path):
            raise GradeTestError(
                f"{path}: does not validate against unit_test.xsd. "
                "Run `llmgrader_test check` on it for the details."
            )

        test_file = load_test_file(path)
        cases = _select_cases(test_file.cases, options.qtags, options.case_ids)

        if pkg_context is not None:
            entry = pkg_context.entry_for(test_file, options.unit)
            key = ("pkg", entry["destination"])
            unit_name = entry["name"]
            package_dir = pkg_context.path
        else:
            unit_path = resolve_unit_path(test_file, options.unit)
            key = ("unit", os.path.normcase(os.path.abspath(unit_path)))
            unit_name = None
            package_dir = None

        if key not in graders:
            index = len(graders)
            if package_dir is None:
                package_dir, unit_name = synthesize_package(unit_path, env.package_dir(index))
            grader = Grader(scratch_dir=env.scratch_for(index), soln_pkg=package_dir)
            if grader.unit_validation_errors:
                raise GradeTestError(
                    "the unit under test failed validation:\n  "
                    + "\n  ".join(grader.unit_validation_errors)
                )
            graders[key] = (grader, unit_name)

        grader, unit_name = graders[key]
        questions = grader.units.get(unit_name)
        if not questions:
            known = ", ".join(sorted(grader.units)) or "(none)"
            raise GradeTestError(
                f"{path}: unit '{unit_name}' loaded no questions. Units available: {known}."
            )

        unit_file = (
            os.path.basename(entry["destination"])
            if pkg_context is not None
            else os.path.basename(unit_path)
        )
        file_run = FileRun(path=path, unit_label=unit_name, unit_file=unit_file)
        for case in cases:
            question_dict = questions.get(case.qtag)
            if question_dict is None:
                raise GradeTestError(
                    f"{path}: case `{case.case_id}` targets qtag '{case.qtag}', which is not in "
                    f"'{unit_name}'. Run `llmgrader_test check` first -- it finds this for free."
                )

            missing = missing_reference_images(question_dict)
            if missing and pkg_context is None:
                raise GradeTestError(
                    f"{path}: {missing} reference image(s) for qtag '{case.qtag}' did not resolve "
                    f"in the package synthesized from {unit_path}. Grading without them would "
                    "test something other than what students hit. Build a solution package and "
                    "pass --pkg instead."
                )

            model = model_override or preferred_model_for(question_dict, case.qtag) or DEFAULT_MODEL_SIMPLE
            case_run = CaseRun(
                case_id=case.case_id,
                qtag=case.qtag,
                file=path,
                description=case.description,
                partial_credit=bool(question_dict.get("partial_credit")),
                model=model,
            )
            file_run.cases.append(case_run)
            planned.append(
                _PlannedCase(
                    case=case,
                    case_run=case_run,
                    grader=grader,
                    question_dict=question_dict,
                    unit_name=unit_name,
                    model=model,
                    file_path=path,
                )
            )

        files.append(file_run)

    return planned, files


def _grade_attempt(item: _PlannedCase, repeat_index: int, options: RunOptions, env: RunEnvironment) -> AttemptResult:
    """Grade one case once and evaluate the result against its expectations."""
    session_id = f"gradetest:{item.case.case_id}#{repeat_index}"
    attempt = AttemptResult(
        case_id=item.case.case_id,
        qtag=item.case.qtag,
        unit_name=item.unit_name,
        file=item.file_path,
        repeat_index=repeat_index,
        session_id=session_id,
        model=item.model,
        description=item.case.description,
        solution=item.case.solution,
        expectations=_expectations(item.case),
        reference_image_count=len(item.question_dict.get("solution_images") or []),
        question_text=str(item.question_dict.get("question_text") or ""),
    )

    try:
        images = load_case_images(item.case, item.file_path)
        grade = item.grader.grade(
            item.question_dict,
            item.case.solution,
            part_label="all",
            unit_name=item.unit_name,
            qtag=item.case.qtag,
            model=item.model,
            api_key=options.api_key,
            timeout=options.timeout,
            solution_images=images or None,
            session_id=session_id,
        )
    except Exception as exc:  # a failed call is a result to report, not a crash
        attempt.error = f"{type(exc).__name__}: {exc}"
        return attempt

    attempt.points = grade.get("points")
    attempt.max_points = grade.get("max_points")
    attempt.result = grade.get("result")
    attempt.feedback = str(grade.get("feedback") or "")
    attempt.full_explanation = str(grade.get("full_explanation") or "")
    attempt.rubric_eval = _plain_rubric_eval(grade)
    attempt.part_scores = part_scores(item.question_dict, grade)
    attempt.failures, attempt.margin = evaluate_attempt(item.case, item.question_dict, grade)

    usage = submission_usage(env.db_path, session_id)
    attempt.tokens_in = usage.get("tokens_in")
    attempt.tokens_out = usage.get("tokens_out")
    attempt.latency_ms = usage.get("latency_ms")
    attempt.timed_out = bool(usage.get("timed_out"))
    if usage.get("model"):
        attempt.model = usage["model"]

    return attempt


def _execute_run(planned, options: RunOptions, env: RunEnvironment, progress) -> None:
    tasks = [
        (item, repeat_index)
        for item in planned
        for repeat_index in range(1, max(1, options.repeat) + 1)
    ]

    def announce(case_run: CaseRun) -> None:
        if progress is not None and len(case_run.attempts) == max(1, options.repeat):
            progress(case_run)

    if options.jobs <= 1 or options.fail_fast:
        for item, repeat_index in tasks:
            attempt = _grade_attempt(item, repeat_index, options, env)
            item.case_run.attempts.append(attempt)
            announce(item.case_run)
            if options.fail_fast and not attempt.passed:
                return
        return

    with ThreadPoolExecutor(max_workers=options.jobs) as pool:
        futures = [pool.submit(_grade_attempt, item, repeat_index, options, env) for item, repeat_index in tasks]
        for (item, _), future in zip(tasks, futures):
            item.case_run.attempts.append(future.result())
            announce(item.case_run)


def run_test_files(paths, options: RunOptions | None = None, *, progress=None) -> RunReport:
    """Grade every case in `paths` and compare the results to its expectations.

    Everything expensive happens here, so everything cheap happens first: the
    files are validated, every case is resolved to a question and a model, and
    the call budget is checked before a single request goes out.
    """
    options = options or RunOptions()
    resolved_paths = expand_paths(list(paths))

    model_override = None
    if options.model:
        from llmgrader.services.models import resolve_preferred_model

        spec = resolve_preferred_model(options.model)
        if spec is None:
            raise GradeTestError(
                f"--model '{options.model}' is not a tier name or a known model id. "
                "Use simple, standard, complex, or an id from the registry."
            )
        model_override = spec.id

    started = time.time()
    env = RunEnvironment(keep_db=options.keep_db)
    pkg_context = None
    try:
        if options.pkg:
            pkg_context = PackageContext(options.pkg, workdir=os.path.join(env.root, "pkg_zip"))

        planned, files = _plan_run(resolved_paths, options, env, pkg_context, model_override)

        report = RunReport(
            files=files,
            storage_path=env.storage,
            dry_run=options.dry_run,
            kept_db=options.keep_db,
        )
        repeat = max(1, options.repeat)
        report.planned_calls = len(planned) * repeat
        breakdown: dict[str, int] = {}
        for item in planned:
            breakdown[item.model] = breakdown.get(item.model, 0) + repeat
        report.planned_by_model = breakdown

        if options.max_calls is not None and report.planned_calls > options.max_calls:
            raise GradeTestError(
                f"this run would make {report.planned_calls} calls, above the --max-calls "
                f"limit of {options.max_calls}. Narrow it with --case/--qtag, lower --repeat, "
                "or raise the limit."
            )

        if not options.dry_run:
            _execute_run(planned, options, env, progress)

        report.elapsed_seconds = time.time() - started

        if options.out and not options.dry_run:
            report.report_path = write_json_report(report, options.out)
        if options.html and not options.dry_run:
            report.html_path = write_html_report(report, options.html)

        return report
    finally:
        env.close()


def write_json_report(report: RunReport, path: str) -> str:
    """Write the full report: nothing summarized away.

    Every field of every attempt, including the complete feedback, the full
    explanation, and the entire ``rubric_eval`` object with its evidence, so
    the instructor can read what the model actually said rather than what the
    terminal had room for.
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, indent=2)
    return path


# ---------------------------------------------------------------------------
# The HTML report
# ---------------------------------------------------------------------------


_HTML_STYLE = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, sans-serif;
       margin: 0 auto; max-width: 60rem; padding: 2rem 1rem 6rem;
       line-height: 1.5; color: #1b1b1b; background: #fbfbfa; }
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.15rem; margin: 0; }
h3 { font-size: 0.95rem; margin: 1.25rem 0 0.35rem; text-transform: uppercase;
     letter-spacing: 0.04em; color: #666; font-weight: 600; }
.sub { color: #666; margin-top: 0; }
.case { border: 1px solid #ddd; border-radius: 6px; margin: 1.5rem 0;
        padding: 1rem 1.25rem 1.25rem; background: #fff; }
.case.failed { border-color: #c0392b; }
.case.warned { border-color: #b8860b; }
.badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px;
         font-size: 0.75rem; font-weight: 700; letter-spacing: 0.05em;
         vertical-align: 0.15em; margin-right: 0.6rem; color: #fff; }
.badge.PASS  { background: #2e7d32; }
.badge.WARN  { background: #b8860b; }
.badge.FAIL  { background: #c0392b; }
.badge.FLAKY { background: #8e44ad; }
.badge.ERROR { background: #444; }
.meta { color: #666; font-size: 0.85rem; margin: 0.35rem 0 0; }
.description { font-style: italic; color: #444; margin: 0.75rem 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; margin: 0.5rem 0; }
th, td { border: 1px solid #ddd; padding: 0.35rem 0.5rem; text-align: left;
         vertical-align: top; }
th { background: #f2f2f0; font-weight: 600; }
tr.bad td { background: #fdecea; }
pre, .solution { white-space: pre-wrap; word-wrap: break-word; background: #f7f7f5;
                 border: 1px solid #e4e4e0; border-radius: 4px; padding: 0.75rem;
                 font-size: 0.88rem; margin: 0.5rem 0; }
.failure { color: #a02622; font-size: 0.9rem; margin: 0.2rem 0; }
.evidence { color: #555; font-size: 0.85rem; margin: 0 0 0.5rem 1.2rem; }
.attempt { border-top: 1px dashed #ddd; margin-top: 1rem; padding-top: 0.75rem; }
.question { background: #f7f9fb; border: 1px solid #e0e6ec; border-radius: 4px;
            padding: 0.75rem; font-size: 0.9rem; }
@media (prefers-color-scheme: dark) {
  body { color: #e8e8e6; background: #17181a; }
  .case { background: #1f2023; border-color: #35363a; }
  .question { background: #1b2026; border-color: #2c333b; }
  th { background: #26272b; }
  th, td { border-color: #35363a; }
  tr.bad td { background: #3a1f1e; }
  pre, .solution { background: #212226; border-color: #35363a; }
  .sub, .meta, h3 { color: #9a9a97; }
  .description { color: #bdbdba; }
  .evidence { color: #a8a8a5; }
}
"""


def _escape(text) -> str:
    return (
        str(text if text is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_markdownish(text: str) -> str:
    """Render the grader's feedback: pipe tables become tables, the rest is text.

    ``append_rubric_feedback`` puts markdown tables in the feedback a student
    sees, so a report that showed the raw pipes would be harder to read than
    the app is.  This is deliberately not a markdown implementation -- it
    handles the one construct the grader actually emits.
    """
    if not text:
        return ""

    html: list[str] = []
    rows: list[list[str]] = []

    def flush_table() -> None:
        if not rows:
            return
        header, body = rows[0], rows[1:]
        # A markdown table's second row is the |---|---| separator.
        if body and all(set(cell) <= set("-: ") for cell in body[0]):
            body = body[1:]
        html.append("<table><thead><tr>")
        html.extend(f"<th>{_escape(cell)}</th>" for cell in header)
        html.append("</tr></thead><tbody>")
        for row in body:
            html.append("<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>")
        html.append("</tbody></table>")
        rows.clear()

    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            html.append("<p>" + _escape("\n".join(paragraph)).replace("\n", "<br>") + "</p>")
            paragraph.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
            continue
        flush_table()
        if not stripped:
            flush_paragraph()
        else:
            paragraph.append(line)

    flush_table()
    flush_paragraph()
    return "".join(html)


def _expectation_rows(attempt: AttemptResult) -> str:
    failed_parts = attempt.failed_part_labels()
    failed_rubrics = attempt.failed_rubric_ids()
    rows: list[str] = []

    if attempt.expectations.get("result") is not None:
        bad = any(failure.startswith("result:") for failure in attempt.failures)
        rows.append(
            f'<tr class="{"bad" if bad else ""}"><td>overall result</td>'
            f'<td>{_escape(attempt.expectations["result"])}</td>'
            f"<td>{_escape(attempt.result)}</td></tr>"
        )

    for band in attempt.expectations.get("points") or []:
        label = band["label"]
        scored = attempt.part_scores.get(label)
        rows.append(
            f'<tr class="{"bad" if label in failed_parts else ""}">'
            f"<td>part <code>{_escape(label)}</code></td>"
            f'<td>{_escape(_band_text(band["min"], band["max"]))}</td>'
            f'<td>{"-" if scored is None else _escape(_num(float(scored)))}</td></tr>'
        )

    for expectation in attempt.expectations.get("rubrics") or []:
        item_id = expectation["id"]
        entry = attempt.rubric_eval.get(item_id) or {}
        if expectation["expect"] is not None:
            expected = expectation["expect"]
            actual = entry.get("result")
        else:
            expected = _band_text(expectation["min"], expectation["max"])
            actual = entry.get("point_awarded")
            actual = None if actual is None else _num(float(actual))
        rows.append(
            f'<tr class="{"bad" if item_id in failed_rubrics else ""}">'
            f"<td>rubric <code>{_escape(item_id)}</code></td>"
            f"<td>{_escape(expected)}</td>"
            f'<td>{"-" if actual is None else _escape(actual)}</td></tr>'
        )

    if not rows:
        return ""
    return (
        "<h3>Expectations</h3><table><thead><tr><th>Claim</th><th>Expected</th>"
        "<th>Actual</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _rubric_rows(attempt: AttemptResult) -> str:
    if not attempt.rubric_eval:
        return ""

    failed_rubrics = attempt.failed_rubric_ids()
    rows = []
    for item_id, entry in attempt.rubric_eval.items():
        if hasattr(entry, "model_dump"):
            entry = entry.model_dump()
        entry = entry if isinstance(entry, dict) else {}
        outcome = entry.get("result")
        if outcome is None and entry.get("point_awarded") is not None:
            outcome = _num(float(entry["point_awarded"]))
        rows.append(
            f'<tr class="{"bad" if item_id in failed_rubrics else ""}">'
            f"<td><code>{_escape(item_id)}</code></td>"
            f"<td>{_escape(outcome)}</td>"
            f'<td>{_escape(entry.get("evidence"))}</td></tr>'
        )

    return (
        "<h3>Rubric evidence</h3><table><thead><tr><th>Item</th><th>Outcome</th>"
        "<th>Evidence the grader cited</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _attempt_html(attempt: AttemptResult, *, show_index: bool) -> str:
    parts: list[str] = ['<div class="attempt">']
    heading = f"Attempt {attempt.repeat_index}" if show_index else "Result"
    score = ""
    if attempt.points is not None:
        score = f" &mdash; {_num(float(attempt.points))}"
        if attempt.max_points is not None:
            score += f" / {_num(float(attempt.max_points))}"
    elif attempt.result:
        score = f" &mdash; {_escape(attempt.result)}"
    parts.append(f"<h3>{heading}{score}</h3>")

    if attempt.error is not None:
        parts.append(f'<p class="failure">{_escape(attempt.error)}</p>')
        parts.append("</div>")
        return "".join(parts)

    for failure, evidence in attempt.failure_lines():
        parts.append(f'<p class="failure">{_escape(failure)}</p>')
        if evidence:
            parts.append(f'<p class="evidence">evidence: {_escape(evidence)}</p>')

    parts.append(_expectation_rows(attempt))
    parts.append("<h3>Feedback the student would see</h3>")
    parts.append(_render_markdownish(attempt.feedback) or "<p>(none)</p>")
    if attempt.full_explanation:
        parts.append("<h3>Full explanation</h3>")
        parts.append(_render_markdownish(attempt.full_explanation))
    parts.append(_rubric_rows(attempt))
    parts.append(
        f'<p class="meta">{attempt.model} &middot; '
        f"{attempt.tokens_in or 0:,} in / {attempt.tokens_out or 0:,} out &middot; "
        f'{(attempt.latency_ms or 0) / 1000:.1f} s{" &middot; timed out" if attempt.timed_out else ""}</p>'
    )
    parts.append("</div>")
    return "".join(parts)


def _case_html(case: CaseRun, question_text: str) -> str:
    css_class = "case"
    if case.verdict in FAILING_VERDICTS:
        css_class += " failed"
    elif case.verdict == VERDICT_WARN:
        css_class += " warned"

    parts = [f'<div class="{css_class}" id="case-{_escape(case.case_id)}">']
    parts.append(
        f'<h2><span class="badge {case.verdict}">{case.verdict}</span>'
        f"<code>{_escape(case.case_id)}</code></h2>"
    )
    parts.append(
        f'<p class="meta">{_escape(case.qtag)} &middot; '
        f'{"partial credit" if case.partial_credit else "binary"} &middot; {_escape(case.model)}'
        + (f" &middot; {case.pass_count}/{len(case.attempts)} attempts passed"
           if len(case.attempts) > 1 else "")
        + "</p>"
    )
    if case.description.strip():
        parts.append(f'<p class="description">{_escape(" ".join(case.description.split()))}</p>')

    if question_text:
        parts.append("<h3>Question</h3>")
        # The question is the instructor's own authored HTML.
        parts.append(f'<div class="question">{question_text}</div>')

    if case.attempts:
        parts.append("<h3>Submitted solution</h3>")
        parts.append(f'<div class="solution">{_escape(case.attempts[0].solution)}</div>')

    for attempt in case.attempts:
        parts.append(_attempt_html(attempt, show_index=len(case.attempts) > 1))

    parts.append("</div>")
    return "".join(parts)


def write_html_report(report: RunReport, path: str) -> str:
    """Write the readable report: the artifact for "why did it grade that way".

    Self-contained, no external assets, so it opens from a file:// URL with no
    network.  LaTeX in a question renders as source rather than as maths --
    typesetting it would need MathJax, and pulling that in would break the
    self-contained property for the sake of the least important part of the
    page.
    """
    verdicts = report.verdicts
    summary = (
        f'{verdicts.get(VERDICT_PASS, 0)} passed, {verdicts.get(VERDICT_FAIL, 0)} failed'
        + (f", {verdicts[VERDICT_FLAKY]} flaky" if verdicts.get(VERDICT_FLAKY) else "")
        + (f", {verdicts[VERDICT_ERROR]} errored" if verdicts.get(VERDICT_ERROR) else "")
        + (f", {verdicts[VERDICT_WARN]} warning" if verdicts.get(VERDICT_WARN) else "")
    )

    body: list[str] = [
        "<h1>Grading test report</h1>",
        f'<p class="sub">{_escape(summary)} &middot; {report.calls} calls &middot; '
        f"{report.tokens_in:,} tokens in / {report.tokens_out:,} out &middot; "
        f"{report.elapsed_seconds:.1f} s &middot; "
        f'{_escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))}</p>',
    ]

    for file_run in report.files:
        body.append(
            f'<h2 style="margin-top:2rem">{_escape(file_run.path)}</h2>'
            f'<p class="meta">unit: {_escape(file_run.unit_file)} '
            f"({_escape(file_run.unit_label)}) &middot; {len(file_run.cases)} cases</p>"
        )
        for case in file_run.cases:
            question_text = case.attempts[0].question_text if case.attempts else ""
            body.append(_case_html(case, question_text))

    document = (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Grading test report</title><style>"
        + _HTML_STYLE
        + "</style></head><body>"
        + "".join(body)
        + "</body></html>\n"
    )

    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(document)
    return path
