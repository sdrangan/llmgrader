---
title:  Testing Your Grading
parent: Building a Course Package
nav_order: 6
has_children: false
---

# Testing Your Grading

## Overview

A rubric is a program. It takes a student solution as input and produces a
score, and like any other program it can be wrong in ways that are invisible
until someone runs it. A condition that reads clearly to you may be ambiguous
to the grader; a negative item may never fire; a `one_of` group may silently
award points twice.

**Grading tests** let you write down what the grader is supposed to do with a
given student answer, and then check that it does. A test case is a fake
student solution plus a statement of the expected outcome. Once the cases
exist, you can re-run them whenever you edit a rubric, change a question, or
switch to a different model — and find out immediately if the grading moved.

This is ordinary software unit testing applied to course content. The point is
not that any single run is authoritative, but that a change in behavior becomes
*visible* instead of being discovered by a student in week 10.

Everything on this page is implemented. See `plans/grading_tests.md` in the
repository for the design and the implementation notes.

## What a test case asserts

Each case makes up to three kinds of claim:

1. **The overall outcome** — the score fell in a range, or the pass/fail
   verdict was as expected.
2. **Individual rubric items** — a specific item fired, or did not.
3. **Nothing else.** Feedback wording, phrasing, and tone are not asserted.
   They vary between runs and between models, and pinning them produces tests
   that fail for no useful reason.

The second kind is the valuable one. "Scored between 3 and 6" is a weak claim;
"the grader noticed the student used the power rule on an exponential" is the
claim you actually care about, and it is far more stable across models and
re-runs.

## Where test files live

Put them in a `tests/` subdirectory beside the unit they test:

```
unit1/
  calculus.xml
  images/
  tests/
    calculus_tests.xml
```

One test file per unit, holding many cases. Do not put test files directly
beside the unit XML — some of the packaging tools expect exactly one XML file
in a unit directory.

Test files are **never included in the course package**. They contain wrong
answers together with their expected scores, which is not something to ship to
a running grader. The package is assembled from the explicit `<unit>` entries
in `llmgrader_config.xml`, so a `tests/` subdirectory is not picked up — but
do not list a unit directory as an `<asset>` source, which would copy it
wholesale.

## Anatomy of a test file

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

</unit_test>
```

| Element | Meaning |
|---|---|
| `unit` attribute | The unit XML this file tests, relative to the test file |
| `id` | A name for the case. Appears in the report and selects the case on the command line. Must be unique in the file |
| `qtag` | The question in the unit this case answers |
| `<description>` | **Required.** What the case is for. Printed whenever the case fails, so write it for the person reading the failure |
| `<solution>` | The fake student answer. Use `CDATA` if it contains markup or LaTeX |
| `<images>` | Optional. A list of `<image>` paths or data URIs to attach, for questions where students submit work as an image |

The assertion elements depend on how the question is graded.

## Binary questions

If the question has `<partial_credit>false</partial_credit>`, there is no
partial score. The grader returns `pass` or `fail` overall, and each rubric
item comes back with one of four verdicts:

| `expect` | Meaning |
|---|---|
| `pass` | The rubric condition is satisfied and supports correctness |
| `fail` | The item identifies a substantive mistake or an unmet requirement |
| `feedback` | Useful context, but not decisive on its own |
| `n/a` | The item does not apply to this solution |

`feedback` is legal, but `check` warns when a case uses it. The template
defines it as useful context that is not decisive on its own, which is close
to a judgment about tone, and cases pinned to it tend to pass one run and fail
the next.

`<expected_result>` also accepts `partial` and `error`. `partial` is reachable
only on a multi-part binary question, where some parts passed and some did
not; `error` asserts that grading itself failed, which is rarely what you
want.

```xml
<expected_result>fail</expected_result>

<expected_rubrics>
  <item id="polynomial_confusion" expect="fail"/>
  <item id="final_answer" expect="fail"/>
</expected_rubrics>
```

Note the reading of `expect="fail"` on a **negative** item such as
`polynomial_confusion`: `fail` means the grader *identified the mistake*. That
is the behavior the case is asserting is correct. It is worth pausing on this
the first time — the word describes the student's work, not the test.

## Partial-credit questions

If the question has `<partial_credit>true</partial_credit>`, the grader
returns numbers, and assertions are ranges:

```xml
<expected_points>
  <part label="all" min="4" max="7"/>
</expected_points>

<expected_rubrics>
  <item id="correct_u_dv" min="3" max="3"/>
  <item id="evaluates_limits" min="0" max="0"/>
