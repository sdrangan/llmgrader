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

    # --- The database choice (plans/mcp_usage.md, decision 8) ---------------

    def open_menu(self) -> None:
        self._page.locator("#analytics-menu-group .menu-button").hover()
        self._page.wait_for_selector("#analytics-db-grade-item", state="visible", timeout=5_000)

    def choose_db(self, db: str) -> None:
        """Pick Grade DB or MCP DB from the Analytics menu."""
        self.open_menu()
        self._page.click(f"#analytics-db-{db}-item")

    def checked_db(self) -> str:
        return self._page.locator(".analytics-db-item[aria-checked='true']").get_attribute("data-db")

    def db_name(self) -> str:
        return self._page.locator("#analytics-db-name").inner_text().strip()

    def schema_tables(self) -> list[str]:
        """Table names in the column reference, once it has loaded."""
        self._page.wait_for_selector("#analytics-schema-body .schema-table-name", timeout=8_000)
        names = self._page.locator("#analytics-schema-body .schema-table-name").all_inner_texts()
        return [name.lstrip("▸▾ ").strip() for name in names]

    def wait_for_schema_table(self, name: str, timeout: int = 8_000) -> None:
        self._page.wait_for_function(
            "name => Array.from(document.querySelectorAll('#analytics-schema-body .schema-table-name'))"
            ".some(b => b.textContent.replace(/^[▸▾]\s*/, '').trim() === name)",
            arg=name, timeout=timeout,
        )

    def result_rows(self) -> int:
        return self.results_table.locator("tbody tr").count()

    def presets(self) -> list[str]:
        return self._page.locator("#analytics-preset-select option").all_inner_texts()[1:]
