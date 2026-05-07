"""Happy-path E2E tests for the grading workflow.

These tests exercise the full browser → Flask → (mocked) LLM → browser loop.
No real OpenAI calls are made: the OpenAI client is patched at the Python level
in conftest.py so grader.py returns a deterministic canned result.

Run with:
    pytest tests/ui/test_grading_flow.py          # headless
    pytest tests/ui/test_grading_flow.py --headed  # see the browser
"""

import pytest


# ---------------------------------------------------------------------------
# Page loads
# ---------------------------------------------------------------------------

def test_page_title(page, live_server):
    """The main page should have the expected title."""
    page.goto(live_server)
    assert "Grader" in page.title() or "AI" in page.title()


def test_grade_view_elements_visible(grader_page):
    """Core grade-view elements should be visible after the SPA initialises."""
    assert grader_page.student_solution.is_visible()
    assert grader_page.grade_button.is_visible()
    assert grader_page.feedback_box.is_visible()
    assert grader_page.full_explanation_box.is_visible()


def test_unit_dropdown_populated(grader_page):
    """Unit dropdown must contain at least one selectable option."""
    options = grader_page.unit_select.locator("option").all()
    selectable = [o for o in options if o.get_attribute("disabled") is None]
    assert len(selectable) >= 1, "Unit dropdown should have at least one option"


def test_question_dropdown_populated(grader_page):
    """Question dropdown must contain at least one option once a unit is loaded."""
    options = grader_page.question_select.locator("option").all()
    assert len(options) >= 1, "Question dropdown should have at least one option"


# ---------------------------------------------------------------------------
# Grading flow
# ---------------------------------------------------------------------------

def test_grade_button_enabled_before_grading(grader_page):
    """Grade button should be enabled before grading is triggered."""
    assert grader_page.is_grade_button_enabled()


def test_submit_shows_live_status(grader_page):
    """Clicking Grade should make the live-status element show progress text."""
    grader_page.student_solution.fill("The answer is 4.")
    grader_page.grade_button.click()

    # The status message updates as grading progresses — wait for any content
    grader_page._page.wait_for_function(
        "document.getElementById('grade-live-status') && "
        "document.getElementById('grade-live-status').textContent.trim().length > 0",
        timeout=5_000,
    )
    live_text = grader_page.grade_live_status.inner_text()
    assert live_text.strip() != ""


def test_grading_result_populates_feedback(grader_page):
    """After grading, the feedback box should contain non-placeholder text."""
    grader_page.submit_answer("The answer is 4.")
    grader_page.wait_for_result(timeout=20_000)

    feedback = grader_page.get_feedback_text()
    # The canned mock returns "Correct! 2 + 2 = 4." in the feedback field
    assert feedback.strip() not in ("", "No feedback yet."), (
        f"Expected feedback from mock but got: {feedback!r}"
    )


def test_grading_result_populates_explanation(grader_page):
    """After grading, the full-explanation box should be filled in."""
    grader_page.submit_answer("4")
    grader_page.wait_for_result(timeout=20_000)

    explanation = grader_page.full_explanation_box.inner_text()
    assert explanation.strip() not in ("", "No explanation yet."), (
        f"Expected explanation from mock but got: {explanation!r}"
    )


def test_grade_button_re_enabled_after_grading(grader_page):
    """Grade button should be re-enabled once the grading job completes."""
    grader_page.submit_answer("4")
    grader_page.wait_for_result(timeout=20_000)

    assert grader_page.is_grade_button_enabled(), (
        "Grade button should be re-enabled after the job finishes"
    )


def test_second_submission_replaces_result(grader_page):
    """A second submission should overwrite the previous feedback."""
    grader_page.submit_answer("4")
    grader_page.wait_for_result(timeout=20_000)
    first_feedback = grader_page.get_feedback_text()

    # Submit again — the mock always returns the same canned result,
    # but we verify the flow completes without errors.
    grader_page.submit_answer("2 + 2 equals 4")
    grader_page.wait_for_result(timeout=20_000)
    second_feedback = grader_page.get_feedback_text()

    assert second_feedback.strip() not in ("", "No feedback yet."), (
        "Second submission should also populate feedback"
    )
    # Both submissions return the same mock, so content equality is expected
    assert second_feedback == first_feedback
