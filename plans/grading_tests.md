# Plan: Instructor-authored grading tests

Status: **implemented** (all four phases) — see "Implementation status" at the end of
this file for what landed and what did not.
Date: 2026-08-23
Origin: instructor request for a way to unit-test a course's grading the way
software is unit-tested — author fake student solutions alongside the
questions, declare what the grader should do with them, and run the whole set
from a CLI and from `pytest`.

## Motivation

Today the only way to find out whether a rubric grades the way its author
intended is to submit answers by hand through the web UI and read the
feedback. There is no artifact recording "this wrong answer should score 0–2
and should trip the `polynomial_confusion` item", so there is nothing to re-run
when the rubric is edited, when the prompt templates change, or when the model
slate is refreshed.

That last case is the strongest argument. `tools/replay_submissions.py` exists
because the default model flipped and nobody could say whether the new model
still graded real work correctly. That tool needs real student submissions out
of SQLite, with the privacy handling documented in its own docstring. Grading
tests answer the same question with no student data at all, reproducibly, from
files that live in the course repo and diff cleanly.

## What already exists

Most of the machinery is built; what is missing is that the expectations are
hardcoded in Python instead of authorable in XML.

| Piece | Where | Reusable as-is? |
|---|---|---|
| Fixture course package + grade-through-the-real-`Grader` harness | `tests/live/conftest.py` | Yes — the `live_grader` fixture is the pattern |
| Scenario table with expected outcomes | `tests/live/test_models_live.py:49` (`SCENARIOS`) | This is the thing being moved into XML |
| Batch grade + JSON report + cost accounting | `tools/replay_submissions.py`, `tests/live/conftest.py:price_call` | Yes |
| Opt-in gating for paid tests | `conftest.live_enabled` + `-m 'not live'` in `pyproject.toml:32` | Yes — reuse, do not invent a second gate |
| Per-rubric-item outcomes to assert on | `GradeResult.rubric_eval` / `RubricEvalItem` (`grader.py:126`) | Yes — but two shapes, see design decision 1 |
| Per-call token counts and latency | `submissions` row (`DB_SCHEMA`, `grader.py:360`); read back by `_last_submission` | Yes — see design decision 6 |
| XSD validation + line-number error mapping | `UnitParser.validate_unit_file` (`unit_parser.py:177`) | Pattern to copy for the new schema |

## Design decisions

### 1. Assert on rubric items, not only the question total

A band on the question total is a noisy proxy for what the instructor actually
wants to test. For the `Exponential derivative` question in
`example_repo/unit1/calculus.xml`, "3–6 points" is a weak restatement of the
real claim, which is *the grader must notice the student applied the power rule
to an exponential* — i.e. the `polynomial_confusion` item fires and
`final_answer` does not.

Per-item assertions are more stable across models and re-runs than the total,
and when one fails it names the misfiring item instead of reporting "scored 7,
expected 3–6".

**The assertion shape is not the same in both grading modes.** The prompt
templates ask for two different objects, and a test format that ignores this
would be wrong half the time:

| Mode | Template | `rubric_eval[id]` contains | Assertion |
|---|---|---|---|
| `<partial_credit>true</partial_credit>` | `prompt.py:221` | `evidence`, `point_awarded` (float) | `min` / `max` on the awarded adjustment |
| `<partial_credit>false</partial_credit>` | `prompt.py:368` | `evidence`, `result` (`pass`/`fail`/`feedback`/`n/a`) | `expect` = one of those four literals |

`RubricEvalItem` (`grader.py:126`) permits either field and its
`validate_outcome` validator requires at least one, so both shapes are legal
model output; which one arrives is decided by the question's mode, not by the
model.

In partial-credit mode a **negative** item is unambiguous without any extra
vocabulary: an item with `point_adjustment="-2"` yields `point_awarded = -2.0`
when the model finds the misconception and `0.0` when it does not
(`prompt.py:209-212`), so `min="-2" max="-2"` says "this must fire" and
`min="0" max="0"` says "this must not". A positive item with
`point_adjustment="+3"` is a range: the template permits any value in `[0, 3]`,
so `min="1"` asserts partial recognition and `min="3"` asserts full.

