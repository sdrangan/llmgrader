"""The registry declares its own defaults rather than relying on list order."""

import dataclasses

import pytest

from llmgrader.services import models
from llmgrader.services.models import (
    DEFAULT_MODEL_COMPLEX,
    DEFAULT_MODEL_SIMPLE,
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
    assert DEFAULT_MODEL_SIMPLE == default_for_tier("simple").id
    assert DEFAULT_MODEL_COMPLEX == default_for_tier("complex").id
    assert MODEL_REGISTRY[DEFAULT_MODEL_SIMPLE].tier_default
    assert MODEL_REGISTRY[DEFAULT_MODEL_COMPLEX].tier_default


def test_default_for_tier_ignores_registry_order(monkeypatch) -> None:
    """The declaration wins, not whichever entry is listed first."""
    standard = default_for_tier("standard")
    decoy = dataclasses.replace(standard, id="decoy-standard", tier_default=False)

    monkeypatch.setattr(
        models, "MODEL_REGISTRY", {"decoy-standard": decoy, **MODEL_REGISTRY}
    )

    assert models.default_for_tier("standard").id == standard.id


def test_a_tier_with_no_declared_default_raises(monkeypatch) -> None:
    stripped = {
        model_id: dataclasses.replace(spec, tier_default=False)
        for model_id, spec in MODEL_REGISTRY.items()
    }
    monkeypatch.setattr(models, "MODEL_REGISTRY", stripped)

    with pytest.raises(ValueError, match="exactly one"):
        models.default_for_tier("simple")


def test_a_tier_with_two_declared_defaults_raises(monkeypatch) -> None:
    simple = default_for_tier("simple")
    twin = dataclasses.replace(simple, id="twin-simple")
    monkeypatch.setattr(models, "MODEL_REGISTRY", {**MODEL_REGISTRY, "twin-simple": twin})

    with pytest.raises(ValueError, match="exactly one"):
        models.default_for_tier("simple")


def test_an_empty_tier_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        models,
        "MODEL_REGISTRY",
        {k: v for k, v in MODEL_REGISTRY.items() if v.tier != "complex"},
    )

    with pytest.raises(ValueError, match="No model registered for tier"):
        models.default_for_tier("complex")


# ---------------------------------------------------------------------------
#  offer_free
# ---------------------------------------------------------------------------

def test_only_the_simple_default_is_offered_free() -> None:
    """A $4/$20 model must not land on the shared key by default."""
    offered = [spec.id for spec in MODEL_REGISTRY.values() if spec.offer_free]

    assert offered == [DEFAULT_MODEL_SIMPLE]
    assert MODEL_REGISTRY[offered[0]].tier == "simple"


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
