# Plan: Refresh the supported model slate

Status: **steps 0-8 merged to `main` and deployed**; the tier rename, step 9 (validation) and step 10 (docs) are done on `feature/docs-and-validation` (3 commits, unpushed). Plan complete apart from Appendix A.
Date: 2026-08-22
Scope: OpenAI only. Gemini support is deferred — see Appendix A.

## Implementation status

| Step | State |
|---|---|
| 0. Stop logging the shared API key | done — see below |
| 1. Verify IDs and pricing | done — §4 |
| 2. `services/models.py` + registry tests | done |
| 3. `supports_temperature` replaces the prefix hack | done, live-verified |
| 4. `GET /api/models` + JS wiring | done |
| 5. `PROVIDER_CALLERS` refactor | done, no behavior change |
| 6. Remove Hugging Face | done |
| 7. Defaults + unknown-model 400 + allow-list migration | done, live-verified |
| 8. `tests/live/` + marker | done — suite run live, §4 |
| 9. Run live suite, flip default | done — flip shipped in step 2; validated against 67 real submissions, §4 |
| 10. Docs + example XML | done — §7, plus the course-author section and `docs/developer/models.md` |
| A. `tier_default` / `offer_free` on the entries | done |
| B. `offer_free` seeds an unset allow-list | done |
| C. Symbolic `preferred_model`, wired up | done |
| D. Tier vocabulary renamed to difficulty | done — §3 |
| E. `.gitignore` no longer ignores project XML/JSON | done |

Test suite: 94 → 138 → 163 → 201 → 204, all passing under
`pytest --ignore=tests/ui/`, plus 49 under `pytest tests/ui/ --browser chromium`.
Step 8 adds 24 live tests, deselected by default and reported as
`204 passed, 24 deselected`. The three tests above 201 cover the legacy tier
aliases added with the rename (§3).

**`preferred_model` was inert until step C.** `unit_parser.py` read it and put
it in the question dict, `parselatex.py` did the same for LaTeX sources, and
**nothing consumed it** — neither `routes/api.py` nor `Grader.grade()`
consulted it, so the model was always whatever the client sent from the
dropdown. Every `preferred_model` value in `example_repo/`, in
`llmgrader/mcp/examples/`, and in instructors' own course repositories has
therefore never influenced a grade, and none of them has ever been exercised.
Two consequences for step 10: those values are untested data rather than
working configuration, and they should be rewritten to the symbolic tier names
(`cheap` / `mid` / `strong`) added in step C, so the next slate refresh does
not require touching course packages at all.

**Step 0 (unplanned, urgent).** `grader.py` printed the shared OpenAI key to
stdout on every community-key grading request (`print('admin key=', ...)`) and
dumped the whole prefs dict, including `openaiApiKey` and `hfToken`, one line
above. On Render stdout is the log stream, so both were live credential leaks.
Fixed in its own commit: the key print is gone, the prefs print goes through a
new `redact_secrets()` helper. **The leaked key still needs rotating — that is
a human action and has not been done.** A sweep of the rest of `llmgrader/`
found no other site that prints a secret; `llmgrader_env_vars.py` masks by
default and `generate_signing_keys.py` prints a keypair by design.

**Step 7c is the deploy blocker and is now handled.** Production's
`admin-config.json` has `allowedModels: ["gpt-4.1-mini"]`, which after the
slate refresh matched nothing the UI could offer — every student on the
community key would have been hard-blocked with an error telling them to pick
another model. `Grader.load_admin_preferences` now migrates the list on read
through `migrate_allowed_models()`: **`["gpt-4.1-mini"]` becomes
`["gpt-5.6-luna"]`**, so the community key serves the cheap tier only and the
admin can widen it in the UI. `GET /api/admin/preferences` applies the same
migration so the modal cannot silently re-save a narrower list.

**Independently verified 2026-08-22** (not taken from the implementation report): all 138 tests pass; every `supports_temperature` flag in both the live and deprecated registries was probed against the real API and **all seven retired models match reality**, including the non-obvious `gpt-5-mini=False`. See §9 for the one value that remains unconfirmed.

Five design decisions were made during implementation that this plan had underspecified, and they are now the spec:

1. **Retired models get their own `ModelSpec`, not just an alias.** §6a said aliases "resolve to live registry entries"; that is true of the alias *map*, but a spec must describe the model actually on the wire, so `get_spec("gpt-4.1-mini")` returns a `gpt-4.1-mini` spec and logs the deprecation. Both structures exist.
2. **`gpt-5-mini` is `supports_temperature=False`**, unlike the other six retired models. The hack being removed set `temperature: 1` for it precisely because it rejects any non-default value. Since 1 is the API default, omitting the key reproduces the old wire behavior exactly. Confirmed by probe.
3. **No tier replacement maps to `gpt-5.6-sol`.** Auto-upgrading a retired mid-tier model to $4/$20 on the shared community key is the exact risk §9 flags. `gpt-5.1`/`5.2`/`5.4` → terra; the minis and nano → luna. This is also what makes the §9 allow-list question safe to answer with auto-map rather than reset.
4. **`_build_message_content` is provider-neutral.** It returns `(text, image_uris)` — the annotated task and the data URIs in canonical order — and each factory wraps a URI into its own content-part shape. That is the part that had drifted between the two providers, and it is the part now covered by a test.
5. **`mcp/blind_user_llm.py` takes the mid tier, not `DEFAULT_MODEL`.** It hard-coded `gpt-4.1`, a flagship-class model, and drives a tool-calling authoring loop rather than routine grading; dropping it to the cheap tier would be a capability downgrade. It now uses `default_for_tier("mid").id`.