An earlier draft of this plan proposed a mode-independent
`expect="triggered" | "not_triggered"`. That was wrong. It has no
correspondence in the JSON, and for negative items its natural reading is
inverted relative to `result="fail"` — "triggered" means the model *found* the
mistake, which the schema records as a failure. The format mirrors the two JSON
shapes directly instead.

Per-item assertions also buy a second tool free: **rubric coverage**. If no
case in a unit ever moves `exponential_form` off its default, that item is dead
weight, and reporting so costs zero API calls.

Bands on the question total stay — they are the only assertion available for
questions with no rubric, and they catch a partial-credit split that sums
wrong even when every item is individually right.

### 2. Static checking is a separate, free command

Two cost profiles, so two commands:

* **`check`** — no API calls, no key, no `Grader`. Runs in a bare `pytest` and
  belongs in ordinary CI.
* **`run`** — real calls, real money. Gated in `pytest` by the existing
  `LLMGRADER_RUN_LIVE_TESTS=1` + `-m live` pair. Not gated in the CLI, where
  invoking the command *is* the opt-in.

`check` does not grade anything. It parses the test file, loads the unit
through `UnitParser`, and cross-references the two. Concretely it reports:

| Check | Why it matters |
|---|---|
| Test file validates against `unit_test.xsd` | Typos in element/attribute names would otherwise be silently ignored |
| Every `<case qtag="...">` exists in the unit | **The most common failure.** Renaming a question orphans every test for it, and nothing else in the system notices |
| Every `<part label="...">` exists in that question's `<parts>` | A stale label asserts on a part that is not graded |
| Every band lies within `[0, points]` for that part | `max="12"` on a 10-point part can never pass |
| Every `<item id="...">` exists in that question's `<rubrics>` | Same orphaning problem as `qtag`, one level down |
| The assertion shape matches the question's mode | `min`/`max` on a binary question, or `expect` on a partial-credit one, can never be satisfied — see design decision 1 |
| Each case has a non-empty `<description>` and `<solution>` | An empty solution grades as a blank submission and the result means nothing |
| **Coverage**: rubric items no case exercises | The rubric-quality report; see caveat 6 for `one_of` groups |
| **Warning**: a band equal to the full range `[0, points]` | Asserts nothing; usually a placeholder someone forgot to tighten |

Everything above is decidable from two XML files. It catches the errors that
accumulate as a course is edited, and it should never cost anything.

### 3. Non-determinism is the central problem, and a band alone does not solve it

A case that passes on one call may pass six times in ten. Determinism cannot be
bought with `temperature=0` either — some registry entries have
`supports_temperature=False` (`services/models.py`), and the payload omits the
parameter for them.

So the runner needs `--repeat N` reporting a pass rate and the observed score
spread, and every result line needs a **margin** column: how close the score
landed to the nearest band edge. A case sitting on the boundary is the one that
flakes next month; the report should say so before it does.

### 4. One test file per unit, not one per solution

Six cases on a hard question and one on an easy one is the normal shape; one
file per solution explodes. Each `<case>` carries an `id`, which becomes the
CLI `--case` selector and the `pytest` parametrize id.

### 5. The report is not the Gradescope format, and the terminal is not the report

The original sketch suggested emitting the Gradescope `results.json`. That
envelope is a student-facing score report (`gradescope/autograde.py` writes
`{"score", "output"}`); a test report needs expected-vs-actual, the band, a
rubric diff, the model id, repeat statistics and token counts. None of that
fits.

The terminal table is a pass/fail summary and nothing more — it must stay
readable at fifty cases. **The full grader output goes to the reports**, so the
instructor can read what the model actually said:

* **JSON** (`--out`, always written), one record per case *per repeat*:
  the case id, qtag, part labels, the model id actually used, `points` /
  `max_points`, the full `feedback` string, `full_explanation`, the entire
  `rubric_eval` object verbatim (evidence included), the expectations and which
  ones failed, `tokens_in` / `tokens_out` / `latency_ms`, and `timed_out`.
  Shaped like `tests/live/_report.json`.
