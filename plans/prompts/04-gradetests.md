Implement the plan in `plans/grading_tests.md`: instructor-authored grading tests, a new `llmgrader_test` CLI, and the pytest suites that sit on it. Read the plan in full before changing anything — it contains findings about the existing code that you must not re-derive or contradict.

**The user is away for the duration of this run and cannot answer questions.** Every open question in the plan is decided below. If you hit a decision the plan and this prompt genuinely do not cover, pick the more conservative option, implement it, and record the choice in your final report under "Judgment calls". Do not stop and wait.

`main` is live and auto-deploys to Render. Nothing in this run touches the grading path a student uses — that is deliberate, and it is what makes this run safe to do unattended. If you find yourself editing `routes/api.py`, `services/prompt.py`, or the model-selection path, you have gone out of scope; stop that edit and note it.

## Context you need before starting

Read these, in this order:

1. `plans/grading_tests.md` — the design, and the six caveats that are the real work.
2. `docs/admin/buildcourse/gradetests.md` — the instructor-facing contract. This is already written and describes the interface you are building. **It is the spec.** Where it and the plan disagree, the plan wins on internals and the docs win on anything an instructor sees.
3. `example_repo/unit1/calculus.xml` — the two questions you will write fixtures against. `Exponential derivative` is binary; `Integration by parts` is partial-credit. You need both modes exercised.
4. `llmgrader/services/prompt.py:200-240` and `:355-395` — the two `rubric_eval` shapes. Design decision 1 of the plan hinges entirely on this and it is the thing easiest to get backwards.
5. `tests/services/test_grader_openai_payload.py` — the fake-OpenAI-client pattern. You will use it heavily; see "Testing strategy" below.

## Decisions — do not re-open these

The plan's "Open questions" section is resolved as follows. Update that section of the plan to record these as decided, with a one-line reason each.

- **`expect="feedback"`** is legal in the schema — it is a value the model can return, and an assertion vocabulary that cannot express a real outcome is worse than one that can. But `check` emits a **warning** when a case uses it, because it is close to a tone judgment and makes for unstable tests.
- **No assertions on `feedback` text.** No substring, no regex, not in this run. Do not add the element even as a no-op.
- **`FLAKY` is a failure**, exit code 1. Do not add a `pass_rate` attribute. A case whose verdict depends on the run is a broken case regardless of which way the majority fell.
- **No response caching / recorded responses.** Out of scope for this run entirely.
- **Implement both `--unit` and `--pkg`.** `--pkg` is the simple path and everything else builds on it; `--unit` synthesizes a temporary single-unit package around a loose unit file. See caveat 3 of the plan — image-bearing units are the hard part. If image path resolution under a synthesized package defeats you after a genuine attempt, ship `--unit` working for image-free units, make it emit a clear error for units with images telling the instructor to use `--pkg`, and report the limitation. Do not let this block the rest of the run.

Two further decisions the plan leaves implicit:

- **Root element is `<unit_test>`**, schema file `llmgrader/schemas/unit_test.xsd`, registered in `pyproject.toml`'s `package-data` alongside the existing `schemas/*.xsd` glob (verify the glob already covers it — it should).
- **Console script is `llmgrader_test`**, entry point `llmgrader.scripts.llmgrader_test:main`, matching the naming of the existing `llmgrader_*` scripts.

## Phase 1 — schema, `check`, and the free pytest suite

This is the phase that must land. It makes no API calls, constructs no `Grader`, and touches none of the plan's caveats 2 or 3.

**1a. `llmgrader/schemas/unit_test.xsd`.** Per the plan's "Test file format" section. The schema is necessarily permissive — it cannot know the question's grading mode (caveat 5), so it declares `<expected_points>`, `<expected_result>`, `<expected_rubrics>` all optional and type-checks their attributes. `min`/`max` are `xs:decimal` and independently optional; `expect` is an enumeration of `pass`/`fail`/`feedback`/`n/a`. Follow the conventions in `llmgrader/schemas/unit.xsd`.

**1b. `llmgrader/services/gradetests.py`.** The core module — the one place the logic lives, shared by the CLI and both pytest suites. At minimum: `load_test_file(path) -> UnitTestFile`, `check_file(test_file, unit_data) -> list[CheckFinding]`, and the dataclasses. No CLI concerns in here, no printing.

Every check in the table under "Static checking is a separate, free command" in the plan must be implemented. The mode-pairing check is the one with real substance: read the question's mode through `UnitParser._parse_partial_credit_for_validation` (`unit_parser.py:283`), **not** by reading the `<partial_credit>` element yourself — the plan explains why in caveat 5.

