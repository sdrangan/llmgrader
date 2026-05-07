"""Shared fixtures for the UI E2E test suite.

Two-layer mocking strategy (no real LLM calls):
  Layer 1 — Python level: `llmgrader.services.grader.OpenAI` is patched so the
             Flask server never makes a network request to OpenAI.
  Layer 2 — Browser level: Playwright route interception is used in specific
             tests that need to simulate HTTP-level errors from the backend.
"""

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make `pages/` importable as `from pages.grader_page import GraderPage` in
# every test file under tests/ui/.
sys.path.insert(0, str(Path(__file__).parent))

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Canned LLM response: binary grading, "pass" result, 1 point awarded.
# This is what grader.py expects as output_text from the OpenAI Responses API.
# ---------------------------------------------------------------------------
MOCK_RAW_RESULT = json.dumps({
    "result": "pass",
    "full_explanation": "The student answered correctly. The answer 4 is correct.",
    "feedback": "Correct! 2 + 2 = 4.",
    "rubric_eval": {
        "correct_answer": {
            "evidence": "Student provided the answer 4.",
            "result": "pass",
        }
    },
})


def _make_fake_openai():
    """Build a mock OpenAI class whose responses.create() returns MOCK_RAW_RESULT."""

    class _FakeUsage:
        input_tokens = 50
        output_tokens = 30

    class _FakeResponse:
        output_text = MOCK_RAW_RESULT
        usage = _FakeUsage()
        output = []

    fake_client = MagicMock()
    fake_client.responses.create.return_value = _FakeResponse()

    fake_openai_class = MagicMock(return_value=fake_client)
    return fake_openai_class


# ---------------------------------------------------------------------------
# Session-scoped live server
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_server():
    """Start the Flask app in a background thread with a mocked OpenAI client.

    Yields the base URL string, e.g. "http://127.0.0.1:5099".
    The OpenAI patch remains active for the entire test session.
    """
    import os
    import tempfile

    fake_openai = _make_fake_openai()

    with (
        patch("llmgrader.services.grader.OpenAI", fake_openai),
        tempfile.TemporaryDirectory() as tmp,
    ):
        os.environ["LLMGRADER_AUTH_MODE"] = "dev-open"
        os.environ["LLMGRADER_STORAGE_PATH"] = tmp

        from llmgrader.app import create_app

        scratch = Path(tmp) / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)

        app = create_app(
            scratch_dir=str(scratch),
            soln_pkg=str(FIXTURE_DIR),
        )
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "ui-test-secret"

        port = 5099
        server_thread = threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False),
            daemon=True,
        )
        server_thread.start()

        # Brief pause to let the server bind
        time.sleep(0.8)

        yield f"http://127.0.0.1:{port}"

        # Daemon thread is cleaned up automatically when the process exits.


# ---------------------------------------------------------------------------
# Per-test browser page pre-configured for the grader
# ---------------------------------------------------------------------------

@pytest.fixture()
def grader_page(page, live_server):
    """Navigate to the grader and wait for the UI to be fully ready."""
    from pages.grader_page import GraderPage

    gp = GraderPage(page)
    gp.navigate(live_server)

    # Inject a dummy API key so gradeCurrentQuestion() doesn't abort early
    gp.set_api_key("test-key-ui")

    # Wait for the dynamic grade view and unit data to load
    gp.wait_for_grade_view()
    gp.wait_for_units_loaded()
    gp.wait_for_questions_loaded()

    return gp
