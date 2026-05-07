"""Responsive layout E2E tests.

Verifies that the grading UI remains usable across common viewport sizes.
No grading is triggered — these tests only check that key elements are
visible and not clipped/hidden at each breakpoint.
"""

import pytest
from pages.grader_page import GraderPage

VIEWPORTS = [
    pytest.param({"width": 375, "height": 812}, id="mobile-375x812"),
    pytest.param({"width": 768, "height": 1024}, id="tablet-768x1024"),
    pytest.param({"width": 1280, "height": 900}, id="desktop-1280x900"),
    pytest.param({"width": 1920, "height": 1080}, id="wide-1920x1080"),
]


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_grade_button_visible_at_viewport(page, live_server, viewport):
    """The Grade button must be visible at every supported viewport."""
    page.set_viewport_size(viewport)
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.wait_for_grade_view()

    assert gp.grade_button.is_visible(), (
        f"Grade button not visible at viewport {viewport}"
    )


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_student_input_visible_at_viewport(page, live_server, viewport):
    """The student-answer textarea must be accessible at every viewport."""
    page.set_viewport_size(viewport)
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.wait_for_grade_view()

    assert gp.student_solution.is_visible(), (
        f"Student solution textarea not visible at viewport {viewport}"
    )


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_unit_dropdown_visible_at_viewport(page, live_server, viewport):
    """The unit selector must be visible and functional at every viewport."""
    page.set_viewport_size(viewport)
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()

    assert gp.unit_select.is_visible(), (
        f"Unit dropdown not visible at viewport {viewport}"
    )


@pytest.mark.parametrize("viewport", VIEWPORTS)
def test_feedback_area_present_at_viewport(page, live_server, viewport):
    """The feedback panel must be present in the DOM at every viewport.

    On narrow viewports the panel may be hidden behind a tab — we only
    assert it exists in the DOM, not that it is pixel-visible.
    """
    page.set_viewport_size(viewport)
    gp = GraderPage(page)
    gp.navigate(live_server)
    gp.wait_for_grade_view()

    assert gp.feedback_box.count() > 0, (
        f"Feedback box element missing from DOM at viewport {viewport}"
    )
