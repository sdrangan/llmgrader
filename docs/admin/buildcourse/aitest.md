---
title:  Testing with AI Answers
parent: Building a Course Package
nav_order: 6.5
has_children: false
---

# Testing with AI Answers

## Overview

`llmgrader_answer` has a model sit your unit the way a student would: it sees
the **question text alone** — no solution, no rubric, no grading notes — and
writes an answer to each question. The answers go into a `<unit_test>` file,
the same format as the hand-written cases in
[Testing your grading](./gradetests.md), so `llmgrader_test` can grade them
exactly as it grades any other test file.

```bash
llmgrader_answer unit1/calculus.xml --out unit1/tests/ai_answers.xml
llmgrader_test run unit1/tests/ai_answers.xml --html ai_report.html
```

The first command writes the answers. The second grades them against your
rubric and produces a report you can read. The two are deliberately separate:
once an answer is in the file it is frozen, so you can re-grade the same
answers after every rubric edit without paying for new ones.

## Uses

Why answer your questions with an independent model at all? There are three
reasons, and the obvious one is the least useful.

**It is a rubric stress test — the main reason to run it.** When a strong model
answers a question blind and scores 3 out of 10, the usual cause is not that
the model is weak. It is that the question is under-specified, or that a rubric
item keys on phrasing rather than substance. You cannot get that signal from
your own test cases, because you write those already knowing what the rubric
wants. A blind answer is the closest thing available to a naive but competent
student.

**It seeds your grading tests.** The cases that are tedious to write by hand are
the "good but not perfect" ones — the near-misses that decide whether a rubric
is tuned. Those are exactly what a model produces unprompted. The output file
is designed to be *edited into* a real test file: read each answer, decide what
it is worth, write the band in, and keep it.

**And it tells you how the model did**, which is the part you were curious
about.

### Reading a low score

Read this before you read any number the tool produces. A low score is
**first** evidence about your question and your rubric, and only **second**
evidence about the model. When an answer scores badly, check these causes in
order:

1. **The question does not ask for what the rubric rewards.** A rubric item for
   "states the limit as x → ∞" against a question that only says "sketch the
   function" asks for something the student was never told to provide. Every
   student loses that point, and your own test cases would never show it,
   because you wrote them knowing the item was there.
2. **A rubric item keys on phrasing.** "Student writes *u = x* and
   *dv = e^{2x} dx*" fails a student who chose the same substitution and named
   it differently. The grader is reading for the words, not the substance.
