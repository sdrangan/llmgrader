"""Tests for the public GET /api/models endpoint."""

from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.services.models import (
    DEFAULT_MODEL_COMPLEX,
    DEFAULT_MODEL_SIMPLE,
    DEFAULT_MODEL_STANDARD,
    DEPRECATED_MODEL_ALIASES,
    MODEL_REGISTRY,
)


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


def test_returns_every_registry_entry(flask_test_client) -> None:
    payload = flask_test_client.get("/api/models").get_json()

    assert {m["id"] for m in payload["models"]} == set(MODEL_REGISTRY)
    for entry in payload["models"]:
        spec = MODEL_REGISTRY[entry["id"]]
        assert entry["label"] == spec.label
        assert entry["provider"] == spec.provider
        assert entry["tier"] == spec.tier
        assert entry["context_tokens"] == spec.context_tokens
        assert entry["notes"] == spec.notes


def test_reports_the_defaults(flask_test_client) -> None:
    payload = flask_test_client.get("/api/models").get_json()

    assert payload["default_model_simple"] == DEFAULT_MODEL_SIMPLE
    assert payload["default_model_standard"] == DEFAULT_MODEL_STANDARD
    assert payload["default_model_complex"] == DEFAULT_MODEL_COMPLEX


def test_options_are_ordered_simple_to_complex(flask_test_client) -> None:
    payload = flask_test_client.get("/api/models").get_json()

    assert [m["tier"] for m in payload["models"]] == ["simple", "standard", "complex"]


def test_every_entry_carries_guidance(flask_test_client) -> None:
    """The UI renders `notes`; a blank one shows a student a bare model id."""
    payload = flask_test_client.get("/api/models").get_json()

    assert all(m["notes"].strip() for m in payload["models"])


def test_retired_models_are_not_offered(flask_test_client) -> None:
    """They stay resolvable server-side, but must not appear in the picker."""
    payload = flask_test_client.get("/api/models").get_json()

    offered = {m["id"] for m in payload["models"]}
    assert offered.isdisjoint(DEPRECATED_MODEL_ALIASES)


def test_leaks_no_key_material(flask_test_client) -> None:
    resp = flask_test_client.get("/api/models")
    payload = resp.get_json()
    body = resp.get_data(as_text=True).lower()

    assert resp.status_code == 200
    # Whitelist the shape: nothing beyond these keys can ride along.
    assert set(payload) == {
        "models",
        "default_model_simple",
        "default_model_standard",
        "default_model_complex",
    }
    for entry in payload["models"]:
        assert set(entry) == {
            "id", "label", "provider", "tier", "context_tokens", "notes",
        }
    for forbidden in ("api_key", "apikey", "api key", "secret", "sk-", "bearer"):
        assert forbidden not in body
