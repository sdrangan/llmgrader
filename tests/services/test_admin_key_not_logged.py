"""The shared OpenAI key must never reach stdout/stderr.

On Render, stdout is the log stream, so a single stray print of the admin
preferences publishes the community key to anyone who can read the logs.
"""

import json
from pathlib import Path

import pytest

from llmgrader.services.grader import Grader, redact_secrets

SECRET_KEY = "sk-test-DO-NOT-LOG-abcdefghijklmnop"
SECRET_HF_TOKEN = "hf_test-DO-NOT-LOG-qrstuvwxyz"


@pytest.fixture()
def grader(tmp_path: Path, monkeypatch) -> Grader:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(Grader, "load_unit_pkg", lambda self: None)
    return Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(tmp_path / "pkg"))


def _write_prefs(grader: Grader, **overrides) -> None:
    prefs = {
        "openaiApiKey": SECRET_KEY,
        "hfToken": SECRET_HF_TOKEN,
        "allowedModels": ["gpt-5.6-luna"],
        "tokenLimit": {"limit": 0, "period": "unlimited"},
    }
    prefs.update(overrides)
    Path(grader.get_admin_pref_path()).write_text(json.dumps(prefs), encoding="utf-8")


def test_get_admin_key_never_prints_the_key(grader: Grader, capsys) -> None:
    _write_prefs(grader)

    admin_key, reason = grader.get_admin_key("gpt-5.6-luna")

    assert admin_key == SECRET_KEY, reason
    captured = capsys.readouterr()
    assert SECRET_KEY not in captured.out
    assert SECRET_KEY not in captured.err
    assert SECRET_HF_TOKEN not in captured.out
    assert SECRET_HF_TOKEN not in captured.err


def test_get_admin_key_never_prints_the_key_when_blocked(grader: Grader, capsys) -> None:
    """The rejection paths log too, and run before the key is returned."""
    _write_prefs(grader, allowedModels=[])

    admin_key, reason = grader.get_admin_key("gpt-5.6-luna")

    assert admin_key is None
    assert reason
    captured = capsys.readouterr()
    assert SECRET_KEY not in captured.out
    assert SECRET_KEY not in captured.err


def test_prefs_are_still_logged_for_debugging(grader: Grader, capsys) -> None:
    """Redacted, not deleted -- the non-secret fields stay useful in the log."""
    _write_prefs(grader)

    grader.get_admin_key("gpt-5.6-luna")

    out = capsys.readouterr().out
    assert "Admin preferences loaded" in out
    assert "gpt-5.6-luna" in out
    assert "unlimited" in out


def test_redact_secrets_masks_key_token_and_secret_names() -> None:
    redacted = redact_secrets(
        {
            "openaiApiKey": SECRET_KEY,
            "hfToken": SECRET_HF_TOKEN,
            "clientSecret": "shhh",
            "allowedModels": ["gpt-5.6-luna"],
            "tokenLimit": {"limit": 5, "period": "per_hour"},
            "nested": [{"apiKey": SECRET_KEY}],
        }
    )

    assert redacted["openaiApiKey"] == "[redacted]"
    assert redacted["hfToken"] == "[redacted]"
    assert redacted["clientSecret"] == "[redacted]"
    assert redacted["nested"] == [{"apiKey": "[redacted]"}]
    # Non-secret fields survive, including the one whose name matches by
    # accident.
    assert redacted["allowedModels"] == ["gpt-5.6-luna"]
    assert redacted["tokenLimit"] == {"limit": 5, "period": "per_hour"}


def test_redact_secrets_leaves_unset_values_alone() -> None:
    assert redact_secrets({"openaiApiKey": ""}) == {"openaiApiKey": ""}