## 1. Problem

The supported-model list lives in the front end, is duplicated, and is stale.

- `llmgrader/static/js/app.js:27-37` — `MODEL_PROVIDER` map plus `DEFAULT_MODEL = "gpt-4.1-mini"`. This is the *only* real registry.
- `llmgrader/static/js/admin.js:126` — reads the same `MODEL_PROVIDER` global to render the admin allow-list checkboxes (implicit cross-file coupling; `admin.js` has no import).
- Server-side defaults are hard-coded separately and drift:
  - `llmgrader/routes/api.py:614` — `model = data.get("model", "gpt-4.1-mini")`
  - `llmgrader/services/grader.py:1321` — `model: str = "gpt-4.1-mini"`
  - `llmgrader/services/autograde_llm_latex.py:210`, `llmgrader/utils/create_grading_json.py:121` — CLI defaults
  - `llmgrader/mcp/blind_user_llm.py:31` — `DEFAULT_MODEL = "gpt-4.1"`
  - `llmgrader/mcp/unit_xml_tools.py:495` — `preferred_model` example
- The server never validates `model` against a registry; it only checks the admin allow-list (`grader.py:1239`) when the admin key is used. A user with their own key can send any string.
- Model-specific quirks are hard-coded as string prefix hacks: `grader.py:1122` sets `"temperature": 1 if model.startswith("gpt-5-mini") else 0`. **Confirmed by probe 2026-08-22:** all three GPT-5.6 models reject the parameter outright with `400 Unsupported parameter: 'temperature' is not supported with this model`. This is not a latent risk — it is a hard blocker on the entire slate, and it makes the fix a *prerequisite* for exposing any new model rather than a later cleanup (see §8).
- Hugging Face is a second provider (`grader.py:1163-1211`) that is unreachable from the UI — `app.js:1500-1505` hard-fails with "Only OpenAI models are supported." Dead code plus a live token-storage surface.
- There are no tests that any advertised model actually works.

## 2. Goals

1. Pick a current, small, defensible model slate.
2. One cheap default good enough for routine question grading.
3. One strong long-context model for project/report grading.
4. Remove Hugging Face entirely.
5. Add a live model test suite that is opt-in (needs a real API key).

Explicitly out of scope: Gemini / multi-provider support (Appendix A).

## 3. Design: a single server-side model registry

Create `llmgrader/services/models.py` as the one source of truth. Everything else reads from it.

```python
@dataclass(frozen=True)
class ModelSpec:
    id: str                 # provider-native model id sent on the wire
    provider: str           # dispatch key into PROVIDER_CALLERS (§3)
    label: str              # UI display name
    tier: str               # "cheap" | "mid" | "strong"
    context_tokens: int
    # OpenAI prices a long-context request higher. Store the break and both
    # rate pairs so the cost report is not silently ~2x optimistic on exactly
    # the project-grading requests we care most about.
    long_context_threshold: int | None
    usd_per_mtok_in: float
    usd_per_mtok_out: float
    usd_per_mtok_in_long: float | None
    usd_per_mtok_out_long: float | None
    supports_temperature: bool
    supports_web_search: bool
    supports_images: bool
    notes: str              # USER-FACING one-line guidance, rendered in the UI
                            # (§4) — not an internal comment. Required, non-empty.

MODEL_REGISTRY: dict[str, ModelSpec]   # keyed by id
DEFAULT_MODEL_SIMPLE: str              # the simple tier default
DEFAULT_MODEL_STANDARD: str            # the standard tier default
DEFAULT_MODEL_COMPLEX: str             # the complex tier default
```

Helpers: `get_spec(model_id)`, `default_for_tier(tier)`, `is_supported(model_id)`.

### Tier vocabulary: difficulty, not price (decided 2026-08-22)

The tiers were originally `cheap` / `mid` / `strong` and the constants were
`DEFAULT_MODEL` / `DEFAULT_PROJECT_MODEL`. Both are now one vocabulary named
for **the difficulty of the problem being graded**:

| Was | Is |
|---|---|
| `TIERS = ("cheap", "mid", "strong")` | `("simple", "standard", "complex")` |
| `DEFAULT_MODEL` | `DEFAULT_MODEL_SIMPLE` |
| — | `DEFAULT_MODEL_STANDARD` *(new)* |
| `DEFAULT_PROJECT_MODEL` | `DEFAULT_MODEL_COMPLEX` |

Rationale:

- **The tier is chosen by course authors, and difficulty is what they know.**
  `preferred_model="complex"` answers "how hard is this question?"; `"strong"`
  asks them to answer "how capable a model does this need?", which is a
  question about the slate rather than about their course. The price ramp
  follows the difficulty ramp, so one vocabulary serves both readings.
- **`DEFAULT_PROJECT_MODEL` was too narrow.** A hard single question needs the
  capable model as much as a report does; naming the constant after one use
  case invited exactly the mis-selection §4 worries about.
- **`cheap` was actively misleading as guidance.** A student reading a
  dropdown does not want the cheap model, they want the right one — and luna
  is the right one for most questions, not a budget compromise.
- **`mid` had no meaning at all** outside the price ordering it implied.

