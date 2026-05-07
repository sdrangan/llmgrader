"""E2E tests for the Analytics / Database Viewer.

The analytics view is an SQL REPL over the grading database.  Tests run in
dev-open mode (which grants admin access) so the view is unlocked.
"""

from pages.analytics_page import AnalyticsPage


def test_analytics_view_loads(page, live_server):
    """Switching to Analytics shows the analytics container."""
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    assert ap.view.is_visible()


def test_analytics_sql_input_visible(page, live_server):
    """The SQL textarea is visible and editable."""
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    assert ap.sql_input.is_visible()


def test_analytics_run_button_visible(page, live_server):
    """The Run Query button is visible."""
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    assert ap.run_button.is_visible()


def test_analytics_results_table_present(page, live_server):
    """The results table element is present in the DOM."""
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    assert ap.results_table.count() > 0


def test_analytics_default_query_preloaded(page, live_server):
    """On first load the SQL input is pre-filled with a SELECT query."""
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    sql_value = ap.sql_input.input_value()
    assert "SELECT" in sql_value.upper(), (
        f"Expected a SELECT statement pre-loaded, got: {sql_value!r}"
    )


def test_analytics_default_query_runs_without_error(page, live_server):
    """The default query completes without showing an error."""
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.wait_for_query_complete()
    assert not ap.error_box.is_visible(), (
        f"Unexpected error after default query: {ap.error_box.inner_text()!r}"
    )


def test_analytics_invalid_sql_shows_error(page, live_server):
    """Submitting a non-SELECT statement shows an error message."""
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.run_query("DROP TABLE submissions")
    ap.wait_for_error()
    assert ap.error_box.is_visible()
    assert ap.error_box.inner_text().strip(), "Error box should contain a message"
