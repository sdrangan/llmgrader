"""The API key wizard sentinel must survive grade_post_process untouched.

The front end matches ``full_explanation`` against the sentinel exactly
(app.js, gradeCurrentQuestion). Two writers used to append to that field on the
way out -- ``append_tool_summary`` always adds a "Tools:" line, and
``invalid_grade`` adds a grader-error line on any multi-part question, because
the stub grade carries no ``point_parts``. Either one silently disables the
wizard, which is invisible in the UI: the student just sees an error.
"""

from pathlib import Path

import pytest

from llmgrader.services.grader import API_KEY_WALKTHROUGH_TOKEN, Grader


@pytest.fixture()
def grader(tmp_path: Path, monkeypatch) -> Grader:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    return Grader(scratch_dir=str(tmp_path / "scratch"))


def _stub_grade(reason: str = "Add your OpenAI API key to continue.") -> dict:
    """The dict grade() builds when no usable API key is available."""
    return {
        "result": "error",
        "full_explanation": API_KEY_WALKTHROUGH_TOKEN,
        "feedback": reason,
    }


def test_sentinel_survives_single_part_question(grader: Grader) -> None:
    result = grader.grade_post_process(
        _stub_grade(),
        partial_credit=False,
        max_points_part=10,
        part_labels=["all"],
    )

    assert result.full_explanation == API_KEY_WALKTHROUGH_TOKEN


def test_sentinel_survives_when_tools_are_requested(grader: Grader) -> None:
    """append_tool_summary appends "Tools: None" even with no tools."""
    result = grader.grade_post_process(
        _stub_grade(),
        partial_credit=False,
        max_points_part=10,
        part_labels=["all"],
        tools=["python"],
    )

    assert result.full_explanation == API_KEY_WALKTHROUGH_TOKEN


def test_sentinel_survives_multi_part_question(grader: Grader) -> None:
    """The stub grade has no point_parts, so this lands in invalid_grade."""
    result = grader.grade_post_process(
        _stub_grade(),
        partial_credit=True,
        max_points_part=[4, 6],
        part_labels=["a", "b"],
    )

    assert result.full_explanation == API_KEY_WALKTHROUGH_TOKEN


def test_reason_reaches_the_student_facing_field(grader: Grader) -> None:
    """The feedback box is the only prose box now, so the reason must land there."""
    result = grader.grade_post_process(
        _stub_grade("Community token limit reached."),
        partial_credit=True,
        max_points_part=[4, 6],
        part_labels=["a", "b"],
    )

    assert "Community token limit reached." in result.feedback
