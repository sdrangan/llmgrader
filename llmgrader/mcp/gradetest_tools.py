from __future__ import annotations

import os
import tempfile

from llmgrader.mcp.description_utils import (
    make_attribute_description,
    make_element_description,
    make_text_content_description,
)
from llmgrader.services import gradetests


def get_unit_test_structure() -> dict:
    """Return a JSON-serializable schema description of a <unit_test> file.

    Grading tests let an instructor pin the behaviour of a rubric: each case is
    a trial answer plus the score it should receive.  Re-running the suite after
    a rubric edit or a model change shows whether the course still grades the
    way the author intended.
    """
    return {
        "summary": (
            "A <unit_test> file holds instructor-authored grading tests for one unit. "
            "Each <case> is a trial student answer for a specific question, together "
            "with the outcome the grader should produce for it."
        ),
        "authoring_workflow": [
            "Write the unit XML first; a test file always refers to an existing question by qtag.",
            "Add one <case> per behaviour worth pinning: a full-credit answer, a "
            "partially correct one, a common misconception, and an answer using a "
            "valid alternative method.",
            "Run `llmgrader_test check <file>` to cross-check the cases against the "
            "unit. This is free and makes no model calls.",
            "Run `llmgrader_test run <file>` to grade the cases for real. This calls "
            "the model and costs money; `--dry-run` prints the call count first.",
        ],
        "structure": {"unit_test": _unit_test_structure()},
        "semantic_rules": [
            "Every <case> needs a unique id and a qtag naming a question in the unit.",
            "Which assertion elements a case may carry depends on the question's "
            "<partial_credit> mode, which lives in the unit file, not here.",
            "Partial-credit questions use <expected_points> with per-part min/max bands.",
            "Binary questions use <expected_result> with pass, fail, or partial.",
            "<expected_result>error</expected_result> asserts that grading itself "
            "failed; it is not a way to express a low score.",
            "Rubric expectations use min/max in partial-credit mode and expect in "
            "binary mode. The schema permits both spellings; `llmgrader_test check` "
            "rejects the wrong pairing for the question's mode.",
            "Bands should be wide enough to tolerate normal model variation. A band "
            "pinned to a single value will be flaky.",
        ],
        "examples": {
            "partial_credit_case": (
                '<unit_test unit="../calculus.xml">\n'
                '  <case id="beam_full_credit" qtag="Beam reaction">\n'
                "    <description>Correct moment balance, correct final expression.</description>\n"
                "    <solution><![CDATA[\n"
                "    Taking moments about the right support: R_L*L = W*L/2 + P*(L-a),\n"
                "    so R_L = W/2 + P(L-a)/L.\n"
                "    ]]></solution>\n"
                "    <expected_points>\n"
                '      <part label="all" min="9" max="10"/>\n'
                "    </expected_points>\n"
                "    <expected_rubrics>\n"
                '      <item id="moment_balance" min="5" max="5"/>\n'
                '      <item id="ignores_weight" min="0" max="0"/>\n'
                "    </expected_rubrics>\n"
                "  </case>\n"
                "</unit_test>"
            ),
            "binary_case": (
                '<unit_test unit="../calculus.xml">\n'
                '  <case id="exp_derivative_alt_method" qtag="Exponential derivative">\n'
                "    <description>Valid alternative method: rewrite as e^(x ln a).</description>\n"
                "    <solution><![CDATA[\n"
                "    y = a^x = e^{x ln a}, so y' = e^{x ln a} * ln(a) = a^x ln(a).\n"
                "    ]]></solution>\n"
                "    <expected_result>pass</expected_result>\n"
                "    <expected_rubrics>\n"
                '      <item id="exponential_form" expect="pass"/>\n'
                '      <item id="taking_logarithm" expect="n/a"/>\n'
                "    </expected_rubrics>\n"
                "  </case>\n"
                "</unit_test>"
            ),
        },
    }


def validate_unit_test_xml(*, unit_test_xml: str, unit_path: str | None = None) -> dict:
    """Schema-validate a <unit_test> document, and cross-check it when possible.

    Schema validation alone is weak here on purpose: ``unit_test.xsd`` cannot see
    the unit file, so it cannot tell whether a case uses the assertion elements
    its question's grading mode allows.  When ``unit_path`` points at the unit
    under test, this runs the same cross-file checks as ``llmgrader_test check``.
    """
    errors: list[str] = []
    warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        test_path = os.path.join(tmp, "unit_test.xml")
        with open(test_path, "w", encoding="utf-8") as handle:
            handle.write(unit_test_xml)

        schema_findings = gradetests.validate_test_file(test_path)
        errors.extend(_finding_text(finding, test_path) for finding in schema_findings)
        if errors:
            return {"valid": False, "errors": errors, "warnings": warnings, "checked_against_unit": False}

        if not unit_path:
            warnings.append(
                "No unit_path supplied, so only the schema was checked. Assertion "
                "elements were not verified against the question's partial_credit mode."
            )
            return {"valid": True, "errors": errors, "warnings": warnings, "checked_against_unit": False}

        if not os.path.exists(unit_path):
            warnings.append(f"Unit file not found, skipped cross-checks: {unit_path}")
            return {"valid": True, "errors": errors, "warnings": warnings, "checked_against_unit": False}

        try:
            test_file = gradetests.load_test_file(test_path)
            unit_data = gradetests.load_unit(unit_path)
            findings = gradetests.check_file(test_file, unit_data)
        except gradetests.GradeTestError as exc:
            return {
                "valid": False,
                "errors": [str(exc)],
                "warnings": warnings,
                "checked_against_unit": False,
            }

    for finding in findings:
        text = _finding_text(finding)
        if finding.is_error:
            errors.append(text)
        else:
            warnings.append(text)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_against_unit": True,
    }


