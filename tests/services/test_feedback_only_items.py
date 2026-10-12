"""Feedback-only rubric items (``scored="false"``).

Such an item asks the grader for an analysis of the student's answer -- a sanity
check, a trace, an estimate -- and reports it below the rubric table.  It awards
no points and passes or fails nothing, so every place that totals, tabulates or
asserts on rubric items has to leave it out.
"""

from pathlib import Path

import pytest

from llmgrader.services.gradetests import check_path
from llmgrader.services.grader import Grader
from llmgrader.services.prompt import PromptBuilder
from llmgrader.services.unit_parser import UnitParser


UNIT_XML = """<unit id="rc" title="RC" version="1.0">
  <question qtag="RC step" preferred_model="standard">
    <question_text><![CDATA[<p>Find v_C(t).</p>]]></question_text>
    <solution><![CDATA[<p>v_C(t) = 5 - 3 exp(-t) V.</p>]]></solution>
    <partial_credit>true</partial_credit>
    <parts>
      <part><part_label>a</part_label><points>2</points></part>
      <part><part_label>b</part_label><points>2</points></part>
    </parts>
    <rubrics>
      <item id="tau" part="a" point_adjustment="+2">
        <display_text>Time constant</display_text>
        <condition>tau = RC = 1 s.</condition>
      </item>
      <item id="form" part="b" point_adjustment="+2">
        <display_text>Step response</display_text>
        <condition>v_C(t) = 5 - 3 exp(-t/tau).</condition>
      </item>
      <item id="limits" scored="false">
        <display_text>Check at the limits</display_text>
        <condition>Evaluate the student's expression at t = 0 and as t goes to infinity.</condition>
      </item>
    </rubrics>
  </question>
</unit>
"""


