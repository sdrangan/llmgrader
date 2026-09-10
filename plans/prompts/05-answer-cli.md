Implement the plan in `plans/answer_cli.md`: `llmgrader_answer`, a console script that asks a model to answer a unit's questions from the question text alone and writes the answers out as a `<unit_test>` file. Read the plan in full before changing anything — it contains findings about the existing code that you must not re-derive or contradict.

**The user is asleep for the duration of this run and cannot answer questions.** Every open question is decided below. If you hit a decision the plan and this prompt genuinely do not cover, pick the more conservative option, implement it, and record the choice in your final report under "Judgment calls". Do not stop and wait.

**This run makes no API calls and spends no money.** Everything is verified with `--dry-run`, unit tests against a fake caller, and the free `llmgrader_test check`. If you become convinced a live call is needed to finish, do not make it: stop, write the exact command in your report, and continue with the rest.

`main` is live and auto-deploys to Render. Nothing in this run touches the grading path a student uses — that is deliberate, and it is what makes the run safe to do unattended. If you find yourself editing `routes/api.py`, `services/prompt.py`, `services/grader.py`'s `grade()`, or the model-selection path, you have gone out of scope; stop that edit and note it.

## Context you need before starting

Read these, in this order:

1. `plans/answer_cli.md` — the design, and the four caveats that are the real work.
2. `llmgrader/scripts/llmgrader_test.py` in full — the CLI conventions you are matching, down to the voice of the help text and the shape of the summary lines.
3. `llmgrader/services/gradetests.py:1864-2070` — `_plan_run` and `_execute_run`. Your planner and runner are the same shape with the grading call swapped out. Note especially how `_plan_run` gets from a loose unit path to a question dict.
4. `llmgrader/services/grader.py:263-360` — `_build_message_content` and `_make_openai_caller`. You are writing a sibling of the second, and reusing the ideas of the first.
5. `llmgrader/schemas/unit_test.xsd` — what you are emitting. `caseType` is a closed `xs:all`; there is nowhere to put a `model=` attribute.
6. `example_repo/unit1/calculus.xml` and `example_repo/unit1/tests/calculus_tests.xml` — your fixtures. `Exponential derivative` is binary, the other two are partial-credit. You need both modes exercised.

## Decisions — do not re-open these

- **Assertion-free output is the default.** `--expect full` is opt-in. Reason in the plan, §2.
- **Provenance lives in `<description>` and XML comments.** Do not extend `unit_test.xsd` to carry a model id, a timestamp, or an attempt number. The schema is shared with hand-written files and this tool does not get to grow it.
- **Temperature 0 where `spec.supports_temperature` allows**, absent otherwise. Do not add a `--temperature` flag in this run.
- **Unresolved question images are a loud warning, not an error.** An image-free unit must work without `--pkg`. See caveat 1.
- **Empty and refusing answers are emitted, never dropped.** See caveat 2.
- **No caching of answers, no resume, no partial-file recovery.** Out of scope entirely.
- **OpenAI only.** `PROVIDER_CALLERS` has one entry; do not generalize ahead of a second provider.
- Console script is `llmgrader_answer`, entry point `llmgrader.scripts.llmgrader_answer:main`, matching the existing `llmgrader_*` scripts.

## Phase 1 — the module and the emitter (no network at all)

This is the phase that must land.

**1a. `llmgrader/services/answers.py`.** The one place the logic lives. At minimum: a planner that resolves paths → question dicts → per-question model (mirroring `_plan_run`), prompt assembly, the XML emitter, and the dataclasses. No printing, no argparse.

Prompt assembly is the part with real substance. It gets `question_text`, the part labels with their points, and question images — and nothing else. Write that test first: assemble a prompt for a question whose solution, grading notes and rubric all contain distinctive sentinel strings, and assert none of them appear. Everything else in this tool is plumbing; this is the property it rests on.

**1b. The emitter.** Deterministic slugified case ids, CDATA with terminator splitting, the `unit` attribute written relative to the output file, provenance in `<description>`. `--expect full` per §2 of the plan. The emitter must round-trip: feed its output to `validate_test_file()` and then `check_file()` against the source unit, and assert zero errors — with `--expect full`, assert zero findings at all.