* **HTML** (`--html`, optional), the same content rendered for reading:
  question text, the submitted test solution, the rendered `feedback` — which
  already carries the rubric table appended by `append_rubric_feedback`
  (`grader.py:864`) — and a rubric evidence table per case, with failures
  highlighted. This is the artifact for "why did it grade it that way", and it
  is exactly what a student would see plus the expectations.

Nothing is summarized away. If a case fails on a judgment call, the evidence
string that drove it is in both reports.

### 6. Token counts come from the submissions row, keyed by `session_id`

`Grader.grade()` returns a `GradeResult` and nothing else — usage is recorded
as a side effect, in the `submissions` row it writes (`tokens_in`,
`tokens_out`, `latency_ms`, `timed_out`; `DB_SCHEMA`, `grader.py:360`).

`tests/live/conftest.py:_last_submission` reads it back with
`ORDER BY rowid DESC LIMIT 1`. That is safe for a serial suite and **wrong
under `--jobs`**: with concurrent grading calls the newest row is not
necessarily the one that just finished.

The fix needs no change to the grader. `grade(session_id=...)` is stored as the
row's `client_id` (`grader.py:1570`), so the runner passes a synthetic
`session_id` per attempt — `f"gradetest:{case_id}#{repeat_index}"` — and looks
the row up by that key. This is the reason `--keep-db` exists as an escape
hatch, and the reason the temporary DB is per-run rather than per-case.

### 7. Report tokens; treat dollars as an opt-in estimate

The registry *does* carry prices — `ModelSpec.usd_per_mtok_in` /
`usd_per_mtok_out` plus a long-context pair (`models.py:61`) — and
`price_call` in `tests/live/conftest.py` already turns token counts into
dollars. So a cost figure is computable without consulting the provider's
pricing page.

But that conftest also records why the figure should not be printed by default:
`long_context_threshold` is an unverified estimate, so any call billed at the
long-context rate is priced as a **lower bound**, not a number to quote. A
dollar figure in the default output would be read as authoritative.

So: token counts are the default report, in the terminal and in both report
formats. `--cost` opts into the derived estimate and prints the
`LONG_CONTEXT_CAVEAT` alongside it. Prices are a registry field, so the
estimate tracks a slate refresh automatically and cannot silently rot.

## Test file format

New schema `llmgrader/schemas/unit_test.xsd`, validated the same way units are.

### A binary-graded question

`Exponential derivative` in `example_repo/unit1/calculus.xml` has
`<partial_credit>false</partial_credit>`, so its rubric items come back with
`result`, not points:

```xml
<unit_test unit="calculus.xml">

  <case id="power_rule_confusion" qtag="Exponential derivative">
    <description>Common misconception: differentiates a^x as if it were x^a.</description>
    <solution><![CDATA[The answer is y' = x a^{x-1}.]]></solution>

    <expected_result>fail</expected_result>

    <expected_rubrics>
      <item id="polynomial_confusion" expect="fail"/>
      <item id="final_answer" expect="fail"/>
    </expected_rubrics>
  </case>

  <case id="log_method_correct" qtag="Exponential derivative">
    <description>Full-credit reference answer by the logarithm method.</description>
    <solution><![CDATA[
      ln y = x ln a, so y'/y = ln a, hence y' = a^x ln(a).
    ]]></solution>

    <expected_result>pass</expected_result>

    <expected_rubrics>
      <item id="taking_logarithm" expect="pass"/>
      <item id="final_answer" expect="pass"/>
      <item id="polynomial_confusion" expect="n/a"/>
    </expected_rubrics>
  </case>

</unit_test>
```

Read `expect="fail"` on `polynomial_confusion` as the template defines it: *the
rubric item identifies a substantive mistake* (`prompt.py:372`). That is the
grader noticing the misconception, which is the outcome the case is asserting.

### A partial-credit question

