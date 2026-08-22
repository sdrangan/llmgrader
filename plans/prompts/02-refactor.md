Continue the plan in `plans/update_model.md`. Steps 1-4 are already done on the current branch `feature/model-registry` — read the plan's "Implementation status" section first, then `git log --oneline main..HEAD` to see what shipped.

This run does step 0 below (new, urgent) plus steps 5, 6, and 7. After this run the branch is intended to be pushed to `main`, which auto-deploys to Render, so correctness matters more than speed. Classes start in about a week.

## Step 0 — FIRST, and independently committable: stop logging credentials

`llmgrader/services/grader.py:1314` is `print('admin key=', admin_key)`. It prints the shared OpenAI API key in plaintext on every grading request that uses the community key. On Render, stdout goes to the log stream.

`llmgrader/services/grader.py:1239` is `print(f"Admin preferences loaded: {prefs}")`. `prefs` contains `openaiApiKey` and `hfToken`, so this dumps secrets too.

Fix both:

- Delete the `admin key=` print outright.
- Make the prefs print safe — log only non-secret fields (e.g. `allowedModels`, `tokenLimit`), or redact any key whose name matches `key|token|secret`. Do not just delete it if it is load-bearing for debugging; redact it.
- Then grep the whole `llmgrader/` package for other prints or log calls that could emit a key, token, or full prefs/config dict, and fix any you find. Report what you found even if the list is empty.

Add a regression test using pytest's `capsys` that calls `get_admin_key` with a populated config and asserts the API key string never appears in captured stdout or stderr.

Commit this on its own, first, before the refactors. It is a live credential leak and should not be entangled with a large diff.

## Step 5 — the PROVIDER_CALLERS refactor

Per §3 of the plan. Refactor `_make_llm_caller` (`grader.py:1060-1215`) into:

- `_build_message_content(task, ref_images, student_images)` — extracted once. It is currently duplicated nearly verbatim between the openai and hf branches; that duplication is the whole reason for this step.
- `_make_openai_caller(...)` — the Responses API path.
- `PROVIDER_CALLERS: dict[str, Callable]` mapping `"openai"` to its factory.
- `_make_llm_caller` becomes a lookup that raises `ValueError(f"Unknown provider '{provider}'")` on a miss.

Every caller keeps the existing 4-tuple return contract: `(GraderRawResult, input_tokens, output_tokens, tool_call_summary)`. This is a pure refactor — no behavior change, and the existing payload tests must pass untouched.

Now add the three offline tests from §6a that run 1 deliberately skipped because the table did not exist yet:

- every distinct `spec.provider` across the live and deprecated registries has an entry in `PROVIDER_CALLERS`
- an unknown provider raises `ValueError`
- `_build_message_content` produces identical output for identical inputs regardless of which caller consumes it

## Step 6 — remove Hugging Face

Per §5 of the plan, which lists all seven sites. This removes the HF *provider*, not the provider abstraction — after step 5 it should be one deleted factory and one deleted `PROVIDER_CALLERS` entry, leaving `{"openai": ...}`.

Note `app.js:1500-1505` currently alerts "Only OpenAI models are supported." in its else branch. Do not leave a dead branch: resolve the key by `provider` via a small lookup, and keep a graceful error for an unrecognized provider rather than an alert that names OpenAI specifically.

Do NOT delete `hfToken` / `adminHfToken` keys from any stored `admin-config.json` on disk. Per §5, unknown keys are simply dropped on the next save — the code must tolerate them being present.

## Step 7 — defaults, unknown-model rejection, and the allow-list migration

**7a. Replace the hard-coded defaults.** Six sites, listed in §1 of the plan: `routes/api.py:614`, `services/grader.py:1321`, `services/autograde_llm_latex.py:210`, `utils/create_grading_json.py:121`, `mcp/blind_user_llm.py:31`, `mcp/unit_xml_tools.py:495`. All should import from `services/models.py` rather than hard-coding a string. Note `mcp/unit_xml_tools.py:495` is a documentation *example* value, not a runtime default — update it to a current id but keep it an example.

**7b. Reject unknown models.** In the grade-job handler, reject a `model` that is not in the live registry and not a resolvable deprecated alias with a 400 and a clear message. Per §3's Wiring, this was deferred from run 1 precisely because it had to wait for 7a.

**7c. The allow-list migration — this is the deploy blocker; get it right.**

Production's `admin-config.json` currently has `allowedModels: ['gpt-4.1-mini']`. `/api/models` now serves only the three GPT-5.6 models, so the gate at `grader.py:1239` rejects every model the UI can offer. Verified against the real config: `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol` are all BLOCKED, while the only ALLOWED model is no longer selectable. Every student on the free community key would be hard-blocked, and the error message tells them to "select another model" — which is impossible.

Fix it by migrating `allowedModels` on load, in `Grader.load_admin_preferences`:

- map each retired id through the existing deprecated-alias map
- drop entries that resolve to nothing, and de-duplicate
- leave already-current ids untouched
- leave an empty list empty — do not helpfully populate it, since an empty allow-list is a deliberate "community key disabled" state

Because the alias map never routes anything to `gpt-5.6-sol` (a step-2 decision, so a retired mid-tier model cannot silently become a $4/$20 model on the shared key), `['gpt-4.1-mini']` migrates to `['gpt-5.6-luna']`. That is the intended outcome: the community key serves the cheap tier only, and the admin can widen it in the UI. **State the resulting list explicitly in your report** so it can be confirmed before deploy.

Write a regression test that reproduces the production scenario exactly: a prefs file containing `allowedModels: ['gpt-4.1-mini']`, then assert `get_admin_key('gpt-5.6-luna')` returns a key rather than a block message. This test is the one that would have caught the outage.

## Out of scope

- Do NOT create `tests/live/` or add the `live` pytest marker. Step 8.
- Do NOT flip any default based on grading quality, and do NOT run a live evaluation suite. Step 9 gates that on real submissions; nothing in this run should change which model is `DEFAULT_MODEL`.
- Do NOT update docs or `example_repo/` XML. Step 10.
- Do NOT add Gemini. Deferred — Appendix A.
- Do NOT rotate the leaked API key or edit any file under `local_data/`. That is a human action; just flag it in your report.

## Verification

```bash
pytest --ignore=tests/ui/
```

All 138 existing tests must still pass, plus your new ones. Steps 5 and 6 are refactors — if an existing test needs changing, that is a signal you changed behavior. Stop and explain rather than editing the test.

Then confirm the app still serves:

```bash
LLMGRADER_AUTH_MODE=dev-open python run.py &
sleep 3
curl -s http://127.0.0.1:5000/api/models
kill %1
```

`OPENAI_API_KEY` is set. Make at most two real API calls to confirm the refactored `_make_openai_caller` still grades end to end through `Grader.grade` — use `gpt-5.6-luna`, roughly $0.0003 each.

## Git and reporting

Continue on `feature/model-registry`. Four logical commits: step 0 first and alone, then 5, 6, 7. **Do NOT push and do NOT open a PR** — the push is a live deploy and the user will do it deliberately.

Finally, update the "Implementation status" table in `plans/update_model.md` to reflect what is now done.

Report: files changed per step, the migrated `allowedModels` value, test counts before and after, results of the live calls, any other credential-logging sites found, and anything in the plan that was wrong or underspecified. If something is genuinely ambiguous, stop and ask rather than guessing — this branch is going to production.
