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

import glob as _glob
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from dataclasses import dataclass, field
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
