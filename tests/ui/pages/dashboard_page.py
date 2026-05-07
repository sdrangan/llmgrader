"""Page Object Model for the Dashboard view."""

from playwright.sync_api import Page


class DashboardPage:
    def __init__(self, page: Page):
        self._page = page
        self.view = page.locator("#dashboard-view")
        self.table_body = page.locator("#dashboard-table-body")
        self.total_all_points = page.locator("#total-all-points")
        self.total_required_points = page.locator("#total-required-points")
        self.unit_select = page.locator("#unit-select")

    def navigate(self, base_url: str, timeout: int = 8_000) -> None:
        self._page.goto(base_url)
        self._page.evaluate("window.loadView('dashboard')")
        self.view.wait_for(state="visible", timeout=timeout)