3. **The question has a figure the model could not see.** See
   [Questions with images](#questions-with-images). If the run warned about
   unresolved images, stop here — that score means nothing.
4. **The model genuinely could not do the problem.** This happens, and it is
   worth knowing. It is the last thing to conclude, not the first.

The useful output of a run is not the score. It is the list of rubric items
that a correct-looking answer failed to earn.

## Running the AI answer tool

### Syntax

```
llmgrader_answer UNIT.xml [UNIT.xml ...]
                 [--pkg PATH] [--qtag TAG]... [--model ID|TIER]
                 [--repeat N] [--jobs N] [--timeout SEC]
                 [--out FILE] [--force] [--expect full]
                 [--dry-run] [--cost] [--api-key KEY] [-v] [-q]
```

| Option | Meaning |
| --- | --- |
| `--dry-run` | Print how many calls the run would make and to which models. Makes no calls and needs no key. |
| `--cost` | Add a dollar estimate from the model registry's rates. |
| `--qtag TAG` | Answer only this question. Repeatable. |
| `--model ID\|TIER` | Answer every question with this model, instead of each question's own. A tier name (`simple`, `standard`, `complex`) or a model id. |
| `--repeat N` | Answer each question N separate times, as N cases. |
| `--out FILE` | Where to write the answers. Default: `<unit>_answers.xml` in the current directory. |
| `--force` | Overwrite `--out` if it already exists. Without it, the tool refuses. |
| `--expect full` | Write a full-credit assertion into every case. See [Verifying the answers](#verifying-the-answers). |
| `--pkg PATH` | Read the unit from a built solution package, so question images resolve. |
| `--api-key KEY` | Key to call the model with. Default: the `OPENAI_API_KEY` environment variable. |
| `-v` | One status line per answer: `ok`, `empty`, `refused`, or `error`. |

By default each question is answered by the model your course would *grade* it
with — its `preferred_model`, falling back to the `simple` tier default — so an
unflagged run mirrors your own configuration.

Check the cost before the first run. It is free:

```
$ llmgrader_answer unit1/calculus.xml --dry-run --cost

dry run: 3 calls across 3 questions
  gpt-5.6-luna                 2
  gpt-5.6-terra                1

unit1/calculus.xml  ->  calculus_answers.xml
  Exponential derivative      gpt-5.6-luna
  Integration by parts        gpt-5.6-luna
  Exponential graphing        gpt-5.6-terra

estimated cost $0.0136
```

Some useful variations:

```bash
# One question only
llmgrader_answer unit1/calculus.xml --qtag "Exponential derivative"

# Three independent attempts at each question, as three cases
llmgrader_answer unit1/calculus.xml --repeat 3

# Would a stronger model do better? If not, suspect the question.
llmgrader_answer unit1/calculus.xml --model complex
```

If a qtag has whitespace in it — several words with spaces between them — put
it in quotes. Otherwise the shell splits it into separate arguments, and only
the first word is taken as the qtag:

```bash
llmgrader_answer data_types.xml --qtag "addition overflow"
```

To answer several questions, repeat the flag:
`--qtag "addition overflow" --qtag "sign extension"`. The match is exact and
case-sensitive against the `qtag` attribute in the unit XML.

`--repeat` is worth using on a question you suspect is ambiguous. Three answers
that cover different things and score differently point to a question that
does not say what it wants. Answers are generated at temperature 0 where the
model allows it, so the variation you see is the model's own, not something
you asked for.

`--out` names one file, and a `<unit_test>` file targets one unit. A run over
several units must therefore leave `--out` off; each unit gets its own
`<unit>_answers.xml`.

### Seeing the answers

The answers are plain text inside the output file. Open it in any editor:

```xml
<unit_test unit="../calculus.xml">

  <!--
    Generated by llmgrader_answer on 2026-09-11 from calculus.xml.

    Every answer below was produced from the question text alone: no
    solution, no rubric, no grading notes. ...
  -->

  <case id="ai_exponential_derivative_1" qtag="Exponential derivative">
    <description>gpt-5.6-luna answered this from the question text alone: no solution, no rubric, no grading notes.</description>
    <solution><![CDATA[ ... the model's answer, verbatim ... ]]></solution>
  </case>

</unit_test>
```

- **`<solution>`** holds the model's answer, exactly as it came back.
- **`<description>`** records which model wrote it. It also notes anything you
  should know before trusting the answer: that it came back empty, that the
  model refused, or that it was written without seeing a figure.
- **Case ids** are built from the question's qtag and are stable, so re-running
  the tool gives a readable diff rather than a reshuffle. The `ai_` prefix
  marks a generated case once the file also holds hand-written ones.

To read the answers **alongside how they were graded**, grade the file with an
HTML report:

```bash
llmgrader_test run unit1/tests/ai_answers.xml --html ai_report.html
```

For each case the report shows the question, the submitted answer, the score,
the grader's evidence for every rubric item, and the feedback a student would
have seen. This is the best place to read the answers, because the rubric
problems show up in the evidence column, not in the score.

`-v` on `llmgrader_answer` is only a quick triage. It lists each answer's status
(`ok`, `empty`, `refused`, `error`) but not its text.

### Empty and refusing answers are kept

If the model returns nothing, or declines to answer, the case is still written
to the file, with a note in its `<description>`. It is never dropped. That is
deliberate: a blank answer that goes on to score well is the most valuable
thing this tool can find, because it means the grader is awarding points for
nothing.

A call that *fails* — a timeout, a network error, an expired key — is
different. There is no answer, so no case is made up for it. The failure is
named in the summary and the command exits `1`.

### Questions with images

This caveat matters most, because it is the one that produces a
plausible-looking number that is worthless.

If a question's text embeds an image, the model has to see the figure to
answer. `llmgrader_answer` attaches question images to the call, but an image
stored in the package's assets only resolves inside a **built solution
package**. A run over a loose unit file may not find it, and the tool says so
for each affected question:

```
  warning: 'Exponential graphing' has 1 question image(s) that did not
  resolve; the model answers without seeing them.
  Build a solution package and pass --pkg to fix this.
```

The same warning is written into that case's `<description>`, so it follows
the answer into the grading report. To fix it, build the package and point at
it:

```bash
create_soln_pkg
llmgrader_answer unit1/calculus.xml --pkg soln_package.zip --out unit1/tests/ai_answers.xml
```

An image-free unit needs none of this and works from the loose unit file.

### Exit codes

`0` every question was answered and the file was written. `1` at least one
call failed. `2` the run could not be performed at all — a missing unit, a
`--qtag` that matched nothing, no API key, or an output file that already
exists without `--force`.

## Verifying the answers

By default the generated cases **assert nothing**: they record what the model
said and leave the verdict to you. To set up an automatic test that a model
answers your questions correctly, have the tool write the assertion for you.

### Assert full credit with `--expect full`

```bash
llmgrader_answer unit1/calculus.xml --expect full --out unit1/tests/ai_answers.xml
```

Every case then claims that the answer earns full marks:

- a **binary** question gets `<expected_result>pass</expected_result>`
- a **partial-credit** question gets, for each part, a minimum equal to that
  part's full points and no maximum

Now `llmgrader_test run` reads as a pass/fail test of the model:

```bash
llmgrader_test check unit1/tests/ai_answers.xml --no-coverage   # free
llmgrader_test run   unit1/tests/ai_answers.xml --html ai_report.html
```

`pass` means the answer earned full credit. `fail` means it did not, and the
report says which part or rubric item it lost points on. The summary line —
"2 passed, 1 failed" — is the model's score on your unit. `llmgrader_test run`
exits `1` if any case fails, so it can sit in a script.

`--no-coverage` is there because `check` normally lists every rubric item that
no case asserts on. A file of blind answers asserts on no rubric item by
design, so without the flag you get one warning per item. They are harmless —
`check` still exits `0` — but they are noise here.

### When a case fails

Open the report and decide which of the four causes in
[Reading a low score](#reading-a-low-score) it was.

- **The rubric or the question was wrong.** Fix the unit, then re-run
  `llmgrader_test run`. The answer is frozen in the file, so the rubric is the
  only thing that changed, and the case passing now tells you the fix worked.
- **The model was genuinely wrong.** Do not leave a full-credit claim on an
  answer you know is wrong; it will fail forever. Either delete the case, or —
  better — turn it into a real test by replacing the assertion with the score
  you believe the answer deserves:

```xml
  <case id="ai_integration_by_parts_1" qtag="Integration by parts">
    <description>...</description>
    <solution><![CDATA[ ... ]]></solution>

    <!-- Edited by hand: the setup is right, the limits were never applied. -->
    <expected_points>
      <part label="all" min="4" max="8"/>
    </expected_points>
    <expected_rubrics>
      <item id="apply_limits" min="0" max="0"/>
    </expected_rubrics>
  </case>
```

Rewrite the description in your own words while you are there. The result is
an ordinary grading test; see [Testing your grading](./gradetests.md) for
what each assertion means.

### Keeping it as a standing test

Commit `ai_answers.xml` next to your other test files and re-run it whenever you
edit the unit:

```bash
llmgrader_test run unit1/tests/ai_answers.xml
```

This re-grades the **stored** answers, so it costs only the grading calls and
isolates your rubric as the thing under test. Two kinds of repetition are
available, and they test different things:

| Command | What it repeats | A mixed result means |
| --- | --- | --- |
| `llmgrader_answer --repeat 3` | Three different answers to each question | The question is ambiguous: the model reads it three ways. |
| `llmgrader_test run --repeat 3` | Three gradings of the same answer | The rubric is ambiguous: the grader cannot decide. `run` reports this as `FLAKY`, which counts as a failure. |

Regenerate the answers with `llmgrader_answer` only when you want a fresh
attempt — a new model, or a rewritten question. Because the tool will not
overwrite a file you have edited, write the new answers to a new file, or pass
`--force` if you really mean to replace them.

## What this does not do

- **It does not grade.** That is `llmgrader_test run`.
- **It does not know whether an answer is right.** It records what the model
  said; the verdict comes from your rubric, which is the point.
- **It is not a benchmark.** One run over one unit with one model is a
  starting point for a conversation about your rubric, not a measurement.