`Integration by parts` in the same unit has
`<partial_credit>true</partial_credit>` and `point_adjustment` on its items, so
assertions are numeric bands per item:

```xml
  <case id="missing_limits" qtag="Integration by parts">
    <description>
      Correct antiderivative, then never evaluates at the limits of integration.
    </description>
    <solution><![CDATA[
      Let u = x, dv = e^{2x} dx. Then the integral is (1/4)(2x - 1)e^{2x} + C.
    ]]></solution>

    <expected_points>
      <part label="all" min="4" max="7"/>
    </expected_points>

    <expected_rubrics>
      <item id="correct_u_dv" min="3" max="3"/>
      <item id="evaluates_limits" min="0" max="0"/>
    </expected_rubrics>
  </case>
```

### Element notes, and the differences from the original sketch

* **`min`/`max`, not `min_points`/`max_points`.** `max_points` already means
  *the question total* everywhere in the codebase (`GradeResult.max_points`);
  reusing it for a band ceiling would be a permanent source of confusion.
* **`<expected_points>` vs `<expected_result>`.** Which one is legal follows
  the question's `partial_credit` mode, exactly as the rubric assertions do —
  a binary question has no points to band, only `pass`/`fail`. `check`
  enforces the pairing; the XSD alone cannot, because the mode lives in the
  *unit* file (see caveat 5).
* **A negative rubric item needs no special vocabulary.** In partial-credit
  mode `min="-2" max="-2"` asserts an item with `point_adjustment="-2"` fired;
  `min="0" max="0"` asserts it did not. In binary mode, `expect="fail"`
  and `expect="n/a"` respectively.
* **`min`/`max` on a rubric item are optional and independent.** `min="1"` with
  no `max` asserts "the model gave this item some credit" without pinning how
  much — the right assertion for a positive item with a range.
* **No `model` attribute on the case.** The original sketch put
  `model="simple"` on `<question>`, which shadows the unit's own
  `preferred_model`. The model belongs to the *run* (`--model`), defaulting to
  whatever each question resolves to, so a default run tests exactly what
  students hit.
* **`<description>` is required**, not decorative. It is the documentation of
  what the case is for, and it is what the failure message prints.
* **`<images>`** (optional, sibling of `<solution>`): a list of paths or data
  URIs, passed through to `Grader.grade(solution_images=...)`. The grader
  supports image attachments and nothing currently tests that path outside
  `tests/live`.
* **Multi-part questions**: one `<part label="..."/>` per part, labels
  validated against the question's `<parts>`. Omitting a part means no
  assertion on it.
* `<unit_test unit="...">` resolves relative to the test file, so the CLI can
  take just the test file and find the unit. `--unit` overrides.

## CLI

New console script `llmgrader_test` in `pyproject.toml:[project.scripts]`,
implemented at `llmgrader/scripts/llmgrader_test.py`. The name follows the
existing `llmgrader_*` / `create_*` convention; `grade_test` was the original
proposal but reads ambiguously ("grade a test?").

### Synopsis

```
llmgrader_test check <test-file>... [options]
llmgrader_test run   <test-file>... [options]
```

`<test-file>` is one or more paths, or a glob (`unit1/tests/*.xml`). Both
subcommands accept multiple files and report across all of them.

### Common options

| Option | Default | Meaning |
|---|---|---|
| `--unit PATH` | the `unit` attribute of the test file | Unit XML to grade against |
| `--pkg PATH` | — | Grade against a built solution package (dir or `.zip`) instead of a loose unit file. Mutually exclusive with `--unit` |
| `--qtag TAG` | all | Run only cases for this qtag. Repeatable |
| `--case ID` | all | Run only this case id. Repeatable |
| `--out PATH` | `local_data/gradetests/report.json` | JSON report destination |
| `-v, --verbose` | off | Per-case detail, including rubric evidence |
| `-q, --quiet` | off | Summary line and exit code only |

### `check` options (no API calls, always free)

| Option | Default | Meaning |
|---|---|---|
| `--coverage` / `--no-coverage` | on | Report rubric items no case exercises |
| `--strict` | off | Treat warnings (uncovered rubric items, band wider than the question total) as failures |

### `run` options

| Option | Default | Meaning |
|---|---|---|
| `--model ID\|TIER` | per-question `preferred_model` | Override the model for every case. Accepts a tier name (`simple`/`standard`/`complex`) or a concrete id, resolved through `services/models.py` |
| `--repeat N` | `1` | Grade each case N times; report pass rate and score spread |
| `--jobs N` | `4` | Concurrent grading calls |
| `--timeout SEC` | `90` | Per-call timeout. The app default of 20 s is too tight for reasoning models — matches `LIVE_TIMEOUT` in `tests/live/conftest.py` |
| `--dry-run` | off | Resolve every case, print the call count and per-model breakdown. No API calls |
| `--max-calls N` | none | Refuse to start if the run would exceed N calls. `--repeat` on a large unit is easy to under-estimate |
| `--cost` | off | Also report a dollar estimate from the `ModelSpec` rates, with the long-context caveat printed alongside — see design decision 7 |
| `--html PATH` | none | Write the readable report: question, submitted answer, rendered `feedback`, rubric evidence table |
| `--fail-fast` | off | Stop at the first failing case |
| `--api-key KEY` | `$OPENAI_API_KEY` | Passed to `Grader.grade(api_key=...)` |
| `--keep-db` | off | Keep the temporary SQLite storage the run writes to (see caveat 2) |

### Examples

```bash
# Free: does the test file even line up with the unit?
llmgrader_test check example_repo/unit1/tests/calculus_tests.xml

# How many calls would a full run make, and against which models?
llmgrader_test run example_repo/unit1/tests/calculus_tests.xml --dry-run

# Grade one question's cases, three times each, on the default models
llmgrader_test run example_repo/unit1/tests/calculus_tests.xml \
    --qtag "Exponential derivative" --repeat 3

# Would the complex tier grade this course differently?
llmgrader_test run "example_repo/unit1/tests/*.xml" \
    --model complex --out local_data/gradetests/complex.json

# Everything, with a page to read the student-facing feedback
llmgrader_test run "example_repo/**/tests/*.xml" --html local_data/gradetests/report.html
```

### Terminal output

The table is a summary. Full feedback, evidence and per-case token counts go to
`--out` and `--html`; the terminal prints only enough to locate a failure.

```
unit1/tests/calculus_tests.xml  (unit: calculus.xml, 4 cases)

  PASS  power_rule_confusion       Exponential derivative  fail                       gpt-5.6-luna
  PASS  log_method_correct         Exponential derivative  pass                       gpt-5.6-luna
  WARN  missing_limits             Integration by parts     6.0  [6-9]   margin 0.0   gpt-5.6-luna
        on the band edge; widen the band or accept flakiness
  FAIL  sign_error                 Integration by parts     9.0  [3-6]   over by 3.0  gpt-5.6-luna
        rubric `sign_error_penalty`: expected point_awarded in [-2,-2], got 0.0
        evidence: "The antiderivative is correct throughout."

3 passed, 1 failed, 1 warning
9 calls, 41.2 s, 38,412 in / 5,910 out
report: local_data/gradetests/report.json
```

With `--repeat 3` the score column becomes a distribution and the verdict a
pass rate:

```
  FLAKY missing_limits             Integration by parts   6.0 6.0 8.0  [6-9]  2/3 passed
```

With `--cost`, one extra line:

```
estimated cost $0.031 (registry rates; long-context calls are a LOWER BOUND)
```

Exit codes: `0` all cases passed, `1` at least one case failed, `2` usage or
validation error (bad file, unresolvable qtag). `--strict` promotes warnings
to `1`.

`FLAKY` — some repeats passed and some did not — is a **failure** by default
(exit `1`). A case whose verdict depends on the run is not a working test,
whichever way the majority fell. See the repeat-semantics open question.

## pytest integration

Two suites, matching the two cost profiles:

