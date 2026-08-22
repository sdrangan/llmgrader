"""The registry declares its own defaults rather than relying on list order."""

import dataclasses

import pytest

from llmgrader.services import models
from llmgrader.services.models import (
    DEFAULT_MODEL,
    DEFAULT_PROJECT_MODEL,
    DEPRECATED_MODEL_REGISTRY,
    MODEL_REGISTRY,
    TIERS,
    default_for_tier,
)


def test_exactly_one_tier_default_per_tier() -> None:
    for tier in TIERS:
        defaults = [
            spec.id
            for spec in MODEL_REGISTRY.values()
            if spec.tier == tier and spec.tier_default
        ]
        assert len(defaults) == 1, f"tier {tier!r} declares {defaults}"


def test_every_tier_is_populated() -> None:
    for tier in TIERS:
        assert default_for_tier(tier).tier == tier


def test_defaults_are_derived_from_the_flags() -> None:
    assert DEFAULT_MODEL == default_for_tier("cheap").id
    assert DEFAULT_PROJECT_MODEL == default_for_tier("strong").id
    assert MODEL_REGISTRY[DEFAULT_MODEL].tier_default
    assert MODEL_REGISTRY[DEFAULT_PROJECT_MODEL].tier_default


def test_default_for_tier_ignores_registry_order(monkeypatch) -> None:
    """The declaration wins, not whichever entry is listed first."""
    mid = default_for_tier("mid")
    decoy = dataclasses.replace(mid, id="decoy-mid", tier_default=False)

    monkeypatch.setattr(
        models, "MODEL_REGISTRY", {"decoy-mid": decoy, **MODEL_REGISTRY}
    )

    assert models.default_for_tier("mid").id == mid.id


def test_a_tier_with_no_declared_default_raises(monkeypatch) -> None:
    stripped = {
        model_id: dataclasses.replace(spec, tier_default=False)
        for model_id, spec in MODEL_REGISTRY.items()
    }
    monkeypatch.setattr(models, "MODEL_REGISTRY", stripped)

    with pytest.raises(ValueError, match="exactly one"):
        models.default_for_tier("cheap")


def test_a_tier_with_two_declared_defaults_raises(monkeypatch) -> None:
    cheap = default_for_tier("cheap")
    twin = dataclasses.replace(cheap, id="twin-cheap")
    monkeypatch.setattr(models, "MODEL_REGISTRY", {**MODEL_REGISTRY, "twin-cheap": twin})

    with pytest.raises(ValueError, match="exactly one"):
        models.default_for_tier("cheap")


def test_an_empty_tier_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        models,
        "MODEL_REGISTRY",
        {k: v for k, v in MODEL_REGISTRY.items() if v.tier != "strong"},
    )

    with pytest.raises(ValueError, match="No model registered for tier"):
        models.default_for_tier("strong")


# ---------------------------------------------------------------------------
#  offer_free
# ---------------------------------------------------------------------------

def test_only_the_cheap_default_is_offered_free() -> None:
    """A $4/$20 model must not land on the shared key by default."""
    offered = [spec.id for spec in MODEL_REGISTRY.values() if spec.offer_free]

    assert offered == [DEFAULT_MODEL]
    assert MODEL_REGISTRY[offered[0]].tier == "cheap"


def test_no_retired_model_is_a_default_or_offered_free() -> None:
    for spec in DEPRECATED_MODEL_REGISTRY.values():
        assert not spec.tier_default
        assert not spec.offer_free


def test_the_retired_flag_check_raises(monkeypatch) -> None:
    bad = dataclasses.replace(
        DEPRECATED_MODEL_REGISTRY["gpt-4.1-mini"], offer_free=True
    )
    monkeypatch.setattr(models, "DEPRECATED_MODEL_REGISTRY", {"gpt-4.1-mini": bad})

    with pytest.raises(ValueError, match="must have tier_default and offer_free"):
        models._validate_retired_flags()