Error messages must name the question and the mode, not just the element, and should carry a line number. `UnitParser._build_xml_line_lookup` (`unit_parser.py:93`) is the existing machinery; reuse it rather than writing a second one.

**1c. `llmgrader/scripts/llmgrader_test.py`** — argparse front end, `check` subcommand only in this phase. Exact option names and exit codes are in the plan's CLI section; they are also in the instructor docs, which is what people will actually follow, so match those.

**1d. `example_repo/unit1/tests/calculus_tests.xml`** — the worked example, and the fixture for the test suite. Cover both grading modes and include, at minimum: a correct full-credit solution for each of the two questions, the power-rule misconception from the docs, and a partial-credit case asserting both a positive item at full value and a negative item at zero. These are real instructor content — write descriptions that would actually help someone reading a failure.

**1e. `tests/services/test_gradetests_static.py`** — the CI gate. Two kinds of test: the example file passes `check` clean, and deliberately-broken files (bad qtag, bad part label, band over the question total, band on a binary question, unknown rubric id) each produce the specific expected finding. Build the broken files in `tmp_path`; do not commit broken fixtures.

**1f. Caveat 1** — `scripts/build_autograder.py:41` globs `*.xml` in the cwd and hard-errors on more than one. A `tests/` subdirectory does not break it, but verify that and add a regression test proving a unit directory containing `tests/` still resolves. If it does break, fix `build_autograder` to ignore subdirectories, not to special-case the name.

**1g. Caveat 4** — add a test asserting a built solution package contains no file with a `<unit_test>` root element. `create_soln_pkg.py` assembles from explicit `<unit>` entries so this should already hold; the test exists to keep it holding.

Commit phase 1 before starting phase 2. `pytest --ignore=tests/ui/` currently collects 204 tests and they all pass — that number must only go up, and no existing test may need editing. If an existing test starts failing, you changed shared behavior; revert and rethink rather than editing the test.

## Phase 2 — the `run` subcommand and the JSON report

**2a. Storage isolation (caveat 2), first, before anything grades.** `Grader.__init__` `rmtree`s its `scratch_dir`, creates a SQLite DB at `get_storage_path()`, and writes a submission row per grade. The runner must set `LLMGRADER_STORAGE_PATH` to a temp directory and pass a temp `scratch_dir`, exactly as `tests/live/conftest.py:live_grader` does. Getting this wrong fills the user's `local_data/` with fake submissions that then pollute the dashboard — treat it as the highest-consequence bug in this run. Write the test that proves isolation *before* the code that needs it.

**2b. Package resolution (caveat 3)** — `--pkg` passes straight through to `Grader(soln_pkg=...)`. `--unit` synthesizes a minimal package in the temp tree: an `llmgrader_config.xml` with one `<unit><source>` entry, plus the asset directories the unit's images resolve against. See the decision above for the fallback if images defeat you.

**2c. Token capture (design decision 6).** Pass `session_id=f"gradetest:{case_id}#{repeat_index}"` to `Grader.grade()`; it lands in the row's `client_id` (`grader.py:1570`). Look the row up by that key. **Do not** copy `_last_submission`'s `ORDER BY rowid DESC LIMIT 1` — it is correct for a serial suite and wrong under `--jobs`.

**2d. Evaluation.** Compare `GradeResult` against the case's expectations, per grading mode. The margin calculation and the `WARN`-on-band-edge behavior are in the plan's terminal-output section.

**2e. JSON report** — every field listed in design decision 5. Nothing summarized away: the full `feedback`, the full `full_explanation`, the entire `rubric_eval` object verbatim including evidence, per repeat. Default path `local_data/gradetests/report.json` (`local_data/` is already gitignored).

**2f. Tokens, not dollars** (design decision 7). Token counts in the default output. `--cost` opts into the estimate derived from `ModelSpec` rates and must print the long-context caveat alongside it — reuse `LONG_CONTEXT_CAVEAT` and the `price_call` logic from `tests/live/conftest.py` rather than writing a second pricing implementation; move it into `gradetests.py` and have the conftest import it from there if that is clean, otherwise leave the conftest alone and note the duplication.

## Phase 3 — HTML report and `--repeat`

**3a. `--html`** — question text, submitted solution, rendered `feedback` (which already carries the rubric table from `append_rubric_feedback`), rubric evidence table, expectations with failures highlighted. Self-contained single file, no external assets. This is the artifact the instructor opens when a case fails for a reason they do not understand, so optimize it for reading, not for looking impressive.