* `tests/services/test_gradetests_static.py` — runs in a bare `pytest` with no
  key. Parametrized over the test files under `example_repo/`, asserting the
  `check` path: schema, qtag resolution, band sanity, rubric coverage. This is
  the CI gate.
* `tests/live/test_course_cases.py` — `pytestmark = pytest.mark.live`,
  parametrized over `(file, case_id)` so each case is a named test. Uses the
  existing `live_grader`-style fixture and the existing double gate.

Both sit on the same core module, so a case that passes in the CLI passes in
`pytest` for the same reason.

## Caveats — the real work

### 1. `build_autograder` breaks on a sibling XML file

`scripts/build_autograder.py:41` globs `*.xml` in the current directory and
**hard-errors when it finds more than one**:

```
Error: Multiple XML files found in current directory:
Please specify which one to use with --schema option.
```

So dropping `calculus_test_soln1.xml` next to `calculus.xml` in `unit1/`
breaks that script today, for anyone who runs it without `--schema`. Fix by
convention: test files live in a `tests/` subdirectory of the unit directory
(`unit1/tests/calculus_tests.xml`). Cheap, and it also keeps the unit directory
readable. Worth adding a regression test that `build_autograder` still resolves
a unit directory containing a `tests/` subdir.

### 2. `Grader.__init__` has side effects a test runner must not inherit

Three of them, all visible at `grader.py:428-462`:

* it **deletes and recreates `scratch_dir`** (`shutil.rmtree`) — so the runner
  must pass a temp path, never a real one;
* it **opens/creates the SQLite DB** at `get_storage_path()` and **writes a
  submission row for every grade** — so an instructor running grading tests
  would otherwise pollute `local_data/` with fake submissions that then show up
  in the dashboard and in any future replay run;
* it runs `init_db` + `temp_modify_db` migrations against whatever DB it finds.

`tests/live/conftest.py:live_grader` already solves this by setting
`LLMGRADER_STORAGE_PATH` to a temp directory. The runner must do the same by
default; `--keep-db` exists for the case where the instructor wants to inspect
token counts afterwards, the way `_last_submission` does.

### 3. `Grader` loads a *package*, not a unit file

