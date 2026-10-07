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


def test_analytics_default_query_is_scoped_to_the_course(page, live_server):
    """The default query names course_id and filters by the course being served.

    Submissions from every course share one table, so an unscoped default
    would quietly report another course's numbers once there is a second one.
    This exercises the whole chain: the served course's id reaches index.html,
    analytics.js builds the WHERE clause from it, and the box opens with it.
    The fixture package authors <course_id>ui_test_course</course_id>.
    """
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    sql = ap.sql_input.input_value()

    assert "course_id" in sql, f"Expected course_id in the default query, got: {sql!r}"
    assert "WHERE course_id = 'ui_test_course'" in sql, (
        f"Expected the default query scoped to the served course, got: {sql!r}"
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


# ---------------------------------------------------------------------------
# Grade DB / MCP DB (plans/mcp_usage.md, decision 8)
# ---------------------------------------------------------------------------


def test_the_menu_lists_both_databases_with_grade_checked(page, live_server):
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.open_menu()
    assert page.locator("#analytics-db-grade-item").is_visible()
    assert page.locator("#analytics-db-mcp-item").is_visible()
    assert ap.checked_db() == "grade"
    assert ap.db_name() == "Grade DB"
    # Trimming usage is offered only while the usage database is active.
    assert not page.locator("#analytics-delete-usage-menu-item").is_visible()


def test_switching_changes_schema_and_query_and_clears_results(page, live_server):
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.wait_for_query_complete()
    grade_sql = ap.sql_input.input_value()
    assert "submissions" in ap.schema_tables()

    ap.choose_db("mcp")
    assert ap.checked_db() == "mcp"
    assert ap.db_name() == "MCP DB"
    ap.wait_for_schema_table("mcp_calls")
    assert "submissions" not in ap.schema_tables()
    assert "FROM mcp_calls" in ap.sql_input.input_value()
    assert ap.result_rows() == 0
    assert page.locator("#analytics-results-table thead tr").count() == 0
    ap.open_menu()
    assert page.locator("#analytics-delete-usage-menu-item").is_visible()

    # Back again: the grading query that was in the box comes back.
    ap.choose_db("grade")
    ap.wait_for_schema_table("submissions")
    assert ap.sql_input.input_value() == grade_sql


def test_run_query_uses_the_active_database(page, live_server):
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.wait_for_query_complete()
    ap.choose_db("mcp")
    ap.wait_for_schema_table("mcp_calls")

    with page.expect_response(lambda r: r.url.endswith("/admin/dbviewer")) as info:
        ap.run_query("SELECT COUNT(*) AS calls FROM mcp_calls")
    assert info.value.request.post_data_json["db"] == "mcp"
    ap.wait_for_query_complete()
    assert not ap.error_box.is_visible(), ap.error_box.inner_text()
    # Usage rows have no submission page to link to.
    assert page.locator("#analytics-results-table thead th").all_inner_texts() == ["calls"]


def test_download_csv_uses_the_active_database(page, live_server):
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.wait_for_query_complete()
    ap.choose_db("mcp")
    ap.wait_for_schema_table("mcp_calls")
    ap.run_query("SELECT 1 AS one FROM mcp_calls UNION ALL SELECT 1")
    ap.wait_for_query_complete()

    with page.expect_download() as info:
        page.click("#analytics-download-link")
    assert info.value.suggested_filename == "mcp_usage.csv"
    assert "db=mcp" in info.value.url


def test_the_choice_is_remembered_across_a_reload(page, live_server):
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.choose_db("mcp")
    ap.wait_for_schema_table("mcp_calls")

    ap.navigate(live_server)
    assert ap.checked_db() == "mcp"
    assert "FROM mcp_calls" in ap.sql_input.input_value()


def run_preset(page, label):
    """Choose a preset and return the error its query came back with, or None.

    Read from the response itself: the table still shows the previous
    preset's result until this one lands, so the page alone cannot tell.
    """
    with page.expect_response(lambda r: r.url.endswith("/admin/dbviewer")) as info:
        page.locator("#analytics-preset-select").select_option(label=label)
    return info.value.json()["error"]


def test_every_mcp_preset_runs_without_error(page, live_server):
    """The presets are SQL in a JS file; this is what checks they parse."""
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.choose_db("mcp")
    ap.wait_for_schema_table("mcp_calls")
    presets = ap.presets()
    assert len(presets) >= 8

    for label in presets:
        assert run_preset(page, label) is None, label


def test_every_grade_preset_runs_without_error(page, live_server):
    ap = AnalyticsPage(page)
    ap.navigate(live_server)
    ap.wait_for_query_complete()
    for label in ap.presets():
        assert run_preset(page, label) is None, label
