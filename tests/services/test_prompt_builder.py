import pytest

from llmgrader.services.prompt import PromptBuilder


def _base_question_dict() -> dict:
    return {
        "question_text": "<p>Question body</p>",
        "solution": "<p>Reference solution</p>",
        "grading_notes": "Use the rubric carefully.",
    }


def test_get_grading_mode_selects_expected_mode() -> None:
    builder = PromptBuilder()

    assert builder.get_grading_mode(True, ["all"], "all") == "partial_single"
    assert builder.get_grading_mode(True, ["a", "b"], "all") == "partial_multi_all"
    assert builder.get_grading_mode(True, ["a", "b"], "a") == "partial_multi_single"
    assert builder.get_grading_mode(False, ["all"], "all") == "binary_single"
    assert builder.get_grading_mode(False, ["a", "b"], "all") == "binary_multi_all"
    assert builder.get_grading_mode(False, ["a", "b"], "a") == "binary_multi_single"


def test_build_task_prompt_no_rubric_partial_multi_all_includes_part_contract() -> None:
    question_dict = {
        **_base_question_dict(),
        "partial_credit": True,
        "parts": [
            {"part_label": "a", "points": 3},
            {"part_label": "b", "points": 2},
        ],
        "rubrics": {},
    }

    prompt, max_points_part = PromptBuilder().build_task_prompt(question_dict, "student answer", part_label="all")

    assert max_points_part == [3, 2]
    assert '"point_parts": a list of numeric values' in prompt
    assert "- (a): max_points = 3" in prompt
    assert "- (b): max_points = 2" in prompt
    assert "--- QUESTION HTML ---" in prompt
    assert "--- STUDENT SOLUTION ---" in prompt


def test_build_task_prompt_rubric_partial_single_includes_point_awarded_contract() -> None:
    question_dict = {
        **_base_question_dict(),
        "partial_credit": True,
        "parts": [{"part_label": "all", "points": 10}],
        "rubrics": {
            "correct_method": {
                "part": "all",
                "point_adjustment": 4,
                "display_text": "Correct method",
                "condition": "Student uses the correct method.",
            }
        },
        "rubric_groups": [],
        "rubric_total": "sum_positive",
    }

    prompt, max_points_part = PromptBuilder().build_task_prompt(question_dict, "student answer")

    assert max_points_part == 10
    assert '"points": the final numeric score for this question' in prompt
    assert '"rubric_eval": an object keyed by rubric id.' in prompt
    assert '"point_awarded": the numeric adjustment awarded' in prompt
    assert "Do not count the same evidence twice." in prompt
    assert "sum the awarded rubric points from 0 and clamp the result to [0, 10]" in prompt


def test_build_task_prompt_rubric_partial_multi_single_filters_to_requested_part() -> None:
    question_dict = {
        **_base_question_dict(),
        "partial_credit": True,
        "parts": [
            {"part_label": "a", "points": 4},
            {"part_label": "b", "points": 6},
        ],
        "rubrics": {
            "part_a_item": {
                "part": "a",
                "point_adjustment": 4,
                "display_text": "Part a criterion",
                "condition": "Correct part a work.",
            },
            "part_b_item": {
                "part": "b",
                "point_adjustment": 6,
                "display_text": "Part b criterion",
                "condition": "Correct part b work.",
            },
            "global_item": {
                "part": "all",
                "point_adjustment": -1,
                "display_text": "Global issue",
                "condition": "Applies to either part.",
            },
        },
        "rubric_groups": [],
        "rubric_total": "sum_positive",
    }

    prompt, max_points_part = PromptBuilder().build_task_prompt(question_dict, "student answer", part_label="a")

    assert max_points_part == 4
    assert "grading only part (a)" in prompt
    assert "- id: part_a_item" in prompt
    assert "- id: global_item" in prompt
    assert "- id: part_b_item" not in prompt
    assert '"points": the final numeric score for part (a)' in prompt


def test_build_task_prompt_rubric_binary_multi_all_includes_result_contract() -> None:
    question_dict = {
        **_base_question_dict(),
        "partial_credit": False,
        "parts": [
            {"part_label": "a", "points": 5},
            {"part_label": "b", "points": 5},
        ],
        "rubrics": {
            "method_a": {
                "part": "a",
                "display_text": "Method for part a",
                "condition": "Student solves part a correctly.",
                "condition_type": "positive",
                "action": "fail",
            },
            "method_b": {
                "part": "b",
                "display_text": "Method for part b",
                "condition": "Student solves part b correctly.",
                "condition_type": "positive",
                "action": "fail",
            },
        },
        "rubric_groups": [{"type": "one_of", "ids": ["method_a", "method_b"]}],
    }

    prompt, max_points_part = PromptBuilder().build_task_prompt(question_dict, "student answer", part_label="all")

    assert max_points_part == [5, 5]
    assert '"result_parts": a list with one value for each part' in prompt
    assert '"result": one of "pass", "fail", "feedback", or "n/a".' in prompt
    assert "Do not count the same evidence twice." in prompt
    assert "- type: one_of; ids: method_a, method_b" in prompt


def test_build_task_prompt_rubric_binary_single_includes_sections_and_json_rule() -> None:
    question_dict = {
        **_base_question_dict(),
        "partial_credit": False,
        "parts": [{"part_label": "all", "points": 3}],
        "rubrics": {
            "final_answer": {
                "part": "all",
                "display_text": "Final answer",
                "condition": "Student gives the correct final answer.",
                "condition_type": "positive",
                "action": "fail",
            }
        },
        "rubric_groups": [],
    }

    prompt, max_points_part = PromptBuilder().build_task_prompt(question_dict, "student answer")

    assert max_points_part == 3
    assert '"result": one of "pass", "fail", or "error".' in prompt
    assert 'Return exactly one valid JSON object and nothing else.' in prompt
    assert "--- REFERENCE SOLUTION HTML ---" in prompt
    assert "--- GRADING NOTES ---" in prompt


@pytest.mark.parametrize(
    ("rubric_total", "expected_fragment"),
    [
        ("sum_positive", "sum the awarded rubric points from 0 and clamp the result to [0, 10]"),
        ("sum_negative", "start from 10, add the awarded rubric adjustments, and clamp the result to [0, 10]"),
        (
            "flexible",
            "use the rubric award sum as a baseline, then adjust if needed based on the overall work and grading notes",
        ),
    ],
)
def test_build_task_prompt_rubric_total_text_matches_mode(rubric_total: str, expected_fragment: str) -> None:
    question_dict = {
        **_base_question_dict(),
        "partial_credit": True,
        "parts": [{"part_label": "all", "points": 10}],
        "rubrics": {
            "criterion": {
                "part": "all",
                "point_adjustment": 2,
                "display_text": "Criterion",
                "condition": "Student meets the criterion.",
            }
        },
        "rubric_groups": [],
        "rubric_total": rubric_total,
    }

    prompt, _ = PromptBuilder().build_task_prompt(question_dict, "student answer")

    assert expected_fragment in prompt