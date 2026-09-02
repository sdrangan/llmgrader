---
title:  Testing the solution
parent: Building a Course Package
nav_order: 5.5
has_children: false
---
# Testing the Unit

## Overview

After you have used [HTML rendering](./htmlnotes.md) to verify the appearance of
the XML file for the questions, it is often useful to test LLM grader on
potential solutions.

Reading a rubric tells you what you *meant*. It does not tell you what the
grader will do with it. A condition that is clear to you may be ambiguous to a
language model; a negative rubric item may never fire; a question may award
full credit to an answer that skips a required step. The only way to find out
is to hand the grader a solution and look at the result.

Doing that by hand — pasting an answer into the web portal, reading the
feedback, adjusting the rubric, pasting again — works once. It does not survive
editing the rubric three weeks later, or switching to a different model. So the
LLM grader lets you write those trial solutions down, together with the result
you expect, and re-run them all with one command.

Two terms are used throughout this page:

- A **test case** is one potential solution to one question, together with the
  result you expect the grader to produce for it. "This answer applies the
  power rule to an exponential, so it should fail, and the
  `polynomial_confusion` rubric item should be the one that catches it."
- A **test case XML file** holds the whole set of test cases for one unit —
  typically several cases per question.

This is ordinary software unit testing, applied to course content. No single
run is authoritative: the grader is a language model, and the same solution may
score 6 one run and 7 the next. What the tests give you is *visibility*. When
grading behavior changes, you find out from a command instead of from a student
in week 10.

## Creating the test

### Where to put the file

Put the test case file in a `tests/` subdirectory beside the unit it tests:

```
unit1/
  calculus.xml
  images/
  tests/
    calculus_tests.xml
```

One file per unit, holding many cases. Do not put it directly beside the unit
XML — `build_autograder` expects to find exactly one XML file in a unit
directory and will refuse to run if it finds two.

A complete worked example ships with the repository at
[`example_repo/unit1/tests/calculus_tests.xml`](https://github.com/sdrangan/llmgrader/blob/main/example_repo/unit1/tests/calculus_tests.xml).
It covers all three questions in the demo unit and both grading modes, and it
is the fastest way to see the format in use.

Test case files are **never included in the course package**. They contain
wrong answers together with their expected scores, which is not something to
ship to a running grader. The package is built from the explicit `<unit>`
entries in `llmgrader_config.xml`, so a `tests/` subdirectory is never picked
up.

### A first test case

Here is a complete, minimal file with one case in it:

```xml
<unit_test unit="../calculus.xml">

  <case id="power_rule_confusion" qtag="Exponential derivative">
    <description>
      The misconception this question exists to catch: the student treats a^x
      as a power of x and applies the power rule.
    </description>

    <solution><![CDATA[
      Using the power rule, bring the exponent down: y' = x a^{x-1}.
    ]]></solution>

    <expected_result>fail</expected_result>

  </case>

</unit_test>
```

Walking through it:

| Item | Meaning |
|---|---|
| `<unit_test unit="...">` | The unit this file tests. The path is relative **to the test file**, so from `unit1/tests/` the unit one level up is `../calculus.xml` |
| `<case id="...">` | A name for this case. It appears in the report and selects the case on the command line, so make it descriptive. Must be unique within the file |
| `qtag="..."` | Which question in the unit this solution answers. It must match the question's `qtag` exactly |
| `<description>` | **Required.** What this case is for. It is printed whenever the case fails, so write it for whoever is reading that failure — possibly you, months later |
| `<solution>` | The trial student answer. Wrap it in `CDATA` if it contains markup, LaTeX, or anything with `<` or `&` in it |
| `<expected_result>` | What the grader should conclude: `pass` or `fail` |

That is a usable test on its own. It asserts that a student who confuses
exponentials with polynomials does not pass the question.

### Asserting on individual rubric items

`expected_result` is a weak claim. It says the answer failed, but not *why* —
and a question can fail an answer for the wrong reason. The more valuable
assertion names the rubric item that should have caught it:

```xml
  <case id="power_rule_confusion" qtag="Exponential derivative">
    <description>
      The misconception this question exists to catch: the student treats a^x
      as a power of x and applies the power rule.
    </description>

    <solution><![CDATA[
      Using the power rule, bring the exponent down: y' = x a^{x-1}.
    ]]></solution>

    <expected_result>fail</expected_result>

    <expected_rubrics>
      <item id="polynomial_confusion" expect="fail"/>
      <item id="final_answer" expect="fail"/>
    </expected_rubrics>
  </case>
```

For a question graded pass/fail, each rubric item comes back with one of four
verdicts, and `expect` asserts which one:

| `expect` | Meaning |
|---|---|
| `pass` | The rubric condition is satisfied and supports correctness |
| `fail` | The item identifies a substantive mistake or an unmet requirement |
| `n/a` | The item does not apply to this solution |
| `feedback` | Useful context, but not decisive on its own |

Read `expect="fail"` on a **negative** item such as `polynomial_confusion`
carefully: `fail` describes the *student's work*, not the test. It means the
grader identified the mistake — which is exactly the behavior this case is
asserting is correct.

`feedback` is accepted but discouraged, and `check` will warn about it. It sits
close to a judgment about tone, and cases pinned to it tend to pass one run and
fail the next.

### Questions that award partial credit

Everything above applies to a question with
`<partial_credit>false</partial_credit>`. If the question awards partial
credit, the grader returns numbers instead of verdicts, and the assertions
become ranges:

```xml
  <case id="missing_limits" qtag="Integration by parts">
    <description>
      Correct antiderivative, then the student stops without evaluating at the
      limits of integration -- a definite integral answered as an indefinite
      one.
    </description>

    <solution><![CDATA[
      Let u = x, dv = e^{2x} dx. Then du = dx and v = (1/2) e^{2x}, so
        integral of x e^{2x} dx = (1/4)(2x - 1) e^{2x} + C.
    ]]></solution>

    <expected_points>
      <part label="all" min="4" max="8"/>
    </expected_points>

    <expected_rubrics>
      <item id="correct_u_dv" min="3" max="3"/>
      <item id="apply_limits" min="0" max="0"/>
    </expected_rubrics>
  </case>
```

- `<expected_points>` bands the score. One `<part>` per part you want to check;
  a part you leave out is not checked at all. For a single-part question the
  label is `all`.
- Each rubric item is banded against its own `point_adjustment`. An item worth
  `+3` can be awarded anywhere in `[0, 3]`, so `min="3" max="3"` asserts full
  recognition, `min="1" max="2"` asserts partial, and `min="0" max="0"` asserts
  it was not awarded.
- An item with a **negative** adjustment such as `-2` is awarded exactly `-2`
  when it fires and `0` when it does not. So `min="-2" max="-2"` means "this
  penalty must apply".
- `min` and `max` are independent and both optional. Omitting one leaves that
  side unbounded.

**Do not mix the two forms.** A pass/fail question has no points to band, and a
partial-credit question has no verdict per item. Using the wrong form is the
most common authoring mistake, and it is the first thing `check` reports.

### Choosing the bands

Two failure modes, opposite directions:

- A band of `[6, 6]` on a genuinely ambiguous answer will pass some runs and
  fail others. Intermittent failures teach you to ignore failures.
- A band of `[0, 10]` on a 10-point question asserts nothing at all. `check`
  flags these.

A useful discipline: after writing a band, ask what score would actually
indicate a grading *bug*. If a 7 would be perfectly reasonable and only a 9
would be wrong, the band is `[0, 8]`, not `[6, 7]`.

Write at least one **correct** solution per question. It is easy to build a
rubric that catches every mistake and also fails correct work, and the
full-credit case is the control that catches it.

## Running the test from the CLI

Two commands. The first is free and the second is not, so run them in that
order.

### `check` — free, run it after every edit

```
llmgrader_test check TEST-FILE [TEST-FILE ...] [options]
```

`check` makes **no grading calls** and needs no API key. It parses the test
file, loads the unit, and cross-references the two:

```bash
llmgrader_test check example_repo/unit1/tests/calculus_tests.xml
```

```
example_repo/unit1/tests/calculus_tests.xml  (unit: calculus.xml, 8 cases)

  no problems found
8 cases, 0 errors, 0 warnings
```

It reports orphaned `qtag`s (renaming a question silently strands every test
for it — this is the most common problem), unknown part labels and rubric ids,
bands that lie outside the question's point range, assertions written in the
wrong form for the question's grading mode, and rubric items that no case
exercises.

That last one is a rubric-quality report in its own right. An item no case ever
moves is either dead weight, a condition the grader cannot recognize, or a case
you have not written yet — and finding out costs nothing.

| Option | Meaning |
|---|---|
| `--unit PATH` | Unit XML to check against. Defaults to the file's `unit` attribute |
| `--pkg PATH` | Check against a built solution package (directory or `.zip`) instead of a loose unit file |
| `--qtag TAG` | Only consider cases for this qtag. Repeatable |
| `--case ID` | Only consider this case id. Repeatable |
| `--no-coverage` | Skip the rubric coverage report |
| `--strict` | Treat warnings as failures |
| `-v` / `-q` | Per-case detail / summary line only |

Exit code `0` means everything checked out, `1` means findings, `2` means the
check could not run at all (missing file, unparseable XML).

### `run` — makes real grading calls

```
llmgrader_test run TEST-FILE [TEST-FILE ...] [options]
```

`run` grades every case through the same path a student submission takes, using
each question's own `preferred_model`, and compares the result to the
expectations. It uses your API key and costs money.

Check the size of the run first:

```bash
llmgrader_test run example_repo/unit1/tests/calculus_tests.xml --dry-run
```

```
dry run: 8 calls across 8 cases
  gpt-5.6-luna                 6
  gpt-5.6-terra                2
no API calls were made
```

Then run it for real:

```bash
llmgrader_test run example_repo/unit1/tests/calculus_tests.xml
```

| Option | Meaning |
|---|---|
| `--model ID\|TIER` | Override the model for every case — a tier name (`simple`/`standard`/`complex`) or a concrete model id |
| `--repeat N` | Grade each case N times and report the spread |
| `--jobs N` | Concurrent grading calls (default 4) |
| `--dry-run` | Print the call count and per-model breakdown, make no calls |
| `--max-calls N` | Refuse to start if the run would exceed N calls |
| `--out PATH` | JSON report destination (default `local_data/gradetests/report.json`) |
| `--html PATH` | Also write the readable HTML report |
| `--cost` | Add a dollar estimate to the summary (token counts are always reported) |
| `--timeout SEC` | Per-call timeout (default 90) |
| `--fail-fast` | Stop at the first failing case |
| `--api-key KEY` | Defaults to the `OPENAI_API_KEY` environment variable |
| `--gradescope [DIR]` | Also write a Gradescope submission from the graded cases — the folder `DIR` and `DIR.zip` beside it, the same zip the portal's **Download submission** produces. Defaults to `./submission`. See [Testing the Autograder](../gradescope/submissiontest.md) |
| `--first-case` | For `--gradescope`: when a question has several selected cases, answer it with the first in document order |

`--qtag`, `--case`, `--unit` and `--pkg` work the same as they do for `check`.

### Reading the output

The terminal gives you a summary — enough to see what passed and to locate a
failure:

```
unit1/tests/calculus_tests.xml  (unit: calculus.xml, 8 cases)

  PASS  log_method_correct          Exponential derivative    10                          gpt-5.6-luna
  PASS  power_rule_confusion        Exponential derivative    0                           gpt-5.6-luna
  WARN  missing_limits              Integration by parts      8 [4-8]        margin 0     gpt-5.6-luna
        on the band edge; widen the band or accept flakiness
  FAIL  forgot_half_in_v            Integration by parts      10 [4-9]                    gpt-5.6-luna
        The algebra slip the rubric for `correct_du_v` calls out by name...
        part 'all': scored 10, expected 4-9, over by 1
        rubric `correct_du_v`: expected point_awarded in 1-2, got 3
        evidence: "The student computes v correctly from dv."

7 passed, 1 failed, 1 warning
8 calls, 41.2 s, 38,412 in / 5,910 out
report: local_data/gradetests/report.json
```

Each line is the verdict, the case id, the question, the score against its band
where there is one, the margin, and the model that graded it. A failing case
prints its `<description>` — which is why the description is required — then
each expectation that was not met, with the evidence the grader cited.

The `margin` column shows how much room a passing score had before it would
have left its band, counting only edges the score could actually cross. A case
passing with margin 0 is one run away from failing.

Questions graded pass/fail have no band, so the column shows the points the
verdict translates to — the question total for a pass, `0` for a fail.

**The full grader output goes to the report files, not the terminal.** Both the
JSON report and the `--html` page contain, for every case: the question, the
submitted solution, the score, the complete student-facing feedback exactly as
a student would see it, every rubric item's verdict with the evidence the
grader cited for it, which expectations failed, and the token counts.

The HTML report is what to open when a case fails for a reason you do not
immediately understand. Reading the grader's own evidence usually makes it
obvious whether the rubric condition was ambiguous, the reference solution was
incomplete, or the test case itself was simply wrong.

### Checking for flakiness

Before you trust a new set of cases, grade them more than once:

```bash
llmgrader_test run unit1/tests/calculus_tests.xml --repeat 3
```

Cases whose verdict changes between repeats are reported as `FLAKY` and count
as failures. A case that passes two runs in three is not a working test — its
band is too tight, and it is far better to discover that now than during
grading week.

## Creating unit tests in your repo

*Planned — not yet available.*

Today the test cases are run from the command line, by you, when you choose to
run them. The natural next step is to run them the way software projects run
their tests: automatically, from a `pytest` suite inside your own course repo,
so that editing a rubric and breaking a test is caught the moment it happens
rather than the next time someone remembers to check.

The intended shape is a small amount of boilerplate in your course repository
that discovers every test case file and turns each case into a named test,
split the same way the two commands are split today:

- The `check` half needs no API key and costs nothing, so it can run on every
  commit — including in continuous integration on GitHub.
- The `run` half makes real grading calls, so it stays opt-in and explicit,
  the way the LLM grader's own live tests do.

Until that ships, running `llmgrader_test check` after editing a unit — it is
free and it takes a second — gets you most of the benefit.

## A suggested workflow

1. Write the question, solution and rubric as usual.
2. Verify the appearance with [HTML rendering](./htmlnotes.md).
3. Write three or four cases: one correct solution, and one per misconception
   the rubric is meant to catch.
4. Run `check`. Fix whatever it reports — this costs nothing.
5. Run `run --repeat 3`. Widen any band that proves unstable, and investigate
   any case that fails outright.
6. Commit the test case file alongside the unit.
7. Re-run `check` on every edit, and `run` before deploying a unit or after
   changing the model.

Step 7 is where the effort pays off. It turns "I think this still grades
correctly" into something you can verify in a minute.