`Grader.__init__(soln_pkg=...)` expects a solution package — a directory or zip
with an `llmgrader_config.xml` naming its units (`example_repo/soln_package/`).
The proposed CLI takes a bare `calculus.xml`. So `--unit` needs to synthesize a
minimal single-unit package in the temp scratch tree (config with one
`<unit><source>` entry, plus any `<assets>` the unit's images need) before
constructing the `Grader`. Image-bearing questions make this non-trivial:
`_extract_solution_images` (`unit_parser.py:945`) resolves image paths relative
to the package root, so a synthesized package must carry the unit's sibling
`images/` directory across or the images silently drop.

`--pkg` sidesteps all of this and should be the path the `pytest` suites use.

### 4. Test files must never ship in a solution package

They contain known-wrong answers *and* their expected scores. Shipping them to
a deployed grader would be bad.

The good news: `create_soln_pkg.py` assembles from explicit `<unit><source>`
entries in `llmgrader_config.xml` (`create_soln_pkg.py:180-205`), not by
globbing, so a `tests/` subdirectory cannot leak in by accident — unless
somebody lists the unit directory as an `<asset>` source, which
`copy_asset_entry` would copy wholesale. Add an explicit test asserting a built
package contains no `unit_test` root element, and a warning in
`validate_course_package_config` if an asset source directory contains one.

### 5. The XSD cannot validate a test file on its own

Which assertion elements are legal in a case depends on the *question's*
`partial_credit` mode, which lives in a different file. `unit_test.xsd` can
declare `<expected_points>`, `<expected_result>`, `min`/`max` and `expect` as
optional and check their types, but it cannot know that this particular case
targets a binary question and therefore must not carry a band.

So the schema is necessarily permissive and `check` carries the real
enforcement. Two consequences worth accepting up front:

* The `check` command is not optional polish — it is where roughly half the
  validation lives. It must run in CI, not just when someone remembers.
* Error messages must name the mode and the question, not just the element:
  *"`missing_limits` asserts `<expected_result>` but `Integration by parts` is
  partial-credit; use `<expected_points>`"*. `UnitParser._build_xml_line_lookup`
  (`unit_parser.py:93`) is the existing machinery for pointing at the offending
  line.

A further wrinkle: `partial_credit` is parsed as a string element
(`unit.xsd:74` types it `xs:string`, and `_parse_partial_credit_for_validation`
at `unit_parser.py:283` normalizes it). The test runner must use that same
parser rather than reading the element itself, or the two will disagree about
what `"True"` means.

### 6. `one_of` groups make coverage reporting fuzzy

`calculus.xml` groups `taking_logarithm` and `exponential_form` as `one_of`. A
correct solution satisfies exactly one — the template instructs the model to
pick the best-supported item and zero the others (`prompt.py:200-203`) — so
"every rubric item is covered by some case" is the wrong completeness criterion
for grouped items. The right one is "every group has a case for each branch".
The coverage report needs to know about groups (`_parse_rubric_groups`,
`unit_parser.py:853`).

This also means a case must not over-specify inside a group: asserting
`expect="pass"` on `taking_logarithm` for a solution that used the exponential
form is asserting which valid method the student chose, not whether grading
worked.

## Files affected

| File | What |
|---|---|
| `llmgrader/schemas/unit_test.xsd` | **new** — the test file schema |
| `llmgrader/services/gradetests.py` | **new** — `load_test_file`, `check_file`, `run_case`, `CaseResult`; the one place the logic lives |
| `llmgrader/scripts/llmgrader_test.py` | **new** — argparse front end, terminal table, JSON/HTML report |
| `pyproject.toml` | register the `llmgrader_test` console script |
| `llmgrader/scripts/build_autograder.py` | tolerate (or document) a `tests/` subdirectory — see caveat 1 |
| `llmgrader/services/unit_parser.py` | optional warning when an asset source directory contains a test file |
| `example_repo/unit1/tests/calculus_tests.xml` | **new** — worked example covering both grading modes, doubles as the fixture |
| `tests/services/test_gradetests_static.py` | **new** — the free CI gate |
| `tests/live/test_course_cases.py` | **new** — the paid suite |
| `docs/admin/buildcourse/gradetests.md` | **new** — instructor-facing guide to designing tests (written ahead of the code, as `rubrics.md` was) |
| `docs/admin/buildcourse/index.md` | link the new page |
| `docs/developer/pytest.md` | how the two suites relate |
| `CLAUDE.md` | commands section |

The MCP server is deliberately **out of scope**. An authoring tool that
proposes wrong-answer variants would be a natural fit, but `mcp/server.py`
needs its own repair first; revisit after.

Note `.gitignore:27` ignores `*.xml` globally with per-directory unignores
(`:179-187`). `example_repo/**/*.xml` and `tests/**/*.xml` are already
unignored, so the new fixtures are covered — but an instructor's own course
repo may need the same treatment, worth a line in the docs.

## Phasing

1. **Schema + `check` subcommand + the static pytest suite.** No API calls, no
   `Grader` construction, none of caveats 2/3 to solve. Ships value immediately
   — a renamed qtag becomes a CI failure — and the format gets exercised by a
   real course package before anything expensive is built on it.
2. **`run` subcommand, JSON report.** Caveats 2 (storage isolation) and 3
   (package synthesis) land here, plus the `session_id` keying from design
   decision 6.
3. **HTML report and `--repeat`.** The instructor-inspection artifact and the
   flakiness data. Separable from step 2 and worth shipping after the core
   runner is trusted.
4. **The live pytest suite**, parametrized per case.

Steps 1 and 2 are the product; 3 and 4 are what make it usable day to day.

## Open questions — resolved

All five were decided before implementation. Recorded here with the reason, so
a later reader does not reopen them by accident.

- **Is `expect="feedback"` ever worth asserting?** **Legal, with a warning.**
  It is a value the model really returns, and an assertion vocabulary that
  cannot express a real outcome is worse than one that can — but it is close
  to a judgment about tone, so `check` warns on every case that uses it.
- **Should a case be able to assert on `feedback` text?** **No.** No
  substring, no regex, and the element is not in the schema even as a no-op:
  a knob that exists gets used, and this one produces tests that fail for no
  useful reason.
- **Repeat semantics.** **`FLAKY` is a failure, exit 1, and there is no
  `pass_rate` attribute.** A case whose verdict depends on the run is a broken
  case regardless of which way the majority fell; a quorum knob would let an
  instructor configure that away instead of fixing the band.
- **Recorded responses.** **Out of scope.** A stale cache asserting on last
  month's grader defeats the purpose of the suite.
- **Does `--pkg` obsolete `--unit`?** **No, both are implemented.** `--pkg` is
  the simple path and the one the pytest suites use; `--unit` synthesizes a
  single-unit package around a loose unit file, because that is the file an
  instructor has open while authoring.


## Implementation status

| Phase | What | Status |
|---|---|---|
| 1 | `unit_test.xsd`, `services/gradetests.py`, `scripts/llmgrader_test.py` (`check`), the worked example, the static pytest suite, caveats 1 and 4 | **done** |
| 2 | `run` subcommand, storage isolation, package synthesis, `session_id` keying, JSON report | **done** |
| 3 | HTML report, `--repeat`, `--jobs` | **done** |
| 4 | live pytest suite | **done** |

### Notes from implementation

* `build_autograder` was **not** broken by a `tests/` subdirectory: its glob
  is `cwd.glob("*.xml")`, which does not descend. Caveat 1 needed a regression
  test (`tests/scripts/test_build_autograder.py`), not a fix.
* The optional warning in `validate_course_package_config` for an asset source
  directory containing a test file (caveat 4) was **not** added. That function
  returns a flat list of *errors* with no warning channel, so a warning there
  would fail packaging for existing courses. The guarantee is carried by
  `tests/scripts/test_soln_pkg_excludes_tests.py` instead, and the hole
  (listing a unit directory as an `<asset>` source) is documented rather than
  closed.
* `example_repo/unit1/calculus.xml` has **no negative-`point_adjustment` rubric
  item** on either partial-credit question, so the worked example cannot show
  a `min="-2" max="-2"` assertion against real course content. The example
  asserts an item at zero instead (`apply_limits`), and the negative-item
  bands are covered against a synthetic unit in the static suite.
* `check` reports schema errors as findings (exit 1) and reserves exit 2 for
  "could not check at all": a missing file, XML that does not parse, an
  unresolvable unit, a selector that matched nothing.
* **The margin rule in design decision 3 needed a correction.** "How close the
  score landed to the nearest band edge" over-reports: a full-credit control
  banded `[9, 10]` on a 10-point part that scores 10 sits on its upper edge
  every single run, and nothing can push it over, because 10 is the maximum.
  The first live run of the worked example produced three such warnings out of
  eight cases, which is exactly the noise that teaches people to ignore
  warnings. The margin now counts only edges a score could actually cross: the
  lower edge when `min > 0`, the upper edge when `max < part total`, and
  neither for an exact band, which is a deliberate pin rather than a range
  with no room in it.
* The live suite honours `LLMGRADER_GRADETEST_MODEL` (a tier name or a model
  id) so it can be run on the cheap tier. Without it each question grades with
  its own `preferred_model`, which is the point: a default run tests exactly
  what students hit. This is not a second opt-in gate -- `live_enabled` is
  still the only gate.
* **`--unit` works for image-bearing units**, contrary to the fallback the
  prompt allowed for. `synthesize_package` copies the unit's sibling
  directories (for a relative `<img src>`) and replays the nearest course
  config's `<assets>` mappings (for `/pkg_assets/...`, whose destination names
  live only in that config). If an image still fails to resolve, the runner
  refuses to grade rather than quietly grading against a question the student
  would not see, and points at `--pkg`.
