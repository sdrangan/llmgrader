"""Offline checks on the model registry.  No network, no API key."""

import logging

import pytest

from llmgrader.services.models import (
    DEFAULT_MODEL,
    DEFAULT_PROJECT_MODEL,
    DEPRECATED_MODEL_ALIASES,
    DEPRECATED_MODEL_REGISTRY,
    MODEL_REGISTRY,
    TIERS,
    ModelSpec,
    default_for_tier,
    get_spec,
    is_supported,
    sorted_specs,
)


def test_registry_is_not_empty() -> None:
    assert MODEL_REGISTRY


@pytest.mark.parametrize("model_id", sorted(MODEL_REGISTRY))
def test_entry_has_id_and_valid_tier(model_id: str) -> None:
    spec = MODEL_REGISTRY[model_id]
    assert isinstance(spec, ModelSpec)
    assert spec.id
    assert spec.tier in TIERS


@pytest.mark.parametrize("model_id", sorted(MODEL_REGISTRY))
def test_entry_has_user_facing_notes(model_id: str) -> None:
    """`notes` is guidance shown to a student, so a blank one is a bug."""
    assert MODEL_REGISTRY[model_id].notes.strip()


@pytest.mark.parametrize("model_id", sorted(MODEL_REGISTRY))
def test_map_key_equals_spec_id(model_id: str) -> None:
    assert MODEL_REGISTRY[model_id].id == model_id


def test_ids_are_unique() -> None:
    ids = [spec.id for spec in MODEL_REGISTRY.values()]
    assert len(ids) == len(set(ids))


def test_all_tiers_are_covered() -> None:
    assert {spec.tier for spec in MODEL_REGISTRY.values()} == set(TIERS)


def test_defaults_are_registered_with_expected_tiers() -> None:
    assert DEFAULT_MODEL in MODEL_REGISTRY
    assert DEFAULT_PROJECT_MODEL in MODEL_REGISTRY
    assert MODEL_REGISTRY[DEFAULT_MODEL].tier == "cheap"
    assert MODEL_REGISTRY[DEFAULT_PROJECT_MODEL].tier == "strong"


@pytest.mark.parametrize("model_id", sorted(MODEL_REGISTRY))
def test_long_context_rates_are_consistent(model_id: str) -> None:
    """Either both long rates and a threshold, or none of the three."""
    spec = MODEL_REGISTRY[model_id]
    long_fields = (
        spec.long_context_threshold,
        spec.usd_per_mtok_in_long,
        spec.usd_per_mtok_out_long,
    )
    assert all(f is None for f in long_fields) or all(f is not None for f in long_fields)
    if spec.usd_per_mtok_in_long is not None:
        assert spec.usd_per_mtok_in_long >= spec.usd_per_mtok_in
        assert spec.usd_per_mtok_out_long >= spec.usd_per_mtok_out


def test_sorted_specs_ramps_cheap_to_strong() -> None:
    assert [spec.tier for spec in sorted_specs()] == ["cheap", "mid", "strong"]
    assert {spec.id for spec in sorted_specs()} == set(MODEL_REGISTRY)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def test_get_spec_returns_the_live_entry() -> None:
    assert get_spec(DEFAULT_MODEL) is MODEL_REGISTRY[DEFAULT_MODEL]


@pytest.mark.parametrize("model_id", [None, "", "gpt-does-not-exist"])
def test_get_spec_returns_none_for_unknown_models(model_id) -> None:
    assert get_spec(model_id) is None
    assert not is_supported(model_id)


def test_default_for_tier_returns_a_live_model() -> None:
    for tier in TIERS:
        spec = default_for_tier(tier)
        assert spec.tier == tier
        assert spec.id in MODEL_REGISTRY


def test_default_for_tier_rejects_an_unknown_tier() -> None:
    with pytest.raises(ValueError):
        default_for_tier("titanium")


# ---------------------------------------------------------------------------
#  Retired models
# ---------------------------------------------------------------------------

def test_deprecated_aliases_resolve_to_live_registry_entries() -> None:
    assert DEPRECATED_MODEL_ALIASES
    for retired_id, replacement_id in DEPRECATED_MODEL_ALIASES.items():
        assert retired_id not in MODEL_REGISTRY
        assert replacement_id in MODEL_REGISTRY


def test_every_alias_has_a_spec_and_vice_versa() -> None:
    assert set(DEPRECATED_MODEL_ALIASES) == set(DEPRECATED_MODEL_REGISTRY)


@pytest.mark.parametrize("model_id", sorted(DEPRECATED_MODEL_ALIASES))
def test_retired_ids_still_resolve_to_their_own_spec(model_id: str) -> None:
    """The spec must describe the model put on the wire, not its replacement.

    Resolving a retired id to its replacement's spec would apply the wrong
    capability flags to a request that still names the retired model.
    """
    spec = get_spec(model_id)
    assert spec is not None
    assert spec.id == model_id
    assert spec.tier in TIERS
    assert spec.notes.strip()
    assert is_supported(model_id)


def test_retired_models_that_accept_temperature_keep_the_flag_set() -> None:
    """Dropping `temperature: 0` here would silently de-tune old grading runs.

    `gpt-5-mini` is the exception: it accepts the parameter only at its default
    value of 1, so omitting the key reproduces exactly what it used to be sent.
    """
    for model_id in DEPRECATED_MODEL_ALIASES:
        expected = model_id != "gpt-5-mini"
        assert get_spec(model_id).supports_temperature is expected


def test_using_a_retired_id_logs_a_deprecation_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="llmgrader.services.models"):
        get_spec("gpt-4.1-mini")
    messages = [record.getMessage() for record in caplog.records]
    assert any("gpt-4.1-mini" in m and "gpt-5.6-luna" in m for m in messages)


def test_live_models_do_not_log_a_deprecation_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="llmgrader.services.models"):
        get_spec(DEFAULT_MODEL)
    assert not caplog.records