def _write_unit(tmp_path: Path, text: str = UNIT_XML) -> Path:
    path = tmp_path / "rc.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _parsed_rubrics(tmp_path: Path) -> dict:
    _write_unit(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    parser = UnitParser(scratch_dir=str(scratch), soln_pkg=str(tmp_path), supported_tools=[])
    units, _, errors = parser.parse_unit_files([("rc", "rc.xml")])
    assert errors == []
    return units["rc"]["RC step"]["rubrics"]


# -- parsing and validation ----------------------------------------------------


def test_parsed_item_is_marked_and_carries_no_scoring_fields(tmp_path: Path) -> None:
    rubrics = _parsed_rubrics(tmp_path)

    assert rubrics["limits"]["scored"] is False
    assert "point_adjustment" not in rubrics["limits"]
    assert rubrics["limits"]["part"] == "all"
    assert "scored" not in rubrics["tau"]


def test_part_all_is_allowed_on_a_multi_part_sum_positive_question(tmp_path: Path) -> None:
    # A scored item at part='all' is an error here; a feedback-only one counts
    # toward no part, so it is not -- and it adds nothing to the part sums.
    assert UnitParser.validate_unit_file(str(_write_unit(tmp_path))) == []


def test_scoring_attributes_on_a_feedback_only_item_are_errors() -> None:
    text = UNIT_XML.replace('<item id="limits" scored="false">', '<item id="limits" scored="false" point_adjustment="+1">')

    result = UnitParser.validate_unit_text(text)

    assert not result["valid"]
    assert any("point_adjustment has no meaning on a feedback-only item" in e for e in result["errors"])


def test_a_feedback_only_item_needs_a_condition() -> None:
    text = UNIT_XML.replace(
        "<condition>Evaluate the student's expression at t = 0 and as t goes to infinity.</condition>", ""
    )

    result = UnitParser.validate_unit_text(text)

    assert any("needs a <condition>" in e for e in result["errors"])


def test_a_feedback_only_item_cannot_be_in_a_one_of_group() -> None:
    text = UNIT_XML.replace(
        "    </rubrics>",
        "      <group type=\"one_of\"><id>form</id><id>limits</id></group>\n    </rubrics>",
    )

    result = UnitParser.validate_unit_text(text)

    assert any("cannot be in a one_of group" in e for e in result["errors"])


def test_scored_must_be_a_boolean() -> None:
    result = UnitParser.validate_unit_text(UNIT_XML.replace('scored="false"', 'scored="no"'))

    assert not result["valid"]


# -- prompt --------------------------------------------------------------------


def _question(rubrics: dict) -> dict:
    return {
        "question_text": "<p>Find v_C(t).</p>",
        "solution": "<p>v_C(t) = 5 - 3 exp(-t) V.</p>",
        "grading_notes": "",
        "partial_credit": True,
        "parts": [{"part_label": "a", "points": 2}, {"part_label": "b", "points": 2}],
        "rubrics": rubrics,
        "rubric_total": "sum_positive",
    }


def test_prompt_lists_the_item_in_its_own_section_not_among_scored_items(tmp_path: Path) -> None:
    prompt, _ = PromptBuilder().build_task_prompt(_question(_parsed_rubrics(tmp_path)), "v = 5 V")

    scored_block, feedback_block = prompt.split("Feedback-only items:")
    assert "- id: limits" not in scored_block
    assert "- id: limits" in feedback_block
    assert "instruction: Evaluate the student's expression at t = 0" in feedback_block
    assert 'Do not give these ids "point_awarded" or "result"' in feedback_block


def test_a_question_with_only_feedback_only_items_uses_the_no_rubric_template(tmp_path: Path) -> None:
    rubrics = {"limits": _parsed_rubrics(tmp_path)["limits"]}

    prompt, _ = PromptBuilder().build_task_prompt(_question(rubrics), "v = 5 V")

    assert "Rubric items:" not in prompt
    assert "- id: limits" in prompt


def test_prompt_without_feedback_only_items_is_unchanged(tmp_path: Path) -> None:
    rubrics = _parsed_rubrics(tmp_path)
    scored = {k: v for k, v in rubrics.items() if k != "limits"}

    prompt, _ = PromptBuilder().build_task_prompt(_question(scored), "v = 5 V")

    assert "Feedback-only items:" not in prompt


# -- scoring and feedback ------------------------------------------------------


@pytest.fixture()
def grader(tmp_path: Path, monkeypatch) -> Grader:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    return Grader(scratch_dir=str(tmp_path / "scratch_grader"))


def _raw_grade(limits_entry: dict) -> dict:
    return {
        "point_parts": [2.0, 0.0],
        "full_explanation": "tau right, form wrong.",
        "feedback": "Check the initial value.",
        "rubric_eval": {
            "tau": {"evidence": "tau = 1 s.", "point_awarded": 2.0},
            "form": {"evidence": "Starts at 5 V, not 2 V.", "point_awarded": 0.0},
            "limits": limits_entry,
        },
    }


def test_a_stray_award_on_a_feedback_only_item_changes_no_score(tmp_path: Path, grader: Grader) -> None:
    rubrics = _parsed_rubrics(tmp_path)
    # The model was told not to, but suppose it does anyway.
    raw = _raw_grade({"evidence": "At t = 0 it gives 5 V.", "point_awarded": 3.0})

    result = grader.grade_post_process(
        raw, partial_credit=True, max_points_part=[2, 2], part_labels=["a", "b"], rubrics=rubrics,
    )

    assert result.point_parts == [2.0, 0.0]
    assert result.points == 2.0
    assert result.rubric_eval["limits"] == {"evidence": "At t = 0 it gives 5 V."}


def test_feedback_lists_the_item_below_the_table_with_no_score_cell(tmp_path: Path, grader: Grader) -> None:
    rubrics = _parsed_rubrics(tmp_path)
    raw = _raw_grade({"evidence": "At t = 0 your expression gives 5 V,\nbut the capacitor starts at 2 V."})

    result = grader.grade_post_process(
        raw, partial_credit=True, max_points_part=[2, 2], part_labels=["a", "b"], rubrics=rubrics,
    )

    table, notes = result.feedback.split("Notes:")
    assert "Rubric evaluation:" in table
    assert "Check at the limits" not in table
    assert "- **Check at the limits:** At t = 0 your expression gives 5 V, but the capacitor starts at 2 V." in notes


def test_an_empty_note_is_left_out(tmp_path: Path, grader: Grader) -> None:
    rubrics = _parsed_rubrics(tmp_path)

    result = grader.grade_post_process(
        _raw_grade({"evidence": ""}),
        partial_credit=True, max_points_part=[2, 2], part_labels=["a", "b"], rubrics=rubrics,
    )

    assert "Notes:" not in result.feedback


# -- grading tests -------------------------------------------------------------


def _write_tests(tmp_path: Path, expected_rubrics: str) -> Path:
    unit = _write_unit(tmp_path)
    path = tmp_path / "rc_tests.xml"
    path.write_text(
        f"""<unit_test unit="{unit.name}">
  <case id="good" qtag="RC step">
    <description>A correct answer.</description>
    <solution><![CDATA[tau = 1 s; v = 5 - 3 exp(-t) V]]></solution>
    <expected_rubrics>
      <item id="tau" min="2" max="2"/>
      <item id="form" min="2" max="2"/>
{expected_rubrics}    </expected_rubrics>
  </case>
</unit_test>
""",
        encoding="utf-8",
    )
    return path


def test_check_does_not_ask_for_an_assertion_on_a_feedback_only_item(tmp_path: Path) -> None:
    result = check_path(str(_write_tests(tmp_path, "")))

    assert result.errors == []
    assert not [f for f in result.findings if "limits" in f.message]


def test_check_refuses_an_assertion_on_a_feedback_only_item(tmp_path: Path) -> None:
    result = check_path(str(_write_tests(tmp_path, '      <item id="limits" min="0" max="0"/>\n')))

    assert any("feedback-only" in f.message for f in result.errors)
