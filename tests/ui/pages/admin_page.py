"""Page Object Model for the Admin view."""

from playwright.sync_api import Page


class AdminPage:
    def __init__(self, page: Page):
        self._page = page
        self.view = page.locator("#admin-view")
        self.unit_select = page.locator("#admin-unit-select")
        self.question_select = page.locator("#admin-question-select")
        self.mode_badge = page.locator("#admin-partial-credit-indicator")
        self.question_text = page.locator("#admin-question-text")
        self.solution_text = page.locator("#admin-solution-text")
        self.grading_notes = page.locator("#admin-grading-notes")

    def navigate(self, base_url: str, timeout: int = 8_000) -> None:
        self._page.goto(base_url)
        self._page.evaluate("window.loadView('admin')")
        self.view.wait_for(state="visible", timeout=timeout)

    def wait_for_units_loaded(self, timeout: int = 10_000) -> None:
        self._page.wait_for_function(
            "document.getElementById('admin-unit-select') && "
            "document.getElementById('admin-unit-select').options.length > 0",
            timeout=timeout,
        )

    def wait_for_questions_loaded(self, timeout: int = 10_000) -> None:
        self._page.wait_for_function(
            "document.getElementById('admin-question-select') && "
            "document.getElementById('admin-question-select').options.length > 0",
            timeout=timeout,
        )
