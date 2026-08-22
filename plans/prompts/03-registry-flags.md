Continue the plan in `plans/update_model.md`. Steps 0-7 are done and **merged to `main`, which is deployed to Render and serving**. Read the plan's "Implementation status" section, then `llmgrader/services/models.py` in full before changing anything.

This run is a refactor with one genuinely new feature. It has no user-visible benefit on its own — its purpose is that the *next* model refresh touches one file instead of many. Classes start in about a week.

**`main` is live.** Two things in this run sit on the path that decides whether a student can grade at all: the admin allow-list and model selection. A regression here is a production outage, not a failed test. Prefer stopping and asking over guessing.

## Background: three things are still hard-coded

1. `DEFAULT_MODEL` and `DEFAULT_PROJECT_MODEL` are string literals (`models.py:149` and `:152`) sitting apart from the registry entries they name. Nothing stops them naming a model that is not in `MODEL_REGISTRY`, and `default_for_tier()` currently returns whichever matching model is *listed first* — a positional accident, not a declaration.
2. There is no registry-side notion of which models the free community key should offer. That lives only in `admin-config.json`, which is why a stale `allowedModels` became a deploy blocker in the last run rather than something with a sane fallback.
3. `preferred_model` in course XML only accepts a concrete model id, so every model refresh means rewriting every course package — including ones in instructors' own repos that this project does not control.

## Discovery you must account for: `preferred_model` is currently inert

`unit_parser.py:1123` reads it and `:1248` puts it in the question dict. `parselatex.py:304` does the same for LaTeX sources. **Nothing consumes it.** Neither `routes/api.py` nor `Grader.grade()` consults it; the model is whatever the client sends from the dropdown.

So step C below is not "extend an existing feature" — it is wiring the attribute up for the first time. Treat the existing values in `example_repo/` and `llmgrader/mcp/examples/` as untested data that has never influenced a grade.

## Step A — declare defaults on the entries

Add to `ModelSpec`:

- `tier_default: bool` — this model is the one its tier resolves to.
- `offer_free: bool` — this model is offered on the shared community key by default.

Then:

- Derive `DEFAULT_MODEL` and `DEFAULT_PROJECT_MODEL` from the flags at import (cheap-tier default and strong-tier default respectively) instead of hard-coding the strings. Keep both names exported — plenty of modules import them.
- Rewrite `default_for_tier()` to select on `tier_default` rather than list order.
- Validate at import: **exactly one** `tier_default` per tier in `TIERS`, and every tier populated. Raise on violation — a registry that cannot say what its default is should fail loudly at startup, not serve a surprising model.
- Set `offer_free=True` on `gpt-5.6-luna` only. Terra and sol stay off by default; putting a $4/$20 model on a shared key by default is the risk §9 of the plan flags.

Retired models in `DEPRECATED_MODEL_REGISTRY` need the new fields too. Both flags must be `False` for every one of them — a retired model is never a tier default and is never offered free.

## Step B — make `offer_free` the fallback for the allow-list

`migrate_allowed_models()` currently starts `if not allowed_models: return []`, which treats "never configured" and "deliberately emptied" identically. Split them:

- `None` / key absent → seed from the registry: every live model with `offer_free=True`.
- `[]` (explicitly empty) → stays empty. This is a deliberate "community key disabled" state and must not be helpfully repopulated.
- A non-empty list → migrate through the alias map as it does today, unchanged.

An admin who narrowed the list must never have it silently re-widened by a later registry edit: a stored non-empty list always wins over `offer_free`.

Check both call sites — `Grader.load_admin_preferences` and `routes/api.py:757` — still behave correctly, and check what `get_default_admin_prefs()` puts in `allowedModels`, since that default is what decides whether a fresh install reads as "unset" or "disabled".

Test all three cases explicitly, plus the production-shaped one that already exists (`['gpt-4.1-mini']` → `['gpt-5.6-luna']`). That existing test must still pass untouched.