**3b. `--repeat N`, `--jobs N`** — the distribution display and the `FLAKY` verdict from the plan. `--jobs` is why 2c matters.

## Phase 4 — the live pytest suite

`tests/live/test_course_cases.py`, `pytestmark = pytest.mark.live`, parametrized over `(file, case_id)` so each case is a separately named test. Reuse the existing gating in `tests/live/conftest.py` — `LLMGRADER_RUN_LIVE_TESTS=1` plus `-m live`. **Do not invent a second opt-in mechanism** and do not change the `-m 'not live'` default in `pyproject.toml`.

## Testing strategy — read this before phase 2

Most of the runner can and should be tested with **no API calls**, using the fake-client pattern in `tests/services/test_grader_openai_payload.py`: `monkeypatch.setattr("llmgrader.services.grader.OpenAI", _FakeOpenAI)` with a fake that returns canned JSON. That gives you deterministic `rubric_eval` payloads in both shapes, which is exactly what the evaluation logic needs to be tested against — including the case that would otherwise cost the most to discover, a negative rubric item scored the wrong way round.

Aim for the graded path to be fully covered offline. Live calls are for proving the wire works, not for testing logic.

## Spending limit

`OPENAI_API_KEY` may be set in the environment. If it is:

- You may spend **at most 25 live grading calls** across this entire run, all on the cheap tier (`simple`). That is roughly $0.01.
- Use them at the end of phase 2 and the end of phase 4, to prove end-to-end behavior that the fake client cannot: that a real `rubric_eval` comes back in the shape the evaluator expects, and that the live suite runs.
- Count them and report the total.

If `OPENAI_API_KEY` is not set, skip all live verification, make sure everything skips cleanly rather than failing, and say so in the report. Do not treat a missing key as a blocker for any phase.

## Out of scope — do not do these

- **The MCP server.** It is known-broken and being fixed separately. Do not touch `llmgrader/mcp/` at all, including its examples and tests.
- **Response caching.** Decided above.
- **`plans/feedback.md`** — the `full_explanation` collapse. Unrelated work, not started, do not begin it. Note that your JSON report includes `full_explanation`; if that field later goes away this report changes, which is fine.
- **`routes/api.py`, the web UI, `services/prompt.py`, `services/models.py`.** If a change seems needed in any of these, it is a signal you have misread the design. The one permitted exception is moving `price_call` per 2f.
- **Do not change `Grader.grade`'s signature.** Everything you need — `session_id`, `model`, `timeout`, `solution_images` — is already a parameter.
- **Do not edit `.gitignore`.** Note it is a Vivado template that ignores `*.xml` globally, with unignores for `example_repo/**/*.xml` and `tests/**/*.xml` (`:179-187`). Your new fixtures are under those paths so they will add normally — but verify with `git status` that every file you created is actually tracked, and use `git add -f` plus a note in your report if any was skipped.

## Verification

After each phase:

```bash
pytest --ignore=tests/ui/
```

204 tests pass today. That number goes up and never down, and no existing test should need editing.

After phase 1, exercise the real CLI:

```bash
pip install -e .
llmgrader_test check example_repo/unit1/tests/calculus_tests.xml
```

It must exit 0 on the good fixture, and exit 1 with a legible message naming the question when you temporarily break a qtag. Do that by hand once — a passing unit test is not proof the console script is wired up.

After phase 3, generate a real HTML report and confirm it opens and contains the feedback text.

## Git and reporting

Branch `feature/grading-tests` off `main`. One commit per phase, message describing what landed. **Do not push and do not merge** — `main` auto-deploys and the user pushes deliberately.

Keep the documentation true as you go. `docs/admin/buildcourse/gradetests.md` was written ahead of the code and says so — when a phase lands, update the "planned" framing for what now exists, and correct anything the implementation forced you to change. An instructor doc that describes an interface you did not build is worse than no doc.

Add an **Implementation status** section to `plans/grading_tests.md` with a per-phase table, and record the resolved open questions. If you discover something about the codebase that changes the design — the way "`preferred_model` is inert" changed the last run — write it into the plan body, not just the report.

Final report, in this order:

1. What landed, by phase, with files changed.
2. Test counts before and after; anything skipped and why.
3. Live calls used, out of 25, and what each proved.
4. **Judgment calls** — every decision you made that this prompt did not cover, and why you chose as you did.
5. What is not done, and what the next run should pick up.
6. Anything in the plan or the instructor docs you now believe is wrong.

Work through the phases in order. Getting phases 1 and 2 correct and well-tested is worth far more than getting to phase 4 with a shaky foundation — if you run short, stop cleanly at a phase boundary with everything committed and say so.
