"""Tests for the /unit/<name> and /unit/<name>/<qtag>/solution routes.

Verifies that reference solution data is stripped from the public endpoint and
only accessible to admins via the dedicated solution endpoint.
"""

import pytest
from pathlib import Path

from llmgrader.app import create_app
from llmgrader.services.grader import Grader


FAKE_UNITS = {
    "unit1": {
        "q1": {
            "qtag": "q1",
            "question_text": "<p>What is 2+2?</p>",
            "solution": "<p>The answer is 4.</p>",
            "solution_images": ["data:image/png;base64,abc123"],
            "grading_notes": "Award full credit for 4.",
            "parts": [],
            "required": True,
            "partial_credit": False,
            "tools": [],
            "rubrics": {},
            "rubric_total": None,
            "rubric_groups": [],
            "preferred_model": None,
        }
    }
}


@pytest.fixture()
def app_with_units(tmp_path: Path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret")

    def fake_load_unit_pkg(self):
        self.units = FAKE_UNITS
        self.units_order = [{"type": "unit", "name": "unit1"}]
        self.unit_validation_alert = None

    monkeypatch.setattr(Grader, "load_unit_pkg", fake_load_unit_pkg)

    app = create_app(scratch_dir=str(scratch), soln_pkg=None)
    app.config["TESTING"] = True
    return app


def test_unit_endpoint_strips_solution_fields(app_with_units):
    with app_with_units.test_client() as client:
        resp = client.get("/unit/unit1")
        assert resp.status_code == 200
        data = resp.get_json()
        q = data["items"]["q1"]
        assert "solution" not in q
        assert "solution_images" not in q
        assert "grading_notes" not in q


def test_unit_endpoint_preserves_non_sensitive_fields(app_with_units):
    with app_with_units.test_client() as client:
        resp = client.get("/unit/unit1")
        assert resp.status_code == 200
        data = resp.get_json()
        q = data["items"]["q1"]
        assert q["question_text"] == "<p>What is 2+2?</p>"
        assert q["required"] is True
        assert q["partial_credit"] is False
        assert q["tools"] == []


def test_solution_endpoint_requires_admin(app_with_units, monkeypatch):
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "normal")
    with app_with_units.test_client() as client:
        resp = client.get("/unit/unit1/q1/solution")
        assert resp.status_code == 403


def test_solution_endpoint_returns_data_for_admin(app_with_units, monkeypatch):
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    with app_with_units.test_client() as client:
        resp = client.get("/unit/unit1/q1/solution")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["solution"] == "<p>The answer is 4.</p>"
        assert data["solution_images"] == ["data:image/png;base64,abc123"]
        assert data["grading_notes"] == "Award full credit for 4."


def test_solution_endpoint_returns_404_for_unknown_unit(app_with_units, monkeypatch):
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    with app_with_units.test_client() as client:
        resp = client.get("/unit/nonexistent/q1/solution")
        assert resp.status_code == 404


def test_solution_endpoint_returns_404_for_unknown_qtag(app_with_units, monkeypatch):
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    with app_with_units.test_client() as client:
        resp = client.get("/unit/unit1/nonexistent/solution")
        assert resp.status_code == 404
