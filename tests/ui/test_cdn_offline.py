"""Grading still works when the CDN does not.

index.html loads MathJax and marked from cdn.jsdelivr.net.  A student on a
network that blocks it -- a corporate proxy, a captive portal, a campus
firewall, jsdelivr having a bad day -- gets the page but not the libraries.

MathJax is the dangerous one, because it is *configured* by assigning
``window.MathJax`` before the script tag runs.  So the object exists whether or
not the library ever arrived, and a truthiness check on it is not a check that
MathJax loaded.  Calling ``typesetPromise`` then throws synchronously inside
the grade handler, the surrounding catch turns a completed grade into an error
string, and the result is never written to session state either.

The CDN is reachable from a development machine, so every other test in this
suite passes with or without the guard.  That is the whole reason this file
exists: blocking the CDN at the browser is the only way the guard is actually
covered.
"""

import re

import pytest

from pages.grader_page import GraderPage

CDN = re.compile(r"https?://cdn\.jsdelivr\.net/")


@pytest.fixture()
def offline_cdn_page(page, live_server):
    """A grader page loaded with cdn.jsdelivr.net unreachable.

    Routed before the first navigation, so the script tags fail on the way in
    rather than being served from Playwright's cache.
    """
    page.route(CDN, lambda route: route.abort())

    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.set_api_key("test-key-ui")
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()
    gp.wait_for_questions_loaded()
    return gp


def test_the_cdn_really_is_blocked(offline_cdn_page):
    """Guard against the test quietly going vacuous.

    ``window.MathJax`` is still truthy -- that is the config object index.html
    assigns, and it is exactly what made the old check pass.  What is missing
    is the method.  If this assertion ever fails, the tests below stop proving
    anything and should not be believed.
    """
    page = offline_cdn_page._page

    assert page.evaluate("Boolean(window.MathJax)") is True, (
        "index.html should still have assigned the MathJax config object"
    )
    assert page.evaluate("typeof (window.MathJax || {}).typesetPromise") == "undefined", (
        "MathJax appears to have loaded; the CDN route interception is not working"
    )


def test_grading_reports_its_result_when_the_cdn_is_blocked(offline_cdn_page):
    """The student sees their grade, not a TypeError."""
    page = offline_cdn_page._page

    dialogs = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

    offline_cdn_page.submit_answer("The answer is 4.")
    offline_cdn_page.wait_for_result(timeout=20_000)

    status = offline_cdn_page.grade_live_status.inner_text()
    assert status.startswith("Done in"), (
        f"Grading should have completed cleanly, but the status reads: {status!r}"
    )
    assert dialogs == [], f"Grading raised an alert: {dialogs!r}"

    feedback = offline_cdn_page.get_feedback_text()
    assert "Correct!" in feedback, (
        f"Expected the graded feedback to render without MathJax, got: {feedback!r}"
    )


def test_the_grade_summary_renders_when_the_cdn_is_blocked(offline_cdn_page):
    """The result and points are what the student is actually here for."""
    offline_cdn_page.submit_answer("The answer is 4.")
    offline_cdn_page.wait_for_result(timeout=20_000)

    assert offline_cdn_page.get_grade_status_text().strip() != ""
    assert offline_cdn_page.get_grade_points_text().strip() != ""


def test_the_grade_reaches_session_state_when_the_cdn_is_blocked(offline_cdn_page):
    """The saved grade is the silent casualty of the throw.

    updateSessionData runs *after* the feedback is rendered, so a typesetting
    TypeError loses the stored result as well as the displayed one -- and the
    student only finds out when the dashboard comes up empty.
    """
    page = offline_cdn_page._page

    offline_cdn_page.submit_answer("The answer is 4.")
    offline_cdn_page.wait_for_result(timeout=20_000)

    saved = page.evaluate(
        """() => {
            const keys = Object.keys(localStorage)
                .filter(k => k === 'llmgrader_session' || k.startsWith('llmgrader_session:'));
            return keys.map(k => localStorage.getItem(k)).join('');
        }"""
    )
    assert "pass" in saved, f"Expected the grade in saved session state, got: {saved!r}"


def test_question_text_still_renders_when_the_cdn_is_blocked(offline_cdn_page):
    """Questions display unstyled rather than not at all."""
    question_box = offline_cdn_page._page.locator("#question-text")
    assert question_box.inner_text().strip() != ""
