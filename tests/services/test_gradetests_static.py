"""Static checking of instructor-authored grading tests -- the free CI gate.

Two kinds of test here:

* the worked example under ``example_repo/`` checks clean, so a renamed qtag
  or a retired rubric id in the demo course becomes a CI failure;
* deliberately broken files, built in ``tmp_path``, each produce the specific
  finding they are supposed to.  They are built rather than committed because
  a committed broken fixture is one someone eventually "fixes".

Nothing here makes an API call or constructs a Grader.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from textwrap import dedent

import pytest

from llmgrader.scripts.llmgrader_test import main as llmgrader_test_main
from llmgrader.services.gradetests import (
    LEVEL_ERROR,
    LEVEL_WARNING,
    GradeTestError,
    check_file,
    check_path,
    expand_paths,
    load_test_file,
    load_unit,
    validate_test_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_UNIT = REPO_ROOT / "example_repo" / "unit1" / "calculus.xml"
EXAMPLE_TESTS = REPO_ROOT / "example_repo" / "unit1" / "tests" / "calculus_tests.xml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_test_file(tmp_path: Path, cases: str, *, unit: str | None = None, name: str = "cases.xml") -> Path:
    """Write a <unit_test> around `cases`, targeting the example unit."""
    unit_attr = f' unit="{unit}"' if unit else f' unit="{EXAMPLE_UNIT.as_posix()}"'
    path = tmp_path / name
    path.write_text(f"<unit_test{unit_attr}>\n{dedent(cases)}\n</unit_test>\n", encoding="utf-8")
    return path


def _messages(findings, level=None) -> list[str]:
    return [f.message for f in findings if level is None or f.level == level]


def _one(findings, needle: str, level: str = LEVEL_ERROR):
    """The single finding at `level` whose message contains `needle`."""
    matches = [f for f in findings if f.level == level and needle in f.message]
    assert matches, f"no {level} containing {needle!r}; got {_messages(findings)}"
    assert len(matches) == 1, f"expected one {level} containing {needle!r}, got {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# The worked example
# ---------------------------------------------------------------------------


def test_example_test_file_validates_against_the_schema() -> None:
    assert validate_test_file(str(EXAMPLE_TESTS)) == []


def test_example_test_file_checks_clean() -> None:
    """The shipped example must pass with no errors and no warnings.

    Warnings included: an example that ships with an uncovered rubric item is
    an example that teaches instructors to ignore the coverage report.
    """
    result = check_path(str(EXAMPLE_TESTS))

    assert result.errors == [], _messages(result.findings, LEVEL_ERROR)
    assert result.warnings == [], _messages(result.findings, LEVEL_WARNING)
    assert result.case_count == 8


def test_example_test_file_covers_both_grading_modes() -> None:
    """The fixture is only useful if it exercises binary and partial credit."""
    test_file = load_test_file(str(EXAMPLE_TESTS))
    unit = load_unit(str(EXAMPLE_UNIT))

    modes = {unit.questions[case.qtag].partial_credit for case in test_file.cases}
    assert modes == {True, False}

    binary = [case for case in test_file.cases if not unit.questions[case.qtag].partial_credit]
    partial = [case for case in test_file.cases if unit.questions[case.qtag].partial_credit]

    assert any(case.expected_result == "pass" for case in binary)
    assert any(case.expected_result == "fail" for case in binary)
    # A positive item pinned at full value, and an item pinned at zero.
    bands = [
        (expectation.item_id, expectation.min, expectation.max)
        for case in partial
        for expectation in case.expected_rubrics
    ]
    assert ("correct_u_dv", 3.0, 3.0) in bands
    assert ("apply_limits", 0.0, 0.0) in bands


def test_unit_attribute_resolves_relative_to_the_test_file() -> None:
    test_file = load_test_file(str(EXAMPLE_TESTS))
    assert Path(test_file.unit_path) == EXAMPLE_UNIT


def test_grading_mode_comes_from_the_unit_parser() -> None:
    """`partial_credit` is an xs:string; the parser is what normalizes it."""
    unit = load_unit(str(EXAMPLE_UNIT))
    assert unit.questions["Exponential derivative"].partial_credit is False
    assert unit.questions["Integration by parts"].partial_credit is True
    assert unit.questions["Exponential graphing"].partial_credit is True


def test_one_of_groups_are_read_from_the_unit() -> None:
    unit = load_unit(str(EXAMPLE_UNIT))
    groups = unit.questions["Exponential derivative"].rubric_groups
    assert groups == [{"type": "one_of", "ids": ["taking_logarithm", "exponential_form"]}]


# ---------------------------------------------------------------------------
# Broken files: one finding each
# ---------------------------------------------------------------------------


def test_unknown_qtag_is_reported_with_the_case_and_the_unit(tmp_path: Path) -> None:
    """Renaming a question orphans its tests, and nothing else notices."""
    path = _write_test_file(
        tmp_path,
        """
        <case id="orphan" qtag="Exponential derivitive">
          <description>Typo in the qtag.</description>
          <solution>y' = a^x ln a</solution>
          <expected_result>pass</expected_result>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, "Exponential derivitive")
    assert "case `orphan`" in finding.message
    assert "calculus.xml" in finding.message
    assert finding.line is not None


