"""The stored admin allow-list must survive a model-slate refresh.

Production's `admin-config.json` carries `allowedModels: ["gpt-4.1-mini"]`.
`/api/models` now serves only the GPT-5.6 slate, and the community-key gate is
an exact-match test, so without migration every model a student can select is
blocked -- and the rejection message tells them to pick another one, which is
impossible.
"""

import json
from pathlib import Path

import pytest

from llmgrader.services.grader import Grader
from llmgrader.services.models import (
    DEFAULT_MODEL,
    MODEL_REGISTRY,
    migrate_allowed_models,
)

ADMIN_KEY = "sk-community-key"


@pytest.fixture()
def grader(tmp_path: Path, monkeypatch) -> Grader:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(Grader, "load_unit_pkg", lambda self: None)
    return Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(tmp_path / "pkg"))


def _write_prefs(grader: Grader, allowed_models) -> None:
    Path(grader.get_admin_pref_path()).write_text(
        json.dumps(
            {
                "openaiApiKey": ADMIN_KEY,
                # Legacy key from the retired HF provider: still tolerated.
                "hfToken": "hf_legacy",
                "allowedModels": allowed_models,
                "tokenLimit": {"limit": 0, "period": "unlimited"},
            }
        ),
        encoding="utf-8",
    )


def test_production_allow_list_still_admits_the_default_model(grader: Grader) -> None:
    """The regression test for the outage this migration prevents."""
    _write_prefs(grader, ["gpt-4.1-mini"])

    admin_key, reason = grader.get_admin_key("gpt-5.6-luna")

    assert admin_key == ADMIN_KEY, reason
    assert reason is None


def test_production_allow_list_migrates_to_the_cheap_tier_only(grader: Grader) -> None:
    """gpt-4.1-mini maps to luna, so terra and sol stay off the shared key."""
    _write_prefs(grader, ["gpt-4.1-mini"])

    assert grader.load_admin_preferences()["allowedModels"] == ["gpt-5.6-luna"]

    for blocked in ("gpt-5.6-terra", "gpt-5.6-sol"):
        admin_key, reason = grader.get_admin_key(blocked)
        assert admin_key is None
        assert reason


def test_an_empty_allow_list_stays_empty(grader: Grader) -> None:
    """Empty means the community key is disabled -- do not helpfully fill it."""
    _write_prefs(grader, [])

    assert grader.load_admin_preferences()["allowedModels"] == []

    admin_key, reason = grader.get_admin_key(DEFAULT_MODEL)
    assert admin_key is None
    assert reason


def test_current_ids_are_left_untouched(grader: Grader) -> None:
    _write_prefs(grader, ["gpt-5.6-luna", "gpt-5.6-sol"])

    assert grader.load_admin_preferences()["allowedModels"] == [
        "gpt-5.6-luna",
        "gpt-5.6-sol",
    ]


def test_missing_key_is_treated_as_disabled(grader: Grader) -> None:
    Path(grader.get_admin_pref_path()).write_text(
        json.dumps({"openaiApiKey": ADMIN_KEY}), encoding="utf-8"
    )

    assert grader.load_admin_preferences()["allowedModels"] == []


# ---------------------------------------------------------------------------
#  migrate_allowed_models
# ---------------------------------------------------------------------------

def test_retired_ids_map_to_their_replacements() -> None:
    assert migrate_allowed_models(["gpt-4.1-mini"]) == ["gpt-5.6-luna"]
    assert migrate_allowed_models(["gpt-5.4"]) == ["gpt-5.6-terra"]


def test_duplicates_collapse_with_order_preserved() -> None:
    assert migrate_allowed_models(
        ["gpt-5.6-sol", "gpt-5.4-mini", "gpt-4.1-mini", "gpt-5.6-sol"]
    ) == ["gpt-5.6-sol", "gpt-5.6-luna"]


def test_unresolvable_entries_are_dropped() -> None:
    assert migrate_allowed_models(["not-a-model", 17, None]) == []
    assert migrate_allowed_models(["not-a-model", "gpt-5.6-luna"]) == ["gpt-5.6-luna"]


def test_nothing_is_migrated_up_to_the_expensive_tier() -> None:
    """A retired model must never become a $4/$20 one on the shared key."""
    strong = [spec.id for spec in MODEL_REGISTRY.values() if spec.tier == "strong"]

    for retired in ("gpt-4.1-mini", "gpt-5-mini", "gpt-5.1", "gpt-5.2",
                    "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"):
        assert migrate_allowed_models([retired])[0] not in strong
