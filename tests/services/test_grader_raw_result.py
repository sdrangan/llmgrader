"""GraderRawResult: parsing the model's JSON reply."""

import json

from llmgrader.services.grader import GraderRawResult, normalize_json_response_text


def test_trailing_commas_are_repaired_but_commas_in_strings_kept() -> None:
    # Seen live from GPT-6 Luna on a web_search question, which runs without
    # JSON mode: "trailing comma at line 50 column 5".
    reply = """{
  "point_parts": [8.0, 2.0,],
  "full_explanation": "Has a, ] and a ,} inside.",
  "feedback": "ok \\", }",
  "rubric_eval": {
    "a": {"evidence": "x", "point_awarded": 8.0,},
  },
}"""

    parsed = GraderRawResult.model_validate_json(normalize_json_response_text(reply))

    assert parsed.point_parts == [8.0, 2.0]
    assert parsed.full_explanation == "Has a, ] and a ,} inside."
    assert parsed.feedback == 'ok ", }'
    assert parsed.rubric_eval["a"]["point_awarded"] == 8.0


def test_a_stray_non_object_entry_in_rubric_eval_is_dropped() -> None:
    # Seen live: the model put its feedback text into rubric_eval as well as
    # into "feedback", and the whole grade was refused over it.
    reply = {
        "point_parts": [2.0, 1.0],
        "full_explanation": "Summary.",
        "feedback": "The command structure is clear.",
        "rubric_eval": {
            "th_op_precise": {"evidence": "Formula given.", "point_awarded": 2.0},
            "feedback": "The command structure is clear.",
            "th_targets": {"evidence": "No target.", "point_awarded": 0.0},
        },
    }

    parsed = GraderRawResult.model_validate_json(json.dumps(reply))

    assert set(parsed.rubric_eval) == {"th_op_precise", "th_targets"}
    assert parsed.rubric_eval["th_op_precise"]["point_awarded"] == 2.0


def test_rubric_eval_may_be_absent() -> None:
    parsed = GraderRawResult.model_validate_json(
        json.dumps({"full_explanation": "x", "feedback": "y"})
    )

    assert parsed.rubric_eval is None
