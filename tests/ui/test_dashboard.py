"""E2E tests for the Dashboard view.

The dashboard displays per-question grading results for a selected unit.
These tests verify the initial (empty) state and structural presence of the
table — no grading submissions are needed.
"""

from pages.dashboard_page import DashboardPage


def test_dashboard_view_loads(page, live_server):
    """Switching to Dashboard shows the dashboard container."""
    dp = DashboardPage(page)
    dp.navigate(live_server)
    assert dp.view.is_visible()


def test_dashboard_table_body_visible(page, live_server):
    """The results table body is present in the DOM."""
    dp = DashboardPage(page)
    dp.navigate(live_server)
    assert dp.table_body.is_visible()


def test_dashboard_table_rows_populated(page, live_server):
    """The dashboard auto-loads the current unit and shows question rows."""
    dp = DashboardPage(page)
    dp.navigate(live_server)
    rows = dp.table_body.locator("tr").all()
    assert len(rows) >= 1, "Dashboard table should have at least one question row"


def test_dashboard_totals_footer_present(page, live_server):
    """Both totals footer cells exist and are visible."""
    dp = DashboardPage(page)
    dp.navigate(live_server)
    assert dp.total_all_points.is_visible()
    assert dp.total_required_points.is_visible()


def test_dashboard_totals_show_points_fraction(page, live_server):
    """Totals show a 'earned/max' fraction once the unit is loaded."""
    dp = DashboardPage(page)
    dp.navigate(live_server)
    text = dp.total_all_points.inner_text().strip()
    assert "/" in text, f"Expected 'N/M' format in totals, got: {text!r}"


def test_dashboard_unit_dropdown_accessible(page, live_server):
    """The shared unit selector in the top bar is visible from the dashboard."""
    dp = DashboardPage(page)
    dp.navigate(live_server)
    assert dp.unit_select.is_visible()