def _finding_text(finding: gradetests.CheckFinding, test_path: str | None = None) -> str:
    """Render a finding without leaking the scratch path the caller never sees.

    Schema findings arrive with the file path already baked into ``message``,
    so it has to be stripped there as well as skipped here.
    """
    message = finding.message
    if test_path:
        message = message.replace(f"{test_path}: ", "").replace(test_path, "<unit_test>")
    if finding.line is not None and not message.startswith("line "):
        return f"line {finding.line}: {message}"
    return message


def _unit_test_structure() -> dict:
    return make_element_description(
        "Root element holding the grading tests for one unit.",
        required=True,
        multiple=False,
        attributes={
            "unit": make_attribute_description(
                "Path to the unit XML under test, relative to this file. Optional "
                "because the CLI can be pointed at a unit or a package instead.",
                required=False,
                type="path",
                example="../calculus.xml",
            ),
        },
        children={"case": _case_structure()},
    )


def _case_structure() -> dict:
    return make_element_description(
        "One trial answer and the outcome it should receive.",
        required=False,
        multiple=True,
        attributes={
            "id": make_attribute_description(
                "Unique identifier for this case within the file.",
                required=True,
                type="string",
                example="beam_full_credit",
            ),
            "qtag": make_attribute_description(
                "qtag of the question in the unit that this case answers.",
                required=True,
                type="string",
                example="Beam reaction",
            ),
        },
        children={
            "description": make_element_description(
                "What this case is pinning, in the author's words.",
                required=True,
                multiple=False,
                text_content=make_text_content_description(
                    "Short description of the behaviour under test.",
                    required=True,
                    type="string",
                    example="Correct setup, algebra slip in the final step.",
                ),
            ),
            "solution": make_element_description(
                "The trial student answer, as the grader will see it. Use CDATA for "
                "answers containing markup or LaTeX.",
                required=True,
                multiple=False,
                text_content=make_text_content_description(
                    "Student answer text.",
                    required=True,
                    type="string",
                    example="R_L = W/2 + P(L-a)/L",
                ),
            ),
            "images": _images_structure(),
            "expected_points": _expected_points_structure(),
            "expected_result": _expected_result_structure(),
            "expected_rubrics": _expected_rubrics_structure(),
        },
    )


def _images_structure() -> dict:
    return make_element_description(
        "Optional images attached to the trial answer, for questions that expect "
        "a hand-drawn or plotted response.",
        required=False,
        multiple=False,
        children={
            "image": make_element_description(
                "One image path relative to the test file.",
                required=True,
                multiple=True,
                text_content=make_text_content_description(
                    "Image path.",
                    required=True,
                    type="path",
                    example="images/beam_sketch.png",
                ),
            ),
        },
    )


def _expected_points_structure() -> dict:
    return make_element_description(
        "Per-part score bands. Use for partial-credit questions.",
        required=False,
        multiple=False,
        children={
            "part": make_element_description(
                "Score band for one part.",
                required=True,
                multiple=True,
                attributes={
                    "label": make_attribute_description(
                        "Part label from the question's <parts> block.",
                        required=True,
                        type="string",
                        example="all",
                    ),
                    "min": make_attribute_description(
                        "Lowest acceptable score. Omit to leave the low side unbounded.",
                        required=False,
                        type="number",
                        example="9",
                    ),
                    "max": make_attribute_description(
                        "Highest acceptable score. Omit to leave the high side unbounded.",
                        required=False,
                        type="number",
                        example="10",
                    ),
                },
            ),
        },
    )


def _expected_result_structure() -> dict:
    return make_element_description(
        "Overall pass/fail outcome. Use for binary-credit questions.",
        required=False,
        multiple=False,
        text_content=make_text_content_description(
            "Expected result. 'partial' is reachable only on a multi-part binary "
            "question. 'error' asserts that grading itself failed, and is not a way "
            "to express a low score.",
            required=True,
            type="string",
            example="pass",
            allowed_values=["pass", "fail", "partial", "error"],
        ),
    )


def _expected_rubrics_structure() -> dict:
    return make_element_description(
        "Expectations on individual rubric items.",
        required=False,
        multiple=False,
        children={
            "item": make_element_description(
                "Expectation for one rubric item.",
                required=True,
                multiple=True,
                attributes={
                    "id": make_attribute_description(
                        "Rubric item id from the question's <rubrics> block.",
                        required=True,
                        type="string",
                        example="moment_balance",
                    ),
                    "expect": make_attribute_description(
                        "Expected per-item result. Binary-credit questions only.",
                        required=False,
                        type="string",
                        example="pass",
                        allowed_values=["pass", "fail", "feedback", "n/a"],
                    ),
                    "min": make_attribute_description(
                        "Lowest acceptable point_awarded. Partial-credit questions only.",
                        required=False,
                        type="number",
                        example="5",
                    ),
                    "max": make_attribute_description(
                        "Highest acceptable point_awarded. Partial-credit questions only.",
                        required=False,
                        type="number",
                        example="5",
                    ),
                },
            ),
        },
    )
