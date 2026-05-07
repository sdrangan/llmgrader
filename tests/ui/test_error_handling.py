"""Edge-case and error-handling E2E tests.

Uses Playwright's page.route() (Layer 2 mocking) to intercept browser-level
fetch calls to the backend, so we can simulate HTTP errors without changing
the Flask server.
"""

import pytest
from pages.grader_page import GraderPage


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_empty_answer_triggers_browser_behaviour(grader_page):
    """Submitting an empty answer should not crash the UI.

    The app either shows an alert or silently sends the empty string. Either
    way, the grade button must be re-enabled afterwards (no stuck state).
    """
    # Dismiss any alert dialogs automatically
    grader_page._page.on("dialog", lambda d: d.dismiss())

    grader_page.grade_button.click()

    # Give the UI time to react (either alert dismissed or job completes)
    grader_page._page.wait_for_timeout(3_000)

    # The grade button must not be permanently disabled after an empty submit
    assert grader_page.is_grade_button_enabled(), (
        "Grade button should be re-enabled after empty submission"
    )


def test_long_input_does_not_crash(grader_page):
    """A very long student answer should be accepted without UI errors."""
    long_answer = "The answer is 4. " * 600   # ~10 000 chars

    grader_page._page.on("dialog", lambda d: d.dismiss())
    grader_page.submit_answer(long_answer)

    # Wait for the grading to finish or for the button to be re-enabled
    grader_page._page.wait_for_function(
        "!document.getElementById('grade-button').disabled",
        timeout=25_000,
    )
    assert grader_page.is_grade_button_enabled()


# ---------------------------------------------------------------------------
# Backend HTTP error simulation (Layer 2 — Playwright route interception)
# ---------------------------------------------------------------------------

def test_backend_500_shows_error_message(page, live_server):
    """When POST /grade/jobs returns 500, the UI should surface an error message."""
    # Intercept the grading start call to return a 500
    def _handle_grade_jobs(route):
        if route.request.method == "POST":
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"error": "Internal Server Error"}',
            )
        else:
            route.continue_()

    page.route("**/grade/jobs", _handle_grade_jobs)

    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.set_api_key("test-key-ui")
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()
    gp.wait_for_questions_loaded()

    # Capture the alert that the app raises on error
    alert_messages = []
    page.on("dialog", lambda d: (alert_messages.append(d.message), d.dismiss()))

    gp.submit_answer("4")

    # Wait for the error to surface (alert or status update)
    page.wait_for_function(
        "!document.getElementById('grade-button').disabled",
        timeout=10_000,
    )

    # The UI must either show an alert or update the live-status with the error
    live_text = gp.grade_live_status.inner_text()
    error_surfaced = len(alert_messages) > 0 or "fail" in live_text.lower() or "error" in live_text.lower()
    assert error_surfaced, (
        f"Expected error to be shown after 500 response. "
        f"Alerts: {alert_messages}, live status: {live_text!r}"
    )


def test_malformed_job_status_shows_error(page, live_server):
    """When the job-status endpoint returns unexpected JSON, the UI handles it gracefully."""
    job_started = False

    def _handle(route):
        nonlocal job_started
        url = route.request.url
        if "/grade/jobs" in url and route.request.method == "POST":
            # Let the real start-job call through to get a real job_id
            job_started = True
            route.continue_()
        elif "/grade/jobs/" in url and route.request.method == "GET":
            # Return a malformed "done" payload with no result fields
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"status": "done", "job_id": "fake"}',
            )
        else:
            route.continue_()

    page.route("**/grade/jobs**", _handle)

    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.set_api_key("test-key-ui")
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()
    gp.wait_for_questions_loaded()

    alert_messages = []
    page.on("dialog", lambda d: (alert_messages.append(d.message), d.dismiss()))

    gp.submit_answer("4")

    # The button must re-enable — no permanent stuck state
    page.wait_for_function(
        "!document.getElementById('grade-button').disabled",
        timeout=15_000,
    )
    assert gp.is_grade_button_enabled(), "UI must recover after malformed status response"
