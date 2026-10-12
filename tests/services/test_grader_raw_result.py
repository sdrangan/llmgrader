"""GraderRawResult: parsing the model's JSON reply."""

import json

from llmgrader.services.grader import GraderRawResult


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