</expected_rubrics>
```

Each rubric item is scored against its own `point_adjustment`:

- A **positive** item with `point_adjustment="+3"` is awarded somewhere in
  `[0, 3]`. `min="3"` asserts full recognition; `min="1"` asserts the grader
  gave *some* credit without pinning how much.
- A **negative** item with `point_adjustment="-2"` is awarded exactly `-2`
  when it fires and `0` when it does not. So `min="-2" max="-2"` means "this
  penalty must apply" and `min="0" max="0"` means "it must not".

`min` and `max` are independent and both optional. Omitting one leaves that
side unbounded.

For a multi-part question, write one `<part>` per part you want to assert on.
Parts you leave out are not checked.

### Do not mix the two forms

A binary question has no points to band, and a partial-credit question has no
`result` per item. Using the wrong form is the most common authoring mistake,
and the `check` command reports it by name.

## Designing good cases

**One misconception per case.** A solution that gets three things wrong tests
nothing in particular — when it fails you will not know which rubric item
moved. Write a separate case for each error you want the rubric to catch.

**Start from real student work.** The most valuable cases are mistakes you have
actually seen. Invented wrong answers tend to be wrong in tidy ways that no
student produces.

**Always include at least one correct solution.** It is easy to build a rubric
that catches every error and also fails correct work. A full-credit case is the
control.

**Make bands wide enough to be stable, and no wider.** The grader is a language
model, not a deterministic function. The same solution may score 6 one run and
7 the next. A band of `[6, 6]` on a genuinely ambiguous answer will fail
intermittently and teach you to ignore failures. But a band of `[0, 10]` on a
10-point question asserts nothing at all — the check command flags those.

A useful discipline: after writing a band, ask what score would actually
indicate a grading bug. If a 7 would be fine and only a 9 would be wrong, the
band is `[0, 8]`, not `[6, 7]`.

**Prefer rubric assertions over score bands.** The score is a sum of judgments;
the rubric items are the judgments. When a score band fails you have to work
backwards to find out why. When a rubric assertion fails, the report names the
item and quotes the evidence the grader used.

**Do not over-specify inside a `one_of` group.** If `taking_logarithm` and
`exponential_form` are grouped, a correct solution satisfies exactly one of
them — whichever method the student used. Asserting a specific one is
asserting the student's choice of method, not that grading worked.

## Rubric coverage

Once you have a set of cases, the tooling can tell you which rubric items no
case ever exercises. An item that never fires in any test is one of three
things:

- dead weight that can be removed,
- a condition the grader cannot recognize, or
- a case you have not written yet.

All three are worth knowing about, and finding out costs nothing — coverage is
computed from the files alone, with no grading calls.

## Running the tests

There are two commands, split by what they cost.

### `check` — free, run it often

```bash
llmgrader_test check unit1/tests/calculus_tests.xml
```

This makes **no grading calls** and needs no API key. It compares the test file
against the unit and reports:

- cases whose `qtag` no longer exists in the unit (the most common problem —
  renaming a question silently orphans its tests)
- part labels and rubric ids that do not exist
- bands outside the question's point range
- assertions in the wrong form for the question's grading mode
- rubric items no case covers
- bands so wide they assert nothing
- duplicate case ids, empty descriptions and empty solutions
- cases that make no assertions at all, and questions with no cases

Run this every time you edit a unit. It is fast, free, and catches the errors
that accumulate as a course evolves.

It exits `0` when nothing is wrong, `1` when it found something, and `2` when
it could not run at all — a missing file, XML that does not parse, a unit it
cannot find. Warnings do not fail the command unless you pass `--strict`.

Useful options:

```bash
# Check every test file in a course repo
llmgrader_test check "example_repo/**/tests/*.xml"

# Check against a built solution package instead of the loose unit file
llmgrader_test check unit1/tests/calculus_tests.xml --pkg soln_package.zip

# Fail on warnings too, which is what you want in CI
llmgrader_test check unit1/tests/calculus_tests.xml --strict

# Skip the coverage report
llmgrader_test check unit1/tests/calculus_tests.xml --no-coverage