No compatibility shim for the constants: they are internal to this repo, and
all 70 references were renamed in one commit. The *tier strings* are different
— they shipped to `main` in step C and can appear in `preferred_model`
attributes in course repositories nobody here controls, so
`LEGACY_TIER_ALIASES` keeps `cheap`/`mid`/`strong` resolving forward with a
deprecation warning, exactly as a retired model id does.

`GET /api/models` payload keys were renamed to match
(`default_model` / `default_project_model` → `default_model_simple` /
`default_model_standard` / `default_model_complex`). The front end is the only
consumer and ships with the server; a stale cached `app.js` reading the old key
falls through to `MODEL_CATALOG[0]`, which is the simple tier — the same model
it would have selected anyway.

**Why server-side:** it lets the grader make capability decisions (temperature, tools, images) from data rather than `startswith` checks, lets the API reject unknown models, and removes the JS duplication.

**On the provider seam.** The multi-provider abstraction stays — more providers are expected later (Appendix A, and others). But *keeping* it should not mean leaving it as it is. Today's `_make_llm_caller` (`grader.py:1060-1215`) is one long `if/elif/else` with the multimodal image-prep block duplicated verbatim between the openai and hf branches; that shape is why adding a provider is a scary edit rather than a drop-in.

Refactor it into a real seam:

```python
# grader.py — or a new services/providers.py if it grows
def _build_message_content(task, ref_images, student_images): ...   # shared, extracted once

def _make_openai_caller(spec, model, api_key, task, timeout, tools, ...): ...

PROVIDER_CALLERS: dict[str, Callable[..., Callable[[], tuple]]] = {
    "openai": _make_openai_caller,
}

def _make_llm_caller(self, provider, model, ...):
    try:
        factory = PROVIDER_CALLERS[provider]
    except KeyError:
        raise ValueError(f"Unknown provider '{provider}'")
    return factory(...)
```

Every caller returns the same 4-tuple contract the current code already uses: `(GraderRawResult, input_tokens, output_tokens, tool_call_summary)`. Adding a provider then means writing one factory and adding one dict entry — no edits to `grade()` or to the dispatch itself.

`provider` on `ModelSpec` is the dispatch key, so the registry and the caller table stay in sync by construction (tested in §6a).

### Wiring

- New endpoint `GET /api/models` in `llmgrader/routes/api.py` returning `[{id, label, provider, tier, context_tokens, notes}, ...]` plus `default_model`. Public — no secrets in it.
- `app.js`: delete the `MODEL_PROVIDER` literal and `DEFAULT_MODEL`; `populateModelSelect()` becomes async and fetches `/api/models`, caching the result. Keep the existing global-name contract (expose `window.MODEL_PROVIDER` derived from the fetch) so `admin.js:126` needs only a one-line change.
- Render `notes` as guidance, per §4: append it to the option label (e.g. "GPT-5.6 Luna — best for routine problems, fastest and cheapest") and show it as a help line under the select when a model is chosen. Order options `cheap` → `mid` → `strong` so the list reads as a ramp. With three same-family models, `<optgroup>` is not worth it.
- Replace the hard-coded server defaults listed in §1 with imports of `DEFAULT_MODEL`.
- `api.py` grade-job handler: reject an unknown `model` with 400 rather than passing it through to the provider.

Note: `preferred_model` in unit XML (`llmgrader/schemas/unit.xsd:95`) stays a free `xs:string` — do **not** enumerate models in the schema, or every course package breaks on each model refresh. Instead `UnitParser` warns (not errors) when `preferred_model` is not in the registry, and the grader falls back to `DEFAULT_MODEL`. **Done in step C**, along with the symbolic form: `resolve_preferred_model()` accepts a tier name (`cheap` / `mid` / `strong`) as well as a concrete or retired id, so a course package survives a slate refresh untouched. The attribute sets the *default selection* for a question and never locks it — a student with their own key may still pick a stronger model.

## 4. Model slate

Prices verified 2026-08-22 against the OpenAI docs. Re-confirm against the account before coding, since entitlements differ per org:

```bash
curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"
```

### Current landscape

OpenAI's GPT-5.6 family (launched 2026-07-09) dropped the `mini`/`nano` suffixes for three named tiers. All three share a ~1.05M-token context window, a 128K max output, and a 2026-02-16 knowledge cutoff, and all are Responses API models — which matches the existing call path at `grader.py:1132`.

USD per 1M tokens, short context / long context:

