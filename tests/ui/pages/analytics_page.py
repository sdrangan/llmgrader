"""Page Object Model for the Analytics / Database Viewer."""

from playwright.sync_api import Page


class AnalyticsPage:
    def __init__(self, page: Page):
        self._page = page
        self.view = page.locator("#analytics-view")
        self.sql_input = page.locator("#analytics-sql-input")
        self.run_button = page.locator("#analytics-run-btn")
        self.results_table = page.locator("#analytics-results-table")
        self.error_box = page.locator("#analytics-error")
        self.no_results_message = page.locator("#analytics-no-results")

    def navigate(self, base_url: str, timeout: int = 8_000) -> None:
        self._page.goto(base_url)
        self._page.evaluate("window.loadView('analytics')")
        self.view.wait_for(state="visible", timeout=timeout)

    def run_query(self, sql: str) -> None:
        self.sql_input.fill(sql)
        self.run_button.click()

    def wait_for_query_complete(self, timeout: int = 10_000) -> None:
        """Wait until the query produces any visible outcome.

        A successful query (even with 0 data rows) renders a header row in
        thead.  No-results or error are the other two terminal states.
        """
        self._page.wait_for_function(
            "document.getElementById('analytics-results-table')?.querySelector('thead tr') !== null || "
            "document.getElementById('analytics-no-results')?.style.display !== 'none' || "
            "document.getElementById('analytics-error')?.style.display !== 'none'",
            timeout=timeout,
        )

    def wait_for_error(self, timeout: int = 10_000) -> None:
        """Wait until the error box becomes visible."""
        self._page.wait_for_function(
            "document.getElementById('analytics-error')?.style.display !== 'none'",
            timeout=timeout,
        )