def test_unknown_part_label_is_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="bad_part" qtag="Exponential graphing">
          <description>Part label c does not exist.</description>
          <solution>Critical point at x = 1.</solution>
          <expected_points>
            <part label="c" min="1" max="3"/>
          </expected_points>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, 'label="c"')
    assert "Exponential graphing" in finding.message
    assert "a, b" in finding.message


def test_band_above_the_part_total_is_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="over_total" qtag="Integration by parts">
          <description>The part is worth 10, so a max of 12 can never be met.</description>
          <solution>u = x, dv = e^{2x} dx.</solution>
          <expected_points>
            <part label="all" min="4" max="12"/>
          </expected_points>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, "above the part total")
    assert "case `over_total`" in finding.message
    assert finding.line is not None


def test_band_on_a_binary_question_is_reported_with_the_mode(tmp_path: Path) -> None:
    """The pairing check: the XSD cannot see the question's grading mode."""
    path = _write_test_file(
        tmp_path,
        """
        <case id="wrong_form" qtag="Exponential derivative">
          <description>Binary question banded as if it allowed partial credit.</description>
          <solution>y' = a^x ln a</solution>
          <expected_points>
            <part label="all" min="8" max="10"/>
          </expected_points>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, "<expected_points>")
    assert "binary" in finding.message
    assert "Exponential derivative" in finding.message
    assert "<expected_result>" in finding.message


def test_expected_result_on_a_partial_credit_question_is_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="wrong_form" qtag="Integration by parts">
          <description>Partial-credit question asserted as pass/fail.</description>
          <solution>u = x, dv = e^{2x} dx.</solution>
          <expected_result>pass</expected_result>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, "<expected_result>")
    assert "partial-credit" in finding.message
    assert "<expected_points>" in finding.message


def test_expect_on_a_partial_credit_rubric_item_is_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="wrong_item_form" qtag="Integration by parts">
          <description>Rubric item asserted with expect on a partial-credit question.</description>
          <solution>u = x, dv = e^{2x} dx.</solution>
          <expected_points>
            <part label="all" min="1" max="9"/>
          </expected_points>
          <expected_rubrics>
            <item id="correct_u_dv" expect="pass"/>
          </expected_rubrics>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, 'expect="pass"')
    assert "point_awarded" in finding.message
    assert "min/max" in finding.message


def test_band_on_a_binary_rubric_item_is_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="banded_item" qtag="Exponential derivative">
          <description>Rubric item banded on a binary question.</description>
          <solution>y' = a^x ln a</solution>
          <expected_result>pass</expected_result>
          <expected_rubrics>
            <item id="final_answer" min="1" max="1"/>
          </expected_rubrics>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, "min/max band")
    assert "use expect" in finding.message


def test_unknown_rubric_id_is_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="stale_rubric" qtag="Exponential derivative">
          <description>Rubric id was renamed in the unit.</description>
          <solution>y' = a^x ln a</solution>
          <expected_result>pass</expected_result>
          <expected_rubrics>
            <item id="polynomial_confusions" expect="n/a"/>
          </expected_rubrics>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, "polynomial_confusions")
    assert "does not exist" in finding.message
    assert "final_answer" in finding.message  # lists what the question does have


def test_empty_description_and_solution_are_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="hollow" qtag="Exponential derivative">
          <description>   </description>
          <solution></solution>
          <expected_result>fail</expected_result>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    _one(result.findings, "<description> is empty")
    _one(result.findings, "<solution> is empty")


def test_duplicate_case_ids_are_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="twice" qtag="Exponential derivative">
          <description>First.</description>
          <solution>y' = a^x ln a</solution>
          <expected_result>pass</expected_result>
        </case>
        <case id="twice" qtag="Exponential derivative">
          <description>Second, same id.</description>
          <solution>y' = x a^{x-1}</solution>
          <expected_result>fail</expected_result>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, "duplicate case id")
    assert "first defined on line" in finding.message


def test_min_above_max_is_reported(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="inverted" qtag="Integration by parts">
          <description>Band written backwards.</description>
          <solution>u = x, dv = e^{2x} dx.</solution>
          <expected_points>
            <part label="all" min="8" max="4"/>
          </expected_points>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    _one(result.findings, "above max")


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def test_full_range_band_is_a_warning(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="asserts_nothing" qtag="Integration by parts">
          <description>A band spanning the whole question asserts nothing.</description>
          <solution>u = x, dv = e^{2x} dx.</solution>
          <expected_points>
            <part label="all" min="0" max="10"/>
          </expected_points>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    assert result.errors == []
    _one(result.findings, "asserts nothing", level=LEVEL_WARNING)


def test_expect_feedback_is_a_warning_not_an_error(tmp_path: Path) -> None:
    """`feedback` is a real outcome, so it validates -- but it is unstable."""
    path = _write_test_file(
        tmp_path,
        """
        <case id="tone" qtag="Exponential derivative">
          <description>Pins a rubric item to the feedback verdict.</description>
          <solution>y' = a^x ln a</solution>
          <expected_result>pass</expected_result>
          <expected_rubrics>
            <item id="taking_logarithm" expect="feedback"/>
          </expected_rubrics>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    assert result.errors == []
    finding = _one(result.findings, 'expect="feedback"', level=LEVEL_WARNING)
    assert "unstable" in finding.message


def test_uncovered_rubric_item_is_reported_by_coverage(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="only_setup" qtag="Integration by parts">
          <description>Asserts on one item only.</description>
          <solution>u = x, dv = e^{2x} dx.</solution>
          <expected_rubrics>
            <item id="correct_u_dv" min="3" max="3"/>
          </expected_rubrics>
        </case>
        """,
    )
    result = check_path(str(path), coverage=True)

    warnings = _messages(result.findings, LEVEL_WARNING)
    assert any("apply_limits" in message and "not asserted on" in message for message in warnings)
    # Questions with no cases at all are reported too.
    assert any("has no test cases" in message for message in warnings)


def test_one_of_group_coverage_is_reported_per_branch(tmp_path: Path) -> None:
    """A correct solution satisfies one branch, so per-item coverage is wrong."""
    path = _write_test_file(
        tmp_path,
        """
        <case id="log_only" qtag="Exponential derivative">
          <description>Covers only the logarithm branch of the one_of group.</description>
          <solution>ln y = x ln a, so y' = a^x ln a.</solution>
          <expected_result>pass</expected_result>
          <expected_rubrics>
            <item id="taking_logarithm" expect="pass"/>
            <item id="final_answer" expect="pass"/>
            <item id="polynomial_confusion" expect="n/a"/>
          </expected_rubrics>
        </case>
        """,
    )
    result = check_path(str(path), coverage=True)

    warnings = _messages(result.findings, LEVEL_WARNING)
    group_warnings = [message for message in warnings if "one_of group" in message]
    assert len(group_warnings) == 1
    assert "exponential_form" in group_warnings[0]
    # The covered branch is not also reported as an uncovered plain item.
    assert not any("taking_logarithm" in message and "not asserted on" in message for message in warnings)


def test_case_with_no_assertions_is_a_warning(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="claims_nothing" qtag="Exponential derivative">
          <description>Grades, but asserts nothing about the outcome.</description>
          <solution>y' = a^x ln a</solution>
        </case>
        """,
    )
    result = check_path(str(path), coverage=False)

    assert result.errors == []
    _one(result.findings, "claims nothing", level=LEVEL_WARNING)


# ---------------------------------------------------------------------------
# Negative rubric items -- the shape a band takes when an item must not fire
# ---------------------------------------------------------------------------


NEGATIVE_UNIT = """\
<unit id="neg" title="Negative item unit" version="1.0">
  <question qtag="Sign error question">
    <question_text><![CDATA[Integrate.]]></question_text>
    <solution><![CDATA[The answer is 4.]]></solution>
    <partial_credit>true</partial_credit>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>10</points>
      </part>
    </parts>
    <rubrics>
      <item id="correct_setup" point_adjustment="+4">
        <display_text>Correct setup</display_text>
        <condition>Student sets the integral up correctly.</condition>
      </item>
      <item id="sign_error_penalty" point_adjustment="-2">
        <display_text>Sign error</display_text>
        <condition>Student flips the sign of the antiderivative.</condition>
      </item>
    </rubrics>
    <rubric_total>flexible</rubric_total>
  </question>
</unit>
"""


@pytest.fixture
def negative_unit(tmp_path: Path) -> Path:
    path = tmp_path / "negative_unit.xml"
    path.write_text(NEGATIVE_UNIT, encoding="utf-8")
    return path


def test_negative_item_bands_are_accepted_both_ways(negative_unit: Path, tmp_path: Path) -> None:
    """`min=-2 max=-2` asserts the penalty fired; `0/0` asserts it did not."""
    path = _write_test_file(
        tmp_path,
        """
        <case id="penalty_fires" qtag="Sign error question">
          <description>Sign flipped, so the penalty must apply.</description>
          <solution>The answer is -4.</solution>
          <expected_rubrics>
            <item id="correct_setup" min="4" max="4"/>
            <item id="sign_error_penalty" min="-2" max="-2"/>
          </expected_rubrics>
        </case>
        <case id="penalty_quiet" qtag="Sign error question">
          <description>Correct signs, so the penalty must not apply.</description>
          <solution>The answer is 4.</solution>
          <expected_rubrics>
            <item id="correct_setup" min="4" max="4"/>
            <item id="sign_error_penalty" min="0" max="0"/>
          </expected_rubrics>
        </case>
        """,
        unit=negative_unit.as_posix(),
        name="negative_cases.xml",
    )
    result = check_path(str(path), coverage=True)

    assert result.findings == [], _messages(result.findings)


def test_positive_band_on_a_negative_item_can_never_pass(negative_unit: Path, tmp_path: Path) -> None:
    """A -2 item is awarded -2 or 0; a band of [1,2] is unsatisfiable."""
    path = _write_test_file(
        tmp_path,
        """
        <case id="backwards" qtag="Sign error question">
          <description>Reads the negative item as if firing awarded points.</description>
          <solution>The answer is -4.</solution>
          <expected_rubrics>
            <item id="sign_error_penalty" min="1" max="2"/>
          </expected_rubrics>
        </case>
        """,
        unit=negative_unit.as_posix(),
        name="backwards.xml",
    )
    result = check_path(str(path), coverage=False)

    finding = _one(result.findings, "sign_error_penalty")
    assert "point_adjustment=-2" in finding.message
    assert "can never be satisfied" in finding.message


def test_band_above_a_positive_items_adjustment_can_never_pass(negative_unit: Path, tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="too_high" qtag="Sign error question">
          <description>Asks for 5 points from a 4 point item.</description>
          <solution>The answer is 4.</solution>
          <expected_rubrics>
            <item id="correct_setup" min="5"/>
          </expected_rubrics>
        </case>
        """,
        unit=negative_unit.as_posix(),
        name="too_high.xml",
    )
    result = check_path(str(path), coverage=False)

    _one(result.findings, "correct_setup")


# ---------------------------------------------------------------------------
# Schema-level rejection
# ---------------------------------------------------------------------------


def test_misspelled_element_is_a_schema_error(tmp_path: Path) -> None:
    """Without the XSD a typo would be silently ignored, asserting nothing."""
    path = _write_test_file(
        tmp_path,
        """
        <case id="typo" qtag="Exponential derivative">
          <description>Element name is wrong.</description>
          <solution>y' = a^x ln a</solution>
          <expected_results>pass</expected_results>
        </case>
        """,
    )
    findings = validate_test_file(str(path))

    assert findings
    assert all(finding.level == LEVEL_ERROR for finding in findings)


def test_unknown_expect_value_is_a_schema_error(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="bad_expect" qtag="Exponential derivative">
          <description>expect must be pass, fail, feedback or n/a.</description>
          <solution>y' = a^x ln a</solution>
          <expected_result>pass</expected_result>
          <expected_rubrics>
            <item id="final_answer" expect="triggered"/>
          </expected_rubrics>
        </case>
        """,
    )
    assert validate_test_file(str(path))


def test_missing_description_is_a_schema_error(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="no_description" qtag="Exponential derivative">
          <solution>y' = a^x ln a</solution>
          <expected_result>pass</expected_result>
        </case>
        """,
    )
    assert validate_test_file(str(path))


def test_unparseable_file_raises_rather_than_reporting_findings(tmp_path: Path) -> None:
    path = tmp_path / "broken.xml"
    path.write_text("<unit_test><case id='x'></unit_test>", encoding="utf-8")

    with pytest.raises(GradeTestError, match="failed to parse XML"):
        validate_test_file(str(path))


def test_missing_unit_attribute_and_no_override_raises(tmp_path: Path) -> None:
    path = tmp_path / "no_unit.xml"
    path.write_text("<unit_test>\n</unit_test>\n", encoding="utf-8")

    with pytest.raises(GradeTestError, match="no unit to check against"):
        check_path(str(path))


# ---------------------------------------------------------------------------
# check_file works on an already-loaded pair, which is what pytest suites use
# ---------------------------------------------------------------------------


def test_check_file_accepts_a_loaded_test_file_and_unit() -> None:
    test_file = load_test_file(str(EXAMPLE_TESTS))
    unit = load_unit(str(EXAMPLE_UNIT))

    assert check_file(test_file, unit) == []


# ---------------------------------------------------------------------------
# The console script
# ---------------------------------------------------------------------------


def test_cli_check_exits_zero_on_the_example(capsys) -> None:
    exit_code = llmgrader_test_main(["check", str(EXAMPLE_TESTS)])

    assert exit_code == 0
    assert "0 errors, 0 warnings" in capsys.readouterr().out


def test_cli_check_exits_one_and_names_the_question_on_a_bad_qtag(tmp_path: Path, capsys) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="orphan" qtag="Exponential derivitive">
          <description>Typo in the qtag.</description>
          <solution>y' = a^x ln a</solution>
          <expected_result>pass</expected_result>
        </case>
        """,
    )
    exit_code = llmgrader_test_main(["check", str(path)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Exponential derivitive" in out
    assert "ERROR" in out


def test_cli_check_strict_promotes_warnings(tmp_path: Path) -> None:
    path = _write_test_file(
        tmp_path,
        """
        <case id="asserts_nothing" qtag="Integration by parts">
          <description>A band spanning the whole question asserts nothing.</description>
          <solution>u = x, dv = e^{2x} dx.</solution>
          <expected_points>
            <part label="all" min="0" max="10"/>
          </expected_points>
        </case>
        """,
    )

    assert llmgrader_test_main(["check", str(path), "--no-coverage"]) == 0
    assert llmgrader_test_main(["check", str(path), "--no-coverage", "--strict"]) == 1


def test_cli_check_missing_file_exits_two(tmp_path: Path, capsys) -> None:
    exit_code = llmgrader_test_main(["check", str(tmp_path / "nope.xml")])

    assert exit_code == 2
    assert "does not exist" in capsys.readouterr().err


def test_cli_check_selector_matching_nothing_exits_two(capsys) -> None:
    exit_code = llmgrader_test_main(["check", str(EXAMPLE_TESTS), "--case", "no_such_case"])

    assert exit_code == 2
    assert "no cases matched" in capsys.readouterr().err


def test_cli_check_case_selector_narrows_the_run(capsys) -> None:
    exit_code = llmgrader_test_main(["check", str(EXAMPLE_TESTS), "--case", "missing_limits"])

    assert exit_code == 0
    assert "1 case," in capsys.readouterr().out


def test_cli_check_verbose_lists_each_case(capsys) -> None:
    llmgrader_test_main(["check", str(EXAMPLE_TESTS), "-v"])

    out = capsys.readouterr().out
    assert "power_rule_confusion" in out
    assert "binary" in out
    assert "partial" in out


def test_cli_check_quiet_prints_only_the_summary(capsys) -> None:
    llmgrader_test_main(["check", str(EXAMPLE_TESTS), "-q"])

    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["8 cases, 0 errors, 0 warnings"]


def test_glob_expansion_finds_the_example() -> None:
    pattern = str(REPO_ROOT / "example_repo" / "unit1" / "tests" / "*.xml")
    assert expand_paths([pattern]) == [str(EXAMPLE_TESTS)]


def test_glob_matching_nothing_raises(tmp_path: Path) -> None:
    with pytest.raises(GradeTestError, match="no files match"):
        expand_paths([str(tmp_path / "*.xml")])


# ---------------------------------------------------------------------------
# Checking against a built package rather than the loose unit file
# ---------------------------------------------------------------------------


PKG_CONFIG = """\
<llmgrader>
  <course><name>Demo</name><semester>Spring 2026</semester></course>
  <units>
    <unit>
      <name>Unit 1</name>
      <source>unit1/calculus.xml</source>
      <destination>unit1_calculus.xml</destination>
    </unit>
  </units>
</llmgrader>
"""


def _built_package(tmp_path: Path, unit_xml: str) -> Path:
    """A package as create_soln_pkg builds one: renamed unit, source retained."""
    pkg = tmp_path / "soln_package"
    pkg.mkdir()
    (pkg / "unit1_calculus.xml").write_text(unit_xml, encoding="utf-8")
    (pkg / "llmgrader_config.xml").write_text(PKG_CONFIG, encoding="utf-8")
    return pkg


def test_check_against_a_package_matches_the_unit_by_its_source_path(tmp_path: Path, capsys) -> None:
    """A package stores the unit under <destination> but keeps <source>.

    So the test file's `unit` attribute, which names the authoring-time path,
    still identifies which unit inside the package it is about.
    """
    pkg = _built_package(tmp_path, EXAMPLE_UNIT.read_text(encoding="utf-8"))

    exit_code = llmgrader_test_main(["check", str(EXAMPLE_TESTS), "--pkg", str(pkg)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "unit: unit1_calculus.xml" in out
    assert "0 errors, 0 warnings" in out


def test_check_against_a_stale_package_reports_the_missing_question(tmp_path: Path, capsys) -> None:
    """The reason to check against a package: it may not be what you authored.

    A deployed package built before a question was added still grades students,
    and nothing else in the system notices that its tests have outrun it.
    """
    unit = ET.fromstring(EXAMPLE_UNIT.read_text(encoding="utf-8"))
    for question in list(unit.findall("question")):
        if question.get("qtag") == "Exponential graphing":
            unit.remove(question)
    pkg = _built_package(tmp_path, ET.tostring(unit, encoding="unicode"))

    exit_code = llmgrader_test_main(["check", str(EXAMPLE_TESTS), "--pkg", str(pkg)])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Exponential graphing" in out
    assert "does not exist in unit1_calculus.xml" in out


def test_check_against_a_zipped_package(tmp_path: Path) -> None:
    pkg = _built_package(tmp_path, EXAMPLE_UNIT.read_text(encoding="utf-8"))
    archive = tmp_path / "soln_package.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for path in pkg.iterdir():
            handle.write(path, path.name)

    assert llmgrader_test_main(["check", str(EXAMPLE_TESTS), "--pkg", str(archive)]) == 0


def test_check_against_a_directory_that_is_not_a_package_exits_two(tmp_path: Path, capsys) -> None:
    exit_code = llmgrader_test_main(["check", str(EXAMPLE_TESTS), "--pkg", str(tmp_path)])

    assert exit_code == 2
    assert "llmgrader_config.xml" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Authoring warnings carried over from the unit
# ---------------------------------------------------------------------------


def _unit_with_display_text(tmp_path: Path, display_text: str) -> Path:
    """A minimal one-question unit whose sole rubric item is on part a."""
    path = tmp_path / "unit.xml"
    path.write_text(
        dedent(
            f"""
            <unit id="u" title="U" version="1.0">
              <question qtag="Q">
                <question_text>Question.</question_text>
                <solution>Solution.</solution>
                <partial_credit>true</partial_credit>
                <parts>
                  <part><part_label>a</part_label><points>2</points></part>
                </parts>
                <rubrics>
                  <item id="r1" part="a" point_adjustment="+2">
                    <display_text>{display_text}</display_text>
                    <condition>Condition.</condition>
                  </item>
                </rubrics>
                <rubric_total>sum_positive</rubric_total>
              </question>
            </unit>
            """
        ).strip(),
        encoding="utf-8",
    )
    return path


def _check_against(tmp_path: Path, unit_path: Path):
    tests = _write_test_file(
        tmp_path,
        """
        <case id="c1" qtag="Q">
          <description>A case.</description>
          <solution>An answer.</solution>
          <expected_points>
            <part label="a" min="1"/>
          </expected_points>
        </case>
        """,
        unit=unit_path.as_posix(),
    )
    return check_path(str(tests), coverage=False)


def test_display_text_repeating_its_part_label_warns_through_check(tmp_path: Path) -> None:
    # The unit is the one at fault, so the finding points at the unit file.
    result = _check_against(tmp_path, _unit_with_display_text(tmp_path, "Part a: Thing"))

    assert result.errors == []
    finding = _one(result.findings, "display_text", level=LEVEL_WARNING)
    assert "Part a: Part a: ..." in finding.message
    assert finding.file.endswith("unit.xml")


def test_clean_display_text_produces_no_authoring_warning(tmp_path: Path) -> None:
    result = _check_against(tmp_path, _unit_with_display_text(tmp_path, "Thing"))

    assert result.errors == []
    assert _messages(result.findings, LEVEL_WARNING) == []