# One case, or one question's cases
llmgrader_test check unit1/tests/calculus_tests.xml --case missing_limits
```

`--qtag` and `--case` narrow the run to a subset, which turns the coverage
report off: coverage over a subset of the cases would report items the file
does cover.

Quote globs. On Windows the shell does not expand them, and `llmgrader_test`
expands them itself.

### `run` — makes real grading calls

```bash
llmgrader_test run unit1/tests/calculus_tests.xml
```

This grades every case through the same path a student submission takes, using
each question's own `preferred_model`, and compares the result to the
expectations. It uses your API key and costs money.

Useful options:

```bash
# See how many calls a run would make, without making them
llmgrader_test run unit1/tests/calculus_tests.xml --dry-run

# Just one question's cases
llmgrader_test run unit1/tests/calculus_tests.xml --qtag "Exponential derivative"

# Check for flakiness: grade each case three times
llmgrader_test run unit1/tests/calculus_tests.xml --repeat 3

# Would a different model tier grade this course the same way?
llmgrader_test run unit1/tests/calculus_tests.xml --model complex

# Write a readable report to inspect the feedback
llmgrader_test run unit1/tests/calculus_tests.xml --html report.html
```

`--repeat` is worth running before you trust a new set of cases. A case that
passes once but only 2 times in 3 is a case whose band is too tight, and it is
better to find that out now than during grading week.

Such a case is reported as **`FLAKY`**, and `FLAKY` **fails the run**. A case
whose verdict depends on which run you happened to make is not a working test,
whichever way the majority fell — widen the band, or assert on the rubric item
you actually care about instead of the total.

`run` exits `0` when every case passed, `1` when any case failed or came out
flaky, and `2` when it could not start — no API key, a qtag that does not
exist, or a run that would exceed `--max-calls`. A `WARN` on the band edge does
not fail the run.

Two options are worth knowing before you spend anything:

```bash
# Refuse to start if this would cost more than you meant
llmgrader_test run unit1/tests/calculus_tests.xml --repeat 5 --max-calls 20

# Add a dollar estimate to the summary (token counts are always reported)
llmgrader_test run unit1/tests/calculus_tests.xml --cost
```

The dollar figure is derived from the model registry's own rates. Any call
billed at a long-context rate is priced as a lower bound, and the command says
so — treat it as an estimate, not an invoice.

## Reading the report

The terminal output is a summary — enough to see what passed and to locate a
failure:

```
unit1/tests/calculus_tests.xml  (unit: calculus.xml, 4 cases)

  PASS  power_rule_confusion       Exponential derivative  fail
  PASS  log_method_correct         Exponential derivative  pass
  WARN  missing_limits             Integration by parts     6.0  [6-9]   margin 0.0
        on the band edge; widen the band or accept flakiness
  FAIL  sign_error                 Integration by parts     9.0  [3-6]   over by 3.0
        rubric `sign_error_penalty`: expected point_awarded in [-2,-2], got 0.0
        evidence: "The antiderivative is correct throughout."

3 passed, 1 failed, 1 warning
```

The **full grader output** goes to the report files, not the terminal. Both the
JSON report and the `--html` page contain, for every case:

- the question, the submitted test solution, and the score
- the complete student-facing feedback, exactly as a student would see it
- every rubric item's verdict and the evidence the grader cited for it
- which expectations failed
- input and output token counts and latency for the call

The HTML report is the one to open when a case fails for a reason you do not
immediately understand. Reading the grader's own evidence usually shows whether
the rubric condition was ambiguous, the reference solution was incomplete, or
the test case itself was wrong.

It is a single self-contained file with no external assets, so it opens
straight from disk. One consequence: LaTeX in a question appears as source
rather than as typeset maths, because typesetting it would mean loading
MathJax from the network.

Note the `margin` column: it shows how close a passing score landed to the
edge of its band. A case passing with margin 0 is one run away from failing,
and is reported as `WARN`.

Only edges a score could actually cross count. A full-credit control banded
`[9, 10]` on a 10-point part scores 10 every run and cannot go higher, so it
is not on an edge in any useful sense. A band of `[4, 8]` on the same part
that scores 8 *is*, and says so. An exact band such as `[3, 3]` is a
deliberate pin rather than a range, and has no margin to report.

## A suggested workflow

1. Write the question, solution and rubric as usual.
2. Write three or four cases: one correct solution, and one per misconception
   the rubric is meant to catch.
3. Run `check`. Fix anything it reports — this costs nothing.
4. Run `run --repeat 3`. Widen any band that proves unstable, and investigate
   any case that fails outright.
5. Commit the test file alongside the unit.
6. Re-run `check` on every edit, and `run` before deploying a unit or after
   changing the model.

Step 6 is where the effort pays off. The tests turn "I think this still grades
correctly" into something you can verify in a minute.
