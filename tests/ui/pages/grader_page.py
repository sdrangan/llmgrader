"""Page Object Model for the LLM Grader UI."""

from playwright.sync_api import Page, expect


class GraderPage:
    """Encapsulates all selectors and interactions for the grader view.

    Element IDs sourced from:
      - llmgrader/templates/index.html  (top-level shell)
      - llmgrader/static/views/grade.html  (dynamically injected grade view)
    """

    def __init__(self, page: Page):
        self._page = page

        # Top-level controls (always present once index.html loads)
        self.unit_select = page.locator("#unit-select")
        self.question_select = page.locator("#question-number")
        self.part_select = page.locator("#part-select")

        # Grade view elements (injected dynamically by loadView("grade"))
        self.student_solution = page.locator("#student-solution")
        self.grade_button = page.locator("#grade-button")
        self.grade_live_status = page.locator("#grade-live-status")

        # Result display elements
        self.grade_status = page.locator("#grade-status")
        self.grade_points = page.locator("#grade-points")
        self.feedback_box = page.locator("#feedback-box")
        self.full_explanation_box = page.locator("#full-explanation-box")

    def navigate(self, base_url: str) -> None:
        self._page.goto(base_url)

    def set_api_key(self, key: str = "test-api-key") -> None:
        """Inject a dummy API key into localStorage so gradeCurrentQuestion() proceeds."""
        self._page.evaluate(
            f"localStorage.setItem('openai_api_key', '{key}')"
        )

    def wait_for_grade_view(self, timeout: int = 10_000) -> None:
        """Wait until the dynamically loaded grade view is ready.

        On mobile viewports the composer lives inside a tab panel that starts
        hidden.  We click the Solution tab so grade_button / student_solution
        become visible, matching the normal user flow.
        """
        self.grade_button.wait_for(state="attached", timeout=timeout)
        mobile_solution_tab = self._page.locator(
            ".mobile-tabs button[data-panel='solution']"
        )
        if mobile_solution_tab.is_visible():
            mobile_solution_tab.click()
        self.grade_button.wait_for(state="visible", timeout=timeout)
        self.student_solution.wait_for(state="visible", timeout=timeout)

    def wait_for_units_loaded(self, timeout: int = 10_000) -> None:
        """Wait until the unit dropdown has at least one selectable option."""
        self._page.wait_for_function(
            "document.getElementById('unit-select') && "
            "document.getElementById('unit-select').options.length > 0",
            timeout=timeout,
        )

    def wait_for_questions_loaded(self, timeout: int = 10_000) -> None:
        """Wait until the question dropdown has at least one option."""
        self._page.wait_for_function(
            "document.getElementById('question-number') && "
            "document.getElementById('question-number').options.length > 0",
            timeout=timeout,
        )

    def submit_answer(self, answer: str) -> None:
        """Fill in the student answer and click Grade."""
        self.student_solution.fill(answer)
        self.grade_button.click()

    def wait_for_result(self, timeout: int = 15_000) -> None:
        """Wait until the live-status indicates grading finished."""
        self._page.wait_for_function(
            "document.getElementById('grade-live-status') && "
            "(document.getElementById('grade-live-status').textContent.startsWith('Done in') || "
            " document.getElementById('grade-live-status').textContent.includes('failed') || "
            " document.getElementById('grade-live-status').textContent.includes('Grading failed'))",
            timeout=timeout,
        )

    def get_feedback_text(self) -> str:
        return self.feedback_box.inner_text()

    def get_grade_status_text(self) -> str:
        return self.grade_status.inner_text()

    def get_grade_points_text(self) -> str:
        return self.grade_points.inner_text()

    def is_grade_button_enabled(self) -> bool:
        return not self.grade_button.is_disabled()
