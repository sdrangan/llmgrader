"""Page Object Model for the Analytics / Database Viewer."""

from playwright.sync_api import Page

from .view_ready import switch_to_view


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
        switch_to_view(self._page, "analytics", timeout=timeout)
        self.view.wait_for(state="visible", timeout=timeout)
        self.wait_for_default_query(timeout=timeout)

    def wait_for_default_query(self, timeout: int = 8_000) -> None:
        """Wait until the SQL box has actually been pre-filled.

        The view becoming visible and the default query being written into the
        box are two separate steps, so reading ``input_value()`` straight after
        ``navigate`` can catch an empty box.  That is a race rather than a slow
        machine, which is why it shows up as an occasional failure in a full
        run and never when the test is run alone -- and why a longer timeout on
        the caller's side does not fix it.
        """
        self._page.wait_for_function(
            "(document.getElementById('analytics-sql-input')?.value || '').trim().length > 0",
            timeout=timeout,
        )

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