## Step C — symbolic `preferred_model`, and wire it up

**C1. Resolution.** Add `resolve_preferred_model(value) -> ModelSpec | None` to `models.py`. Accept, in order:

- a tier name — `"cheap"`, `"mid"`, `"strong"` → that tier's `tier_default`
- a concrete live model id → that model
- a retired id → its alias target, logging the deprecation as `get_spec` already does
- anything else, including empty/None → return `None` and log a warning naming the offending value and the question, so a typo in course XML is visible in the logs rather than silent

Use the tier names as the symbolic vocabulary — not `default_low`/`default_high`. `tier` already exists on every spec, `/api/models` already exposes it, and the UI already orders by it. A second vocabulary for the same concept would need translating in three places, and it cannot name the mid tier.

**C2. Wiring — this is new behavior, so keep it conservative.** `preferred_model` sets the *default selection* for that question; the student can still override it in the dropdown. It must not force or lock the model — a student using their own API key is entitled to pick a stronger one.

- Server: when a grade request arrives with no explicit `model`, fall back to the question's resolved `preferred_model`, then to `DEFAULT_MODEL`. Do not override a model the client sent explicitly.
- Client: when a question loads, if it carries a resolvable `preferred_model`, select it in the dropdown. The existing `sessionStorage` selection should not override a question's explicit preference — but re-selecting manually must still work and still persist.
- The question payload the front end already receives will need `preferred_model` included if it is not there yet. Check before adding.

Unresolvable values fall back to `DEFAULT_MODEL` and never raise into a student's grading request.

**C3.** `UnitParser` should warn — not error — when `preferred_model` resolves to nothing, per §3 of the plan. Keep `unit.xsd` as `xs:string`; do not enumerate models or tier names in the schema.

## Out of scope

- Do NOT update `example_repo/` or `llmgrader/mcp/examples/` XML to symbolic values. That is step 10, and it should happen after this lands so it is rewritten once.
- Do NOT create `tests/live/` or add the `live` marker. Step 8.
- Do NOT change which model is `DEFAULT_MODEL`. Step 9 gates that on real submissions.
- Do NOT add Gemini. Appendix A.
- Do NOT touch `.gitignore`, though note it is a Vivado template that ignores `*.xml` and `*.json` — if you create a new fixture with either extension, `git add` will silently skip it. Use `git add -f` and say so in your report.

## Verification

```bash
pytest --ignore=tests/ui/
```

All 163 existing tests must pass. Steps A and B are refactors of live-serving code — if an existing test needs editing, that is a signal you changed behavior, so stop and explain instead.

Then, because step C is new behavior on the grading path:

```bash
LLMGRADER_AUTH_MODE=dev-open python run.py &
sleep 3
curl -s http://127.0.0.1:5000/api/models
kill %1
```

`OPENAI_API_KEY` is set. Prove step C end to end with at most three real calls on `gpt-5.6-luna` (~$0.0003 each) through `Grader.grade`, using a temporary fixture unit — not by editing `example_repo/`:

1. a question with `preferred_model="strong"` resolves to `gpt-5.6-sol` when no model is sent
2. a question with `preferred_model="gpt-5.6-terra"` resolves to terra
3. an explicit client-sent model still wins over `preferred_model`

You may assert 1 and 3 without spending a call if you can inspect the resolved model before dispatch — prefer that, and spend calls only on what genuinely needs the wire.

## Git and reporting

Branch `feature/registry-flags` off `main`. Three logical commits, one per step. **Do NOT push and do NOT merge** — `main` auto-deploys, and the user pushes deliberately.

Update the "Implementation status" table in `plans/update_model.md`, and record the `preferred_model`-was-inert discovery in the plan body — it changes what step 10 has to do.

Report: files changed per step, the `allowedModels` behavior for all three input cases, how `preferred_model` resolution and precedence work now, test counts before and after, live-call results, and anything underspecified here. If a design question comes up that changes student-visible behavior, stop and ask.
