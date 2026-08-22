Implement steps 2, 3, and 4 of the plan in `plans/update_model.md`. Read that plan first — it is the spec, and §3 defines the exact design.

These three steps must ship together. The plan explains why under "Ordering constraint discovered by the probe" in §8: the moment `/api/models` serves a GPT-5.6 model, a user can select it, and every grading request for it fails until the temperature handling is fixed. Do not stop after step 2.

## Verified facts you can rely on (probed against the live API 2026-08-22)

- `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol` are all visible to this account. So are all seven models being retired. No entitlement problems.
- Measured cost/latency per graded question, for the `notes` guidance strings: luna $0.30/1000 at 2.8s, terra $2.21/1000 at 2.2s, sol $3.89/1000 at 3.1s. All three correctly failed a wrong answer that `gpt-4.1-mini` gave half credit to.
- All three GPT-5.6 models **reject** the `temperature` parameter with `400 Unsupported parameter: 'temperature' is not supported with this model`. `gpt-4.1-mini` still accepts it. This is the single most important behavioral difference in this change.
- The Responses API with `text={"format": {"type": "json_object"}}` works correctly on all four models and returns parseable grading JSON.

## Scope

**Step 2.** Create `llmgrader/services/models.py` containing the `ModelSpec` dataclass, `MODEL_REGISTRY`, `DEFAULT_MODEL`, `DEFAULT_PROJECT_MODEL`, and the helpers `get_spec` / `default_for_tier` / `is_supported`, exactly as specified in §3. Populate with the three-model slate from §4:

- `gpt-5.6-luna` — tier `cheap`, the `DEFAULT_MODEL`
- `gpt-5.6-terra` — tier `mid`
- `gpt-5.6-sol` — tier `strong`, the `DEFAULT_PROJECT_MODEL`

All three are `provider="openai"`, ~1.05M context, support images, support web search, and all three must have `supports_temperature=False`. Pricing fields come from the §4 table including long-context rates and threshold.

`notes` is **user-facing guidance shown in the UI**, not an internal comment — see §4. Write one clear sentence per model saying what kind of work it suits, drawing on the measured cost/latency in §4. Every entry needs a non-empty one.

Add the deprecated-id alias map from the end of §4: `gpt-4.1-mini`, `gpt-5-mini`, `gpt-5.1`, `gpt-5.2`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano` all still resolve, mapping to their tier replacement, logging a deprecation warning when used. Note these retired models DO accept `temperature`, so if you keep them resolvable their specs need `supports_temperature=True` — get this right, it is exactly the bug this step exists to prevent.

Then write `tests/services/test_model_registry.py` covering the offline assertions in §6a. Skip the three `PROVIDER_CALLERS` assertions — that table does not exist until step 5, which is out of scope here.

**Step 3.** Replace the temperature hack at `grader.py:1122` — currently `"temperature": 1 if model.startswith("gpt-5-mini") else 0` — with a lookup of `supports_temperature` on the model's `ModelSpec`. When the flag is false, the `temperature` key must be **absent from the request payload entirely**, not set to 1 or to None. Unknown models not in the registry should omit it too; omitting is the safe default.

This is a surgical change to one request-building site. Do NOT refactor `_make_llm_caller` into `PROVIDER_CALLERS` — that is step 5.

Add the regression test described in §6a: assert `temperature` is absent for a `supports_temperature=False` model and present for one that supports it. Follow the existing fake-client style in `tests/services/test_grader_openai_payload.py`.

**Step 4.** Add `GET /api/models` to `llmgrader/routes/api.py` returning the registry plus `default_model`, and move `llmgrader/static/js/app.js` and `llmgrader/static/js/admin.js` onto it, per the "Wiring" subsection of §3.

Critical detail: `admin.js:126` reads the `MODEL_PROVIDER` global that `app.js` defines, with no import between them. Preserve that contract — populate `window.MODEL_PROVIDER` from the fetch result so `admin.js` needs only a minimal change. Do not restructure the admin allow-list UI.

Surface the guidance, per the "Wiring" subsection of §3: `/api/models` returns `notes`, the option label carries it, and a help line under the select shows it for the chosen model. Order the options `cheap` → `mid` → `strong`. This is a requirement, not a nicety — it is what makes offering three models reasonable.

## Out of scope — do NOT do these

- Do NOT refactor `_make_llm_caller` into the `PROVIDER_CALLERS` table. Step 5. The only grader.py change in this run is the temperature fix.
- Do NOT remove Hugging Face. Step 6.
- Do NOT replace the hard-coded `gpt-4.1-mini` defaults scattered across `api.py`, `grader.py`, the CLI scripts, and the MCP files. Step 7, and doing it early will tangle the step 5 diff.
- Do NOT add Gemini or any second provider. Deferred — Appendix A.
- Do NOT create `tests/live/`, add the `live` pytest marker, or make real API calls. Step 8.
- Do NOT update docs or `example_repo/` XML. Step 10.

## Verification — all must pass before you report done

```bash
pytest --ignore=tests/ui/
```

Every existing test must still pass. If one breaks, fix the cause rather than the test — unless it asserts the old hard-coded model list, in which case update it and say so explicitly in your summary.

Then confirm the endpoint serves and contains no secrets:

```bash
LLMGRADER_AUTH_MODE=dev-open python run.py &
sleep 3
curl -s http://127.0.0.1:5000/api/models
kill %1
```

`OPENAI_API_KEY` is set in the environment. After the offline tests pass, prove the temperature fix works end to end against the real API with a single cheap call on `gpt-5.6-luna` through the actual grader code path — not a hand-rolled `openai` call. If it returns a 400 mentioning `temperature`, the fix is wrong. Keep this to one or two calls; it costs about $0.0003 each.

## Git

Work on a new branch `feature/model-registry` off `main`. Three logical commits, one per step, clear messages. Do NOT push and do NOT open a PR.

## Report back

Summarize: files added/changed, the `/api/models` response shape, test counts before and after, the result of the live `gpt-5.6-luna` verification, and anything in the plan that turned out wrong or underspecified. If you hit a genuine blocker, stop and explain rather than guessing or expanding scope.