| Model | Input | Cached in | Output |
|---|---|---|---|
| `gpt-5.6-sol` | $4.00 / $8.00 | $0.40 / $0.80 | $20.00 / $30.00 |
| `gpt-5.6-terra` | $2.00 / $4.00 | $0.20 / $0.40 | $12.00 / $18.00 |
| `gpt-5.6-luna` | $0.20 / $0.40 | $0.02 / $0.04 | $1.20 / $1.80 |
| `gpt-5.4` (272K ctx) | $2.50 / $5.00 | $0.25 / $0.50 | $15.00 / $22.50 |
| `gpt-5.4-mini` | $0.75 | $0.075 | $4.50 |
| `gpt-4.1-mini` *(today's default)* | $0.40 | $0.10 | $1.60 |

`gpt-5.6-luna` undercuts the current `gpt-4.1-mini` default on both rates — half the input price, and $1.20 vs $1.60 output. Moving to the newest generation makes the cheap path cheaper, not more expensive. An earlier draft of this plan proposed `gpt-5.4-mini` / `gpt-5.4`; that slate is superseded and was strictly the worse buy.

### Measured, not estimated (probe run 2026-08-22)

List prices mislead for this workload. Grading is **output-dominated** — a typical single-question request is ~200 input / ~200 output tokens — so the output rate drives cost, not the headline input rate. Measured against the real request shape (Responses API, `json_object`, one correct and one wrong answer to a 2-point chain-rule rubric):

| Model | $/question | $/1000 questions | Latency | Correctness floor |
|---|---|---|---|---|
| `gpt-5.6-luna` | $0.000305 | $0.30 | 2.8s | **PASS** |
| `gpt-5.6-terra` | $0.002207 | $2.21 | 2.2s | PASS |
| `gpt-5.6-sol` | $0.003894 | $3.89 | 3.1s | PASS |
| `gpt-4.1-mini` *(current default)* | $0.000390 | $0.39 | 4.1s | **FAIL** |

Consequences for the slate:

- The luna → 4.1-mini saving is **~22%, not ~50%**. Real, but do not oversell it; cost is not the main argument for this migration.
- The luna → sol gap is **~13x realized**, not the ~20x list prices suggest. Still large enough to justify two tiers rather than three.
- All three 5.6 models are *faster* than the 4.1-mini they replace.
- `gpt-4.1-mini` awarded **1/2 points and "partial"** to an answer that missed the chain rule entirely and satisfied zero rubric items. All three 5.6 models correctly returned 0 / "fail". **This is n=1 and not conclusive** — it is the reason §6b must run against real submissions before the default flips, not a substitute for having done so. But the direction favors the migration, and the *cheapest* new model got it right.

Verified the same day: all of `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol` are visible to the account, as are all seven models slated for retirement (124 models total). Nothing in the slate is entitlement-blocked.

### Measured by the live suite (step 8, 2026-08-22)

Second independent measurement, from `pytest tests/live -m live` — six calls per
model through the real `Grader`, so this prices the app's actual request shape
(system prompt, rubric block, JSON contract) rather than a probe script's.
Latency is `latency_ms` as the app records it, which includes post-processing,
not just the API call. Raw per-call data is in `tests/live/_report.json`
(gitignored; regenerate by re-running the suite).

| Model | $/question | $/1000 questions | Mean latency | $/web-search call | Correctness floor |
|---|---|---|---|---|---|
| `gpt-5.6-luna` | $0.000303 | $0.30 | 2.2s | $0.0012 | **PASS** |
| `gpt-5.6-terra` | $0.002844 | $2.84 | 2.2s | $0.0117 | PASS |
| `gpt-5.6-sol` | $0.005350 | $5.35 | 2.9s | $0.0225 | PASS |

Full run: **$0.078**, 24 tests, 44s wall clock. Token totals per model: 8,890
in / ~700 out across the six calls.

- **`$/question` here excludes the web-search call.** Search results come back
  inside the next request's input — 4,997 tokens against ~520 for a routine
  question — so a blended average runs about 3x the routine figure and would
  misprice the thing the slate is chosen for. The report keeps the two
  separate, and the `$/web-search call` column is the price of the one
  tool-enabled call per model.
- **luna reproduces the probe almost exactly** ($0.000303 vs $0.000305). terra
  and sol come in ~30-40% above it, because the fixture's rubric-bearing
  derivation question is a longer prompt than the probe's and the wrong-answer
  calls draw more output. Treat the higher figures as the better estimate: they
  are measured through the code path a student actually hits.
- **All three passed the correctness floor**, on both the recall and the
  derivation question, in both directions (full marks for correct, zero for
  wrong). No flakiness across three runs of the suite.
- The luna → sol gap measures **~18x** here rather than the probe's ~13x.
- **Nothing in this run exceeded `long_context_threshold`** (largest input:
  4,997 tokens), so every figure above is at the short-context rate and none of
  the long-context uncertainty in §9 applies to it. That uncertainty is still
  live for project grading, and the report labels long-context costs a lower
  bound.
- This is a smoke test, not a benchmark. It establishes that each model is
  reachable, returns parseable JSON, and can tell right from wrong on
  unambiguous input. **It does not establish rubric adherence on real student
  work**, which is what step 9 still needs.

### Validated against real submissions (step 9, 2026-08-22)

`tools/replay_submissions.py` replayed the **67 stored submissions previously
graded by `gpt-4.1-mini`** — the model luna replaced — through the real
`Grader.grade()` path on `gpt-5.6-luna`, then escalated every disagreement to
terra and sol. Detail is in `local_data/replay/` (gitignored; real student
work). Rows are identified here by id only.

| | n |
|---|---|
| replayed | 67 |
| stored grade was an error (not comparable) | 6 |
| agree | 44 |
| luna stricter | 14 |
| luna more lenient | 3 |

**Agreement 72% (44/61 comparable).** On the 17 disagreements, terra and sol
were replayed under identical conditions:

| directional outcome | n |
|---|---|
| both stronger models move the same way luna did | 13 |
| split | 3 |
| neither backs luna | 1 (id 52) |

**Agreement is not accuracy.** The stored grade is the output of the model
being replaced. The decisive row is **id 116: the student submission is empty
(zero characters) and `gpt-4.1-mini` awarded it 10/10 "pass".** All three
GPT-5.6 models award zero. Of the six empty submissions in the sample,
4.1-mini failed five and passed one; luna failed all six. So the bulk of the
"luna is stricter" column is luna declining to give credit that should never
have been given, not luna being harsh.

Two caveats on the method, both real:

- **Rubrics are not stored.** The submissions table keeps the rendered
  `raw_prompt` but no structured rubric, so the 15 rows originally graded with
  a rubric replay through the *no-rubric* template. Agreement is 83% (38/46)
  on rows without a rubric and 40% (6/15) on rows with one — most of that gap
  is the missing rubric, not the model. Comparisons *among* the replayed
  models are unaffected: all three ran without it.
- **The sample is one course's data, n=67, and single-graded.** No human
  adjudication was done; the shortlist below is what a human should look at.

**id 52 is the one row where luna looks wrong**: luna awarded 7/10 where the
old grade, terra and sol all awarded 10/10, docking an imprecision the other
three accepted. One row in 61 is not a case against the default, but it is the
row to read first.

**No registry value was changed by this exercise.** The default flip already
shipped in step 2; this validates a decision already in production, and the
evidence supports keeping it.

### Proposed slate (3 entries — the full GPT-5.6 family)

| Tier | Model | Role | Measured |
|---|---|---|---|
| `cheap` | `gpt-5.6-luna` | **Default.** Routine short-answer and single-derivation grading. | $0.30/1000, 2.8s |
| `mid` | `gpt-5.6-terra` | Multi-part derivations, proofs, short code — work that needs real reasoning but not a project's context. | $2.21/1000, 2.2s |
| `strong` | `gpt-5.6-sol` | Projects and reports; long context and web-search tool use. | $3.89/1000, 3.1s |

Rationale:

- `gpt-4.1-mini`, `gpt-5-mini`, `gpt-5.1`, `gpt-5.2`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano` — all retire. Every one is dominated on price *and* capability by a 5.6 tier.
- `gpt-5.6-terra` — **include.** A course with a diverse problem set has genuinely mid-weight work that luna under-serves and sol overpays for, and terra was the fastest model measured (2.2s) while passing the correctness floor. Taking the whole 5.6 family also keeps the registry conceptually simple: one generation, three tiers, no mixed-vintage explanations.

The risk of a three-way choice is that students pick badly. That is answered with guidance, not by removing the option — which makes the guidance a **deliverable of this plan**, not an aspiration:

- `ModelSpec.notes` is the user-facing one-line guidance string ("Best for routine problems — fastest and cheapest"), not an internal comment. Every entry must have one.
- `/api/models` returns `notes`, and the UI renders it — as the option label suffix and as a help line under the select when a model is chosen. A student should not have to read the docs to pick correctly.
- Course authors get the sharper tool: `preferred_model` in unit XML already pins a model per question (`unit.xsd:95`), so the right default is set by whoever wrote the problem. §7 docs should push authors toward setting it rather than leaving the choice to students.

With `preferred_model` doing the real work, the student-facing selector is an override for the unusual case, and three options is not a burden.

**Nothing currently listed is deprecated.** Only `gpt-4.1-nano` (shutdown 2026-10-23 → `gpt-5.6-luna`) and various `-chat-latest` / `-codex` variants appear in the deprecation notices, and none of those are in `MODEL_PROVIDER`. So this refresh is not urgent-broken — it is stale and overpriced. No emergency, but no reason to defer either: the migration *saves* money.

Selection criteria applied, in priority order: (1) rubric adherence / instruction following on a held-out sample of real submissions, (2) reliable JSON-object output, (3) price per graded question, (4) context window for the strong tier, (5) image input support — the grader passes student and reference images (`grader.py:1098-1118`). Criteria 2-5 are settled by the table above; **criterion 1 is not, and is the thing the live suite in §6b must actually establish** before the default flips.

Keep the retired IDs working server-side for one release: accept them, log a deprecation, and map them to their tier replacement. Stored `preferred_model` values in existing course XML and saved admin `allowedModels` will otherwise break.

## 5. Remove Hugging Face

Delete, in this order:

1. `grader.py:1163-1211` — the `elif provider == "hf"` branch and its `requests` import. This removes the *HF provider*, not the provider abstraction: after the §3 refactor it is one deleted factory function and one deleted `PROVIDER_CALLERS` entry, leaving `{"openai": ...}`. Update the `provider` docstrings at `grader.py:1067` and `1342` to stop enumerating `"hf"`.

   Note the HF branch is also the *only* existing example of a Chat Completions-shaped caller, which is the shape Gemini needs (Appendix A). Delete it from the live path, but it is worth reading once while writing the Gemini factory rather than starting from scratch — git history has it.
2. `api.py:395-410` — `read_admin_hf_token` and its `/api/admin/hf-token` route; `"hfToken": ""` from `get_default_admin_prefs` (`api.py:24`) and from `grader.py:1686`.
3. `app.js:1783-1806` — `getHfToken()`.
4. `admin.js:159-172, 262-263` — `hfToken` read/write.
5. `menu.js:242-343` — `hfToken` localStorage, `hf-key-*` element wiring, `setupKeyToggle('hf-key-input', ...)`.
6. `index.html:197-201, 232-234` — the HF key input, the toggle, and the admin HF token row. Delete outright; git history has the markup if a second-provider key field is ever needed again.
7. Docs: grep for `huggingface` under `docs/`.

**Migration:** existing `admin-config.json` files contain `hfToken` / `adminHfToken`. Do not fail on unknown keys — `set_admin_preferences` (`api.py:737`) should drop them silently on the next save. Note in the release notes that the stored HF token is discarded, and that it should be revoked on the Hugging Face side.

## 6. Tests

### 6a. Offline (always run)

`tests/services/test_model_registry.py` — no network, no key:

- every registry entry has a non-empty `id` and a `tier` in `{cheap, mid, strong}`
- **every registry entry has non-empty `notes`** — it is user-facing guidance (§4), and a blank one ships a bare model ID to a student
- `DEFAULT_MODEL_SIMPLE` and `DEFAULT_MODEL_COMPLEX` are both in the registry, with the expected tiers
- all three tiers are covered
- ids are unique and each map key equals `spec.id`
- deprecated-id aliases all resolve to live registry entries
- **every distinct `spec.provider` in the registry has an entry in `PROVIDER_CALLERS`** — this is the test that keeps the seam honest, and the one that fails loudly if a future provider's models are added to the registry before its caller is written
- an unknown provider raises `ValueError` from `_make_llm_caller` rather than falling through
- the shared message builder produces identical image-part output for the same inputs regardless of caller, so the multimodal contract cannot silently diverge per provider again
- `GET /api/models` returns every registry entry and leaks no key material
- capability flags drive the request payload: extend `tests/services/test_grader_openai_payload.py` with a case asserting `temperature` is *absent* for a `supports_temperature=False` model and present for one that supports it — this is the regression test for the `startswith("gpt-5-mini")` hack

### 6b. Live (opt-in)

New `tests/live/test_models_live.py`.

**Gating — two independent conditions, both required:**

```python
pytestmark = pytest.mark.live

@pytest.fixture(scope="session")
def live_enabled():
    if os.getenv("LLMGRADER_RUN_LIVE_TESTS") != "1":
        pytest.skip("set LLMGRADER_RUN_LIVE_TESTS=1 to run live model tests")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
```

Register the marker and exclude it by default in `pyproject.toml` — the `[tool.pytest.ini_options]` block is currently empty except for comments:

```toml
[tool.pytest.ini_options]
markers = [
    "live: hits the real OpenAI API; requires an API key and costs money",
]
addopts = "-m 'not live'"
```

`addopts` keeps bare `pytest` and CI green with no key. Running them is then explicit:

```bash
LLMGRADER_RUN_LIVE_TESTS=1 OPENAI_API_KEY=... pytest tests/live -m live
```

**What each live test asserts,** parametrized over `MODEL_REGISTRY` so adding a model automatically adds coverage:

1. *Reachability* — a trivial grading call returns without an API error. Catches retired/renamed IDs, which is the failure mode that produced this whole task.
2. *Schema* — the response parses as `GraderRawResult` and `grade_post_process` yields a `GradeResult` with `0 <= points <= max_points`.
3. *Correctness floor* — a small fixture where an unambiguously correct answer scores full marks and an unambiguously wrong one scores zero. Two questions: one recall, one short derivation. Keep it coarse — this is a smoke test, not a benchmark, and a flaky assertion here is worse than no assertion.
4. *Capability flags* — if `supports_images`, send a tiny inline PNG and assert no error; if `supports_web_search`, run one tool-enabled call and assert a non-empty `tool_call_summary`.
5. *Cost/latency report* — record `input_tokens`, `output_tokens`, and wall-clock per model, write `tests/live/_report.json` (gitignored), and print a summary table at session teardown. Price it from the `ModelSpec` rate fields, **selecting the long-context rate when input tokens exceed `long_context_threshold`** — otherwise project-grading cost comes out ~2x optimistic, which is the one number this report exists to get right. This is the artifact used to re-justify the slate at the next refresh.

Keep the fixture unit tiny and self-contained under `tests/live/fixtures/` (model the XML on `tests/fixtures/unit_parser/unit_good.xml`). Budget: 3 models x ~5 calls x ~1-2k tokens. From the measured per-question costs in §4, a full run is roughly $0.03 — sol dominates it, and it is still negligible.

**As built (step 8, 2026-08-22).** `tests/live/` holds `conftest.py`,
`test_models_live.py` and a two-file fixture package under `fixtures/`. 24
tests = 3 models x 8 assertions, costing 6 API calls per model. Four points
where this section was wrong or underspecified:

1. **`Grader.grade()` swallows API errors, it does not raise.** A retired model
   id comes back as `{"result": "error", "full_explanation": "openai API call
   failed: ..."}`, indistinguishable from a graded submission unless the test
   looks. So "returns without an API error" is asserted as `result != "error"`
   with the explanation surfaced in the failure message — this is the whole
   point of the suite and it would have silently passed written naively.
2. **`grade()` returns no token counts.** It records them by writing a
   submission row, so the cost report reads `tokens_in` / `tokens_out` /
   `latency_ms` back out of the run's SQLite DB (redirected to a temp dir via
   `LLMGRADER_STORAGE_PATH`). That also means latency is the app's own
   measurement, including post-processing, not a bare API timing.
3. **`tool_call_summary` never reaches the caller either.** `grade_post_process`
   folds it into `full_explanation` under a `Tool Summary:` header that appears
   only when the summary is non-empty, so that header is the non-empty
   assertion §6b asked for.
4. **The blended `$/question` this section implies is misleading.** A
   web-search call carries the search results in its *input* — 4,997 tokens
   against ~520 for a routine question — so averaging tool-enabled and routine
   calls together triples the per-question figure. The report separates them;
   see §4.

The cost estimate was also low: **$0.078 per full run, not ~$0.03**, because
§6b's budget assumed ~5 calls of ~1-2k tokens and did not account for the
web-search call's input. Still negligible.

**Not in CI by default.** Optionally add a manually-dispatched GitHub Actions workflow (`workflow_dispatch` plus a monthly `schedule`) that runs the live suite with a repo secret, so a silently-retired model ID is caught within a month instead of by a student mid-term.

## 7. Docs

- `docs/student/openai.md:34-39` — rewrite the model guidance and pricing for the three-model slate. This is the long form of the `notes` strings, with worked examples: which tier for a one-line derivative, which for a multi-part proof, which for a project. Use the measured per-question costs from §4, not list prices.
- **New, for course authors:** a short section pushing `preferred_model` as the right place to make the choice. Per §4, if authors pin the model per question, students rarely touch the selector at all — this is the main mitigation for offering three options, so it should not be a footnote.
- `docs/admin/buildcourse/unitxml.md:261-262` — the `preferred_model` list still says `gpt-4o-mini` / `gpt-4o`; replace with the registry and point at `/api/models` as the live list.
- `docs/admin/buildcourse/rubrics.md:53,164` and the `example_repo/` + `llmgrader/mcp/examples/` XML — update `preferred_model` attributes to current IDs.
- `docs/overview/dataprivacy.md:27` — the sample log line names `gpt-4.1-mini`.
- `CLAUDE.md` — mention `services/models.py` as the model registry.
- Add a short "How to add or retire a model" section: edit `models.py`, run the live suite, update docs. One file, one test command.

**As built (step 10, 2026-08-22).** Everything in the list above, plus:

- `docs/developer/models.md` — the "how to add or retire a model" page, linked
  from the developer index. Covers the `ModelSpec` fields, the two test
  commands, why a retired model keeps its own spec rather than borrowing its
  replacement's, and how to validate a default change with
  `tools/replay_submissions.py`.
- The course-author section landed in `docs/admin/buildcourse/unitxml.md`
  rather than as a new page, next to the `preferred_model` reference it is
  about. It documents the tier names as the recommended form and gives the
  rule of thumb for each, including "do not upgrade to be safe" — `complex` is
  ~18x `simple` per graded question and grades routine work no better.
- `example_repo/` and `llmgrader/mcp/examples/` now pin tiers, not model ids:
  the two single-derivation calculus questions are `simple`, the four
  multi-part ones and the Python/code question are `standard`. No example is
  project-scale, so `complex` appears in the docs but in no example XML.
- The `notes` string is rendered under the select and on hover, but no longer
  appended to the option label — the full sentence overflowed the Preferences
  modal (`app.js:88`).
- `.gitignore` was a Vivado/FPGA template ignoring `*.xml` and `*.json`, which
  in this project are source. It now re-includes them by path under
  `llmgrader/`, `tests/`, `docs/`, `example_repo/` and `soln_repos/`, with
  explicit re-ignores for the generated ones (`tests/live/_report.json`,
  `example_repo/soln_package/`, rendered HTML/PDF, `_site/`). Test fixtures no
  longer need `git add -f`.

## 8. Order of work

1. ~~Verify live model IDs and pricing against the account~~ — **done 2026-08-22**, see §4.
2. Add `llmgrader/services/models.py` plus `tests/services/test_model_registry.py` (offline).
3. **Replace the `startswith` temperature hack with the `supports_temperature` flag** (`grader.py:1122`). Small and surgical — not the `PROVIDER_CALLERS` refactor, just the one capability check.
4. Add `GET /api/models`; move `app.js` / `admin.js` onto it.
5. Refactor `_make_llm_caller` into the `PROVIDER_CALLERS` table plus an extracted shared message builder (§3).
6. Remove Hugging Face (§5).
7. Replace the six hard-coded server-side defaults with `DEFAULT_MODEL`. **Also do the deferred piece of §3's Wiring here:** rejecting an unknown `model` with a 400 in the grade handler was consciously left out of step 4, because it pairs with this cleanup — while `gpt-4.1-mini` is still hard-coded as the default in six places, a strict unknown-model check would reject the app's own fallback.
8. Add `tests/live/` and the `live` marker config.
9. Run the live suite, capture the cost report, confirm rubric adherence on real submissions, then flip the default. Use the same run to sanity-check the tier boundaries — if terra and sol grade a mid-weight problem identically, the guidance in `notes` should say so.
10. Docs and example XML.

**Ordering constraint discovered by the probe.** The temperature fix was originally bundled into the `PROVIDER_CALLERS` refactor and sequenced *after* the registry work. That is wrong: the moment `/api/models` serves a GPT-5.6 model, a user can select it, and every grading request for it 400s until `grader.py:1122` is fixed. So the temperature fix is now step 3 — before the endpoint, after the registry that supplies the flag. Steps 2-4 must ship together as one unit.

Steps 6 and 7 remain independently shippable. Step 5 is the only one restructuring the grading hot path.

## 9. Open questions

- **`offer_free` is registry-side, `allowedModels` is admin-side.** The registry seeds the allow-list only when an admin has never configured one; a stored list, empty or not, always wins. So a later registry edit can never widen what an admin narrowed, and can never re-enable a community key an admin turned off.
- ~~**Middle tier**~~ — **resolved 2026-08-22: include `gpt-5.6-terra`.** A diverse problem set has mid-weight work that luna under-serves and sol overpays for. The pick-badly risk is handled by the guidance requirements in §4 and by pushing course authors toward `preferred_model`.
- **`long_context_threshold` is a guess (currently 128000).** OpenAI's pricing page shows separate short/long context input rates for the whole GPT-5.6 family but **does not state the token count where the long rate begins** — confirmed by re-reading it 2026-08-22. The value is presently unverifiable from the docs and impractical to determine empirically, since the API returns token counts but not billed cost.

  Impact is narrow but real: routine grading runs ~200-400 tokens, nowhere near any plausible threshold, so `cheap` and `mid` are unaffected regardless. It only matters for `sol` on long project submissions — which is exactly the case the §6b cost report exists to price. **Do not let the step-9 cost report be trusted for project grading until this is pinned down**, either from a model detail page or by comparing the billing dashboard before and after one deliberately large request. Until then, treat long-context costs as a lower bound.
- ~~**Admin allow-list migration**~~ — **resolved 2026-08-22: auto-map, in step 7c.** The safety objection to auto-mapping was that a retired mid-tier model could silently become a $4/$20 one; since no alias routes to `gpt-5.6-sol`, that cannot happen, so the friendlier option is also the safe one. Production's `["gpt-4.1-mini"]` migrates to `["gpt-5.6-luna"]`.

---

## Appendix A: deferred — Gemini support

**Deferred 2026-08-22. Low priority.** Recorded here so the work does not have to be re-derived.

### Why it was deferred

The original motivation was a report that students can get free Gemini API credits. That appears to be a misunderstanding of two real but different things:

- **Google AI Pro / AI Plus student offer** (live as of 2026-08-20): US students get 12 months of AI Pro free ($240 value), 140+ other countries get AI Plus; redeemable through 2026-12-31. This is a *consumer subscription to the Gemini app* — study notebooks, flashcards, deep research. Google's API pricing documentation does not indicate it confers any API quota or credits.
- **The Gemini API free tier**, which is real and separate: limited model access, free input/output tokens, AI Studio access, open to any Google account. Rate-limited, with "higher rate limits for production deployments" reserved for the paid tier.

So a student could call the Gemini API for free, but not via the student offer, and not at rates suitable for a class-wide grading service. That removes the cost argument that motivated this work. What remains is second-vendor redundancy and the 2M-token context window — real but not urgent.

### Model candidates (verified 2026-08-22, re-verify before use)

| Tier | Model | Notes |
|---|---|---|
| cheap | `gemini-3.7-flash` | Stable, launched 2026-08-13. $0.75/$3.75 per 1M. ~1.05M ctx. |
| strong | `gemini-3.1-pro-preview` | $2.00/$12.00 per 1M. 2M ctx — the largest available anywhere. |
| (cheapest) | `gemini-3.5-flash-lite` | $0.10/$0.40 per 1M, if raw cost ever dominates. |
| (stable fallback) | `gemini-2.5-pro` | Stable but a generation behind. |

**Preview caveat.** The Gemini flagship is still `-preview` while Flash has shipped stable through 3.7 — a version skew suggesting the Pro line is mid-transition. Preview models can be withdrawn with little notice. If Gemini lands, add a `stability: "stable" | "preview"` field to `ModelSpec` and **exclude preview models from the admin community-key allow-list**, so a withdrawal can only break a user running their own key, never the shared service.

### Integration sketch

Two options:

**A. OpenAI-compatibility endpoint (recommended for a first cut).** Point the existing OpenAI SDK at `https://generativelanguage.googleapis.com/v1beta/openai/` with the Gemini key. No new dependency. Caveat: that surface is Chat Completions, not the Responses API, so `client.responses.create` (`grader.py:1132`) does not apply — a `chat.completions.create` branch is needed, with `response_format={"type": "json_object"}` and `image_url` content parts.

**B. Native `google-genai` SDK.** Full feature access (Google Search grounding as the `web_search` equivalent, native structured output). Costs a new dependency and a second response-parsing path.

Ship A; move to B only if Google Search grounding is wanted for project grading, or if A's `json_object` / image-part handling diverges enough to need compatibility shims. Under A, mark `supports_web_search=False` on Gemini entries and have the UI hide the tool checkbox — `grader.py:1126-1136` would otherwise silently send an OpenAI-only `tools` payload.

Implementation reduces to: write `_make_gemini_caller` (Chat Completions shaped — read the deleted HF factory in git history for the shape), add `"gemini"` to `PROVIDER_CALLERS`, and add the model entries to `MODEL_REGISTRY`. The §6a provider-coverage test fails until the caller exists, which is the intended order.

### Key management

- `localStorage` `geminiApiKey` for the student-supplied key.
- Admin pref `geminiApiKey` in `admin-config.json` plus `GET /api/admin/gemini-key`, mirroring the `read_admin_hf_token` shape that §5 deletes.
- `Grader.get_admin_key` (`grader.py:1216`) must become provider-aware — it reads `openaiApiKey` unconditionally and would hand an OpenAI key to Gemini.
- `app.js:1497-1505` picks the key by `provider` instead of alerting.
- Env fallback `LLMGRADER_GEMINI_API_KEY`.

### Prerequisite

Confirm the Gemini API tier in use does not train on submitted content, since student work is being sent. This is a hard gate, not a nice-to-have — `docs/overview/dataprivacy.md` makes claims that must stay true. `docs/overview/dataprivacy.md` would also need a note that grading requests go to Google when a Gemini model is selected.
