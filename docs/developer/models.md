---
title: The model registry
parent: Developer Guide
nav_order: 3
has_children: false
---

# The Model Registry

`llmgrader/services/models.py` is the single source of truth for which models
the grader supports. The front end, the admin allow-list, the CLI tools and the
grader all read from it — through `GET /api/models` or a direct import — so a
model is added or retired by editing that one file.

## What a registry entry holds

Each entry is a frozen `ModelSpec`:

| Field | Why it exists |
|---|---|
| `id` | The provider-native id put on the wire, verbatim |
| `provider` | Dispatch key into `PROVIDER_CALLERS` in `grader.py` |
| `label`, `notes` | User-facing. `notes` is the one-line guidance shown next to the model in the UI, not an internal comment |
| `tier` | `simple`, `standard` or `complex` — the *difficulty of the problem*, not the price of the model |
| `context_tokens`, `long_context_threshold` | Window size, and where the provider switches to the long-context rates |
| `usd_per_mtok_*` | Both rate pairs, so a cost report is not ~2x optimistic on long inputs |
| `supports_temperature`, `supports_web_search`, `supports_images` | Capability flags, so the grader builds a request from data rather than from `startswith` checks on the model name |
| `tier_default` | Exactly one live model per tier sets this. The registry refuses to import otherwise |
| `offer_free` | Seeds the shared community key's allow-list, but only when an admin has never configured one |

## Tiers name difficulty, not price

`simple` / `standard` / `complex` describe how hard the graded question is.
Course authors pick a tier in `preferred_model`, and difficulty is the thing
they know about their own questions; how capable a model that requires is the
registry's problem. The price ramp happens to follow the difficulty ramp.

`DEFAULT_MODEL_SIMPLE`, `DEFAULT_MODEL_STANDARD` and `DEFAULT_MODEL_COMPLEX`
are derived from the `tier_default` flags — never hard-code a model id
anywhere else.

## How to add a model

1. **Check the id and the prices against the account**, not just the docs —
   entitlements differ per organisation:

   ```bash
   curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"
   ```

2. **Add the `ModelSpec`** to `MODEL_REGISTRY` in `llmgrader/services/models.py`.
   Fill in `notes`: it is shown to students, and a blank one ships a bare model
   id to somebody choosing between three options. If the new model is taking
   over a tier, move `tier_default=True` onto it and off the incumbent — two
   defaults in one tier is an import-time error, which is the point.

3. **Run the offline suite.** It checks the structural invariants: unique ids,
   every tier populated with exactly one default, every provider present in
   `PROVIDER_CALLERS`, no retired model marked as a default.

   ```bash
   pytest --ignore=tests/ui/
   ```

4. **Run the live suite.** This is the one that actually talks to the API, and
   the only thing that catches a wrong or retired model id — every mocked test
   passes against a model that does not exist. It is parametrized over
   `MODEL_REGISTRY`, so the new entry is covered automatically: reachability,
   response schema, a coarse correctness floor, and each capability flag it
   declares.

   ```bash
   LLMGRADER_RUN_LIVE_TESTS=1 OPENAI_API_KEY=... pytest tests/live -m live
   ```

   A full run costs about $0.08 and writes `tests/live/_report.json` with
   per-model tokens, latency and cost. That report is the evidence for the next
   slate decision — keep it.

5. **Update the docs**: the student-facing table in
   [OpenAI Keys](../student/openai.md) and the tier table in
   [Unit XML](../admin/buildcourse/unitxml.md).

## How to retire a model

Do **not** delete the entry outright. Stored `preferred_model` attributes in
course packages — including ones in instructors' own repositories — and saved
admin `allowedModels` lists will name it.

1. Remove it from `MODEL_REGISTRY` and add a `DEPRECATED_MODEL_ALIASES` entry
   pointing at its replacement, plus a `DEPRECATED_MODEL_REGISTRY` spec
   describing the retired model itself. The alias is what a *preference*
   resolves forward to; the spec is what `get_spec()` returns, because a spec
   must describe the model actually put on the wire — resolving a retired id to
   its replacement's spec would silently change capability flags on requests
   still using the old id.

2. Point the alias at a tier of comparable cost. Auto-upgrading a retired
   mid-priced model onto the most expensive tier bills the shared community key
   for a decision nobody made.

3. `migrate_allowed_models()` handles stored admin allow-lists on read, so no
   data migration is needed. An allow-list that was explicitly emptied stays
   empty; one that was never configured is seeded from `offer_free`.

## Validating a default change

Before changing which model a tier resolves to, replay real submissions rather
than trusting a fixture:

```bash
python tools/replay_submissions.py --dry-run   # reconstruct and price, no API calls
python tools/replay_submissions.py             # replay, then escalate disagreements
```

It re-grades stored submissions through the real `Grader.grade()` path and
reports where the new model disagrees with the recorded grade, escalating each
disagreement to the stronger tiers. Output lands in `local_data/replay/`, which
is gitignored — the submissions are real student work.

Read the result carefully: **the stored grade is not ground truth**, it is the
output of whichever model produced it. Where the stronger models side with the
new model against the stored grade, the evidence points at the old grade being
wrong, not the new model.
