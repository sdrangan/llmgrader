"""E2E tests for the Admin view.

The admin view shows question text, reference solutions, and grading rubrics
for a selected unit/question.  Tests run in dev-open mode (admin access
granted automatically).
"""

from pages.admin_page import AdminPage


def test_admin_view_loads(page, live_server):
    """Switching to Admin shows the admin container."""
    ap = AdminPage(page)
    ap.navigate(live_server)
    assert ap.view.is_visible()


def test_admin_unit_dropdown_visible(page, live_server):
    """The unit selector is visible in the admin top bar."""
    ap = AdminPage(page)
    ap.navigate(live_server)
    assert ap.unit_select.is_visible()


def test_admin_question_dropdown_visible(page, live_server):
    """The question selector is visible in the admin top bar."""
    ap = AdminPage(page)
    ap.navigate(live_server)
    assert ap.question_select.is_visible()


def test_admin_unit_dropdown_populated(page, live_server):
    """The unit dropdown loads options from the course package."""
    ap = AdminPage(page)
    ap.navigate(live_server)
    ap.wait_for_units_loaded()
    options = ap.unit_select.locator("option").all()
    selectable = [o for o in options if o.get_attribute("disabled") is None]
    assert len(selectable) >= 1, "Admin unit dropdown should have at least one option"


def test_admin_question_dropdown_populated(page, live_server):
    """After the unit loads, the question dropdown is populated."""
    ap = AdminPage(page)
    ap.navigate(live_server)
    ap.wait_for_units_loaded()
    ap.wait_for_questions_loaded()
    options = ap.question_select.locator("option").all()
    assert len(options) >= 1, "Admin question dropdown should have at least one option"


def test_admin_mode_badge_visible(page, live_server):
    """The Binary/Partial credit mode badge is visible."""
    ap = AdminPage(page)
    ap.navigate(live_server)
    ap.wait_for_units_loaded()
    ap.wait_for_questions_loaded()
    assert ap.mode_badge.is_visible()
    badge_text = ap.mode_badge.inner_text().strip()
    assert badge_text in ("Binary", "Partial"), (
        f"Mode badge should show 'Binary' or 'Partial', got: {badge_text!r}"
    )