**1c. `tests/services/test_answers.py`**, in the style of `tests/services/test_gradetests_static.py`. Baseline is **329 tests passing** (`pytest --ignore=tests/ui/`, 32 live deselected). That number goes up and never down, and no existing test should need editing. Cover at least:

- prompt leaks no solution / rubric / grading notes / solution images
- part labels and points do appear in the prompt
- emitted XML validates, with and without `--expect full`
- `--expect full` bands produce no `check_file` findings, in both grading modes
- an answer containing the CDATA terminator round-trips
- case ids: deterministic, unique, slugified, `--repeat` numbering
- empty answer and refusal are both emitted, and marked
- model resolution: `--model` override, tier name, per-question `preferred_model`, fallback

## Phase 2 — the CLI

**2a. `llmgrader/scripts/llmgrader_answer.py`** — argparse, terminal output, exit code. Synopsis in the plan. Nothing but presentation in this file.

**2b. `--dry-run`** prints the call count and per-model breakdown in the shape `_print_dry_run` uses, and makes no calls. `--cost` adds the `price_call` estimate and the same `LONG_CONTEXT_CAVEAT` text `llmgrader_test` prints. Test that dry-run's fake caller is never invoked.

**2c. `--out` refuses to clobber without `--force`**, and the unresolved-image warning count appears in the summary.

**2d.** Wire `[project.scripts]`, then exercise the real console script by hand — a passing unit test is not proof the entry point is wired up:

```bash
pip install -e .
llmgrader_answer example_repo/unit1/calculus.xml --dry-run --cost
```

## Phase 3 — the model call

**3a.** The free-form sibling of `_make_openai_caller`: same client construction, same `spec.supports_temperature` gate, no `text.format`, no `GraderRawResult`. Returns the text plus input and output token counts. Question images attach as `input_image` parts.

Inject it at a seam the tests can replace — follow the fake-client pattern in `tests/services/test_grader_openai_payload.py`. **Do not call the real API in this run.**

**3b.** Concurrency via the `ThreadPoolExecutor` block in `_execute_run`, and a per-call try/except that records a failed call as a result rather than crashing the run, the way `_grade_attempt` does. One question failing must not lose the other twenty answers.

**3c.** End-to-end with the fake caller: generate a file from `example_repo/unit1/calculus.xml` and confirm

```bash
llmgrader_test check <that file>
```

exits 0. Then delete the generated file — do not commit generated output.

## Phase 4 — docs

- New `docs/admin/buildcourse/answers.md`, in the voice of `gradetests.md`: what it is for (rubric stress test first, curiosity second), the two-step workflow, the `--pkg`/images caveat, and an explicit paragraph saying a low score usually indicts the question or the rubric rather than the model. Instructors will read that number as a verdict on the AI unless you tell them otherwise.
- Link it from `docs/admin/buildcourse/index.md`.
- `CLAUDE.md`: the command in the Commands block, and a short paragraph under Architecture beside the "Grading tests" section.
- Optionally add a `@pytest.mark.live` test under `tests/live/` following `tests/live/test_course_cases.py`. It stays deselected by default. **Do not run it.**

## Git and reporting

Branch `feature/answer-cli` off `main`. One commit per phase, message describing what landed. **Do not push and do not merge** — `main` auto-deploys and the user pushes deliberately. End each commit message with:

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

Add an **Implementation status** section to `plans/answer_cli.md` with a per-phase table. If you discover something about the codebase that changes the design, write it into the plan body, not just the report.

Final report, in this order:

1. What landed, by phase, with files changed.
2. Test counts before and after; anything skipped and why.
3. The exact commands to try it, including the first one that costs money and roughly what it will cost per the registry rates.
4. **Judgment calls** — every decision this prompt did not cover, and why you chose as you did.
5. What is not done, and what the next run should pick up.
6. Anything in the plan you now believe is wrong.

Work the phases in order. Phase 1 correct and well-tested is worth more than reaching phase 4 on a shaky foundation — if you run short, stop cleanly at a phase boundary with everything committed and say so.
