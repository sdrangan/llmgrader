"""The grade endpoint rejects models the server cannot grade with."""

from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.services.models import DEFAULT_MODEL


@pytest.fixture()
def pkg_dir(tmp_path: Path) -> Path:
    pkg = tmp_path / "soln_pkg"
    pkg.mkdir()
    (pkg / "llmgrader_config.xml").write_text(
        (
            "<llmgrader>"
            "<course><name>Fixture Course</name><term>Fall 2026</term></course>"
            "<units><section>Empty Section</section></units>"
            "</llmgrader>"
        ),
        encoding="utf-8",
    )
    return pkg


@pytest.fixture()
def flask_test_client(tmp_path: Path, pkg_dir: Path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    app = create_app(scratch_dir=str(scratch), soln_pkg=str(pkg_dir))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _post(client, **overrides):
    body = {"unit": "unit1", "qtag": "q1", "student_solution": "42"}
    body.update(overrides)
    return client.post("/grade", json=body)


def test_unknown_model_is_rejected_with_400(flask_test_client) -> None:
    resp = _post(flask_test_client, model="gpt-9000-imaginary")

    assert resp.status_code == 400
    error = resp.get_json()["error"]
    assert "gpt-9000-imaginary" in error
    # The message has to name what the student can pick instead.
    assert DEFAULT_MODEL in error


def test_a_registered_model_gets_past_the_model_check(flask_test_client) -> None:
    """It fails later on the fixture's missing unit, not on the model."""
    resp = _post(flask_test_client, model=DEFAULT_MODEL)

    assert resp.status_code == 400
    assert "Unknown unit" in resp.get_json()["error"]


def test_a_retired_model_is_still_accepted(flask_test_client) -> None:
    """Stored preferred_model values keep working for one release."""
    resp = _post(flask_test_client, model="gpt-4.1-mini")

    assert "Unknown unit" in resp.get_json()["error"]


def test_omitting_the_model_falls_back_to_the_registry_default(flask_test_client) -> None:
    resp = _post(flask_test_client)

    assert "Unknown unit" in resp.get_json()["error"]
