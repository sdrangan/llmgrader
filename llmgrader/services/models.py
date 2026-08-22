"""Server-side registry of the LLM models the grader supports.

This module is the single source of truth for the model slate.  The front end
(``static/js/app.js``), the admin allow-list UI (``static/js/admin.js``) and the
grader all read from it, via ``GET /api/models`` or a direct import, so a model
is added or retired by editing this file alone.

Capability flags exist so the grader can build a request from data rather than
from string prefix checks.  ``supports_temperature`` is the one that currently
matters: the GPT-5.6 family rejects the parameter outright with
``400 Unsupported parameter: 'temperature' is not supported with this model``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


TIERS: tuple[str, ...] = ("cheap", "mid", "strong")


@dataclass(frozen=True)
class ModelSpec:
    """Everything the app needs to know about one model.

    Attributes
    ----------
    id: str
        Provider-native model id, sent on the wire verbatim.
    provider: str
        Dispatch key for the per-provider caller factory in the grader.
    label: str
        UI display name.
    tier: str
        One of :data:`TIERS` -- "cheap", "mid" or "strong".
    context_tokens: int
        Size of the context window.
    long_context_threshold: int | None
        Input-token count above which the provider bills the long-context
        rates below, or None when the model has a single rate pair.
    usd_per_mtok_in, usd_per_mtok_out: float
        Short-context price per one million input / output tokens.
    usd_per_mtok_in_long, usd_per_mtok_out_long: float | None
        Long-context price per one million tokens, or None when there is no
        long-context rate.  Stored separately so a project-grading cost report
        is not silently ~2x optimistic.
    supports_temperature: bool
        False when the model rejects the ``temperature`` parameter, in which
        case the grader omits the key entirely.
    supports_web_search: bool
        Whether the built-in ``web_search`` tool can be enabled.
    supports_images: bool
        Whether image content parts may be attached.
    notes: str
        USER-FACING one-line guidance rendered next to the model in the UI.
        Required, non-empty -- a blank one ships a bare model id to a student.
    tier_default: bool
        This model is the one its tier resolves to.  Exactly one live model
        per tier must set it; the registry refuses to import otherwise.  A
        retired model never sets it.
    offer_free: bool
        This model is offered on the shared community key by default.  It
        seeds `allowedModels` only when an admin has never configured one --
        a stored list always wins.  A retired model never sets it.
    """

    id: str
    provider: str
    label: str
    tier: str
    context_tokens: int
    long_context_threshold: int | None
    usd_per_mtok_in: float
    usd_per_mtok_out: float
    usd_per_mtok_in_long: float | None
    usd_per_mtok_out_long: float | None
    supports_temperature: bool
    supports_web_search: bool
    supports_images: bool
    notes: str
    tier_default: bool = False
    offer_free: bool = False


# The GPT-5.6 family (launched 2026-07-09) shares a context window, a knowledge
# cutoff and -- relevant here -- a refusal of the `temperature` parameter.
_GPT56_CONTEXT_TOKENS = 1_050_000

# OpenAI bills the higher rate pair once a request's input exceeds this many
# tokens.  Taken from the published rate table, not measured against the
# account.
_LONG_CONTEXT_THRESHOLD = 128_000


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "gpt-5.6-luna": ModelSpec(
        id="gpt-5.6-luna",
        provider="openai",
        label="GPT-5.6 Luna",
        tier="cheap",
        context_tokens=_GPT56_CONTEXT_TOKENS,
        long_context_threshold=_LONG_CONTEXT_THRESHOLD,
        usd_per_mtok_in=0.20,
        usd_per_mtok_out=1.20,
        usd_per_mtok_in_long=0.40,
        usd_per_mtok_out_long=1.80,
        supports_temperature=False,
        supports_web_search=True,
        supports_images=True,
        notes=(
            "Best for routine short-answer questions and single derivations "
            "— the cheapest at about $0.30 per 1,000 graded questions."
        ),
        tier_default=True,
        # The only model on the shared community key by default: terra and sol
        # cost 7x and 13x per graded question, which is not something to opt an
        # admin into by editing a registry.
        offer_free=True,
    ),
    "gpt-5.6-terra": ModelSpec(
        id="gpt-5.6-terra",
        provider="openai",
        label="GPT-5.6 Terra",
        tier="mid",
        context_tokens=_GPT56_CONTEXT_TOKENS,
        long_context_threshold=_LONG_CONTEXT_THRESHOLD,
        usd_per_mtok_in=2.00,
        usd_per_mtok_out=12.00,
        usd_per_mtok_in_long=4.00,
        usd_per_mtok_out_long=18.00,
        supports_temperature=False,
        supports_web_search=True,
        supports_images=True,
        notes=(
            "Best for multi-part derivations, proofs and short code — the "
            "fastest at ~2.2 s, about $2.21 per 1,000 graded questions."
        ),
        tier_default=True,
    ),
    "gpt-5.6-sol": ModelSpec(
        id="gpt-5.6-sol",
        provider="openai",
        label="GPT-5.6 Sol",
        tier="strong",
        context_tokens=_GPT56_CONTEXT_TOKENS,
        long_context_threshold=_LONG_CONTEXT_THRESHOLD,
        usd_per_mtok_in=4.00,
        usd_per_mtok_out=20.00,
        usd_per_mtok_in_long=8.00,
        usd_per_mtok_out_long=30.00,
        supports_temperature=False,
        supports_web_search=True,
        supports_images=True,
        notes=(
            "Best for projects and reports needing long context or web search "
            "— the most capable, about $3.89 per 1,000 graded questions."
        ),
        tier_default=True,
    ),
}

def _tier_default(tier: str) -> ModelSpec:
    """Return the model declared as ``tier``'s default.

    Raises
    ------
    ValueError
        If the tier has no live model, or does not have exactly one marked
        ``tier_default``.  A registry that cannot say which model a tier means
        should fail at startup rather than serve whichever entry happens to be
        listed first.
    """
    candidates = [spec for spec in MODEL_REGISTRY.values() if spec.tier == tier]
    if not candidates:
        raise ValueError(f"No model registered for tier {tier!r}")

    defaults = [spec for spec in candidates if spec.tier_default]
    if len(defaults) != 1:
        raise ValueError(
            f"Tier {tier!r} must have exactly one model with tier_default=True; "
            f"found {len(defaults)}: {[spec.id for spec in defaults]}"
        )
    return defaults[0]


def _validate_tier_defaults() -> None:
    """Every tier is populated and names exactly one default. Import-time."""
    for tier in TIERS:
        _tier_default(tier)


_validate_tier_defaults()

#: The cheap-tier default, used when no model is requested.
DEFAULT_MODEL = _tier_default("cheap").id

#: The strong-tier default, used for project and report grading.
DEFAULT_PROJECT_MODEL = _tier_default("strong").id


# ---------------------------------------------------------------------------
#  Retired models
# ---------------------------------------------------------------------------
#
# These ids stay resolvable for one release: stored `preferred_model` values in
# existing course XML and saved admin `allowedModels` lists reference them, and
# several server-side defaults still hard-code `gpt-4.1-mini`.  They are NOT
# offered in the UI -- `/api/models` serves MODEL_REGISTRY only.
#
# Each keeps its own spec rather than borrowing its replacement's, because the
# spec describes the model actually put on the wire.  Getting this wrong is the
# bug this registry exists to prevent: resolving `gpt-4.1-mini` to the luna
# spec would drop `temperature: 0` from every request still using the old
# default and silently make grading non-deterministic.
#
# The replacement tiers deliberately map nothing up to `gpt-5.6-sol`: at
# $4/$20 it is several times the cost of the models being retired, and an
# automatic upgrade onto the shared community key is the wrong default.

DEPRECATED_MODEL_ALIASES: dict[str, str] = {
    "gpt-4.1-mini": "gpt-5.6-luna",
    "gpt-5-mini": "gpt-5.6-luna",
    "gpt-5.1": "gpt-5.6-terra",
    "gpt-5.2": "gpt-5.6-terra",
    "gpt-5.4": "gpt-5.6-terra",
    "gpt-5.4-mini": "gpt-5.6-luna",
    "gpt-5.4-nano": "gpt-5.6-luna",
}


def _retired(
    model_id: str,
    label: str,
    context_tokens: int,
    usd_per_mtok_in: float,
    usd_per_mtok_out: float,
    *,
    supports_temperature: bool = True,
    usd_per_mtok_in_long: float | None = None,
    usd_per_mtok_out_long: float | None = None,
    long_context_threshold: int | None = None,
) -> ModelSpec:
    """Build the spec for a retired model kept resolvable for one release."""
    replacement = MODEL_REGISTRY[DEPRECATED_MODEL_ALIASES[model_id]]
    return ModelSpec(
        id=model_id,
        provider="openai",
        label=f"{label} (retired)",
        tier=replacement.tier,
        context_tokens=context_tokens,
        long_context_threshold=long_context_threshold,
        usd_per_mtok_in=usd_per_mtok_in,
        usd_per_mtok_out=usd_per_mtok_out,
        usd_per_mtok_in_long=usd_per_mtok_in_long,
        usd_per_mtok_out_long=usd_per_mtok_out_long,
        supports_temperature=supports_temperature,
        supports_web_search=True,
        supports_images=True,
        # A retired model is never a tier default and is never offered on the
        # shared key: it stays resolvable, nothing more.
        tier_default=False,
        offer_free=False,
        notes=(
            f"Retired — {label} is no longer offered. "
            f"Use {replacement.label} instead."
        ),
    )


DEPRECATED_MODEL_REGISTRY: dict[str, ModelSpec] = {
    "gpt-4.1-mini": _retired("gpt-4.1-mini", "GPT-4.1 Mini", 1_047_576, 0.40, 1.60),
    # gpt-5-mini accepts `temperature` only at its default value of 1, which is
    # what the `startswith("gpt-5-mini")` hack this registry replaces was
    # working around.  Omitting the key yields exactly that default, so False
    # is both the accurate flag and byte-for-byte the old behaviour.
    "gpt-5-mini": _retired(
        "gpt-5-mini", "GPT-5 Mini", 400_000, 0.25, 2.00, supports_temperature=False
    ),
    "gpt-5.1": _retired("gpt-5.1", "GPT-5.1", 272_000, 1.25, 10.00),
    "gpt-5.2": _retired("gpt-5.2", "GPT-5.2", 272_000, 1.75, 12.00),
    "gpt-5.4": _retired(
        "gpt-5.4",
        "GPT-5.4",
        272_000,
        2.50,
        15.00,
        usd_per_mtok_in_long=5.00,
        usd_per_mtok_out_long=22.50,
        long_context_threshold=_LONG_CONTEXT_THRESHOLD,
    ),
    "gpt-5.4-mini": _retired("gpt-5.4-mini", "GPT-5.4 Mini", 272_000, 0.75, 4.50),
    "gpt-5.4-nano": _retired("gpt-5.4-nano", "GPT-5.4 Nano", 272_000, 0.20, 1.20),
}


def _validate_retired_flags() -> None:
    """No retired model may be a tier default or an offer-free model."""
    for spec in DEPRECATED_MODEL_REGISTRY.values():
        if spec.tier_default or spec.offer_free:
            raise ValueError(
                f"Retired model {spec.id!r} must have tier_default and "
                f"offer_free both False"
            )


_validate_retired_flags()


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def get_spec(model_id: str | None) -> ModelSpec | None:
    """Return the :class:`ModelSpec` for ``model_id``, or None if unknown.

    Retired ids still resolve, to the spec describing the retired model itself
    -- not to its replacement's spec -- and log a deprecation warning naming
    the model that should be used instead.
    """
    if not model_id:
        return None

    spec = MODEL_REGISTRY.get(model_id)
    if spec is not None:
        return spec

    spec = DEPRECATED_MODEL_REGISTRY.get(model_id)
    if spec is not None:
        logger.warning(
            "Model '%s' is deprecated and will be removed in a future release; "
            "use '%s' instead.",
            model_id,
            DEPRECATED_MODEL_ALIASES[model_id],
        )
        return spec

    return None


def default_for_tier(tier: str) -> ModelSpec:
    """Return the live model declared as ``tier``'s default.

    Selection is by the ``tier_default`` flag, not by position in the
    registry.

    Raises
    ------
    ValueError
        If the tier has no live model or no single declared default.
    """
    return _tier_default(tier)


def is_supported(model_id: str | None) -> bool:
    """Whether ``model_id`` can be graded with, retired ids included."""
    return get_spec(model_id) is not None


def sorted_specs() -> list[ModelSpec]:
    """Live registry entries ordered cheap -> mid -> strong, for the UI."""
    return sorted(MODEL_REGISTRY.values(), key=lambda spec: TIERS.index(spec.tier))


def migrate_allowed_models(allowed_models) -> list[str]:
    """Map a stored admin allow-list onto live model ids.

    A saved ``allowedModels`` list names the models the shared community key
    may be used with.  After a slate refresh those ids are retired, and since
    the gate is an exact-match test the community key would reject every model
    the UI can still offer -- with an error telling the student to pick another
    one, which is impossible.  So retired ids are mapped through
    :data:`DEPRECATED_MODEL_ALIASES`, unresolvable ids are dropped, and the
    result is de-duplicated with order preserved.

    An empty list stays empty: that is a deliberate "community key disabled"
    state, not a list waiting to be populated.
    """
    if not allowed_models:
        return []

    migrated: list[str] = []
    for model_id in allowed_models:
        if not isinstance(model_id, str):
            continue
        resolved = model_id if model_id in MODEL_REGISTRY else DEPRECATED_MODEL_ALIASES.get(model_id)
        if resolved and resolved not in migrated:
            migrated.append(resolved)

    if migrated != list(allowed_models):
        logger.info(
            "Migrated admin allowedModels %s -> %s", list(allowed_models), migrated
        )
    return migrated
