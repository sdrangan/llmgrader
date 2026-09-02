---
title: Testing the Autograder
parent: Gradescope Integration
nav_order: 5
has_children: false
---

# Testing the Autograder with a Built Submission

## Overview

After you upload `autograder.zip`, Gradescope offers to test it against a
student submission. That is a genuinely useful check — it is the only way to
see the score Gradescope will actually display before a student sees it — but
the only thing that counts as a submission is the zip the portal's **Download
submission** button produces. Getting one means opening the portal, answering
every required question in the unit, waiting for each to grade, and
downloading.

If you have already written [grading test cases](../buildcourse/solntest.md)
for the unit, you have those answers written down. `llmgrader_test run
--gradescope` grades them the usual way and then writes the same zip the portal
would have written, so testing the autograder costs one command instead of a
session in the browser.

```bash
llmgrader_test run unit1/tests/calculus_tests.xml --gradescope --first-case
```

```
  PASS  by_parts_partial       Integration by parts    6 [4-8]     margin 2   gpt-5.6-luna
  PASS  graphing_partial       Exponential graphing    a=5 [4-5]   margin 1   gpt-5.6-terra

2 passed, 0 failed
2 calls, 0.8 s, 3,702 in / 168 out
report: local_data/gradetests/report.json

gradescope submission: 13/20
  Integration by parts            6/10   case by_parts_partial
  Exponential graphing            7/10   case graphing_partial
  folder: /courses/unit1/submission
  zip:    /courses/unit1/submission.zip
```

Upload that `.zip` under **Configure Autograder → Test autograder**. Gradescope
should come back with 13/20 and the same per-question breakdown, because the
autograder does nothing but read the file. If it reports something else — most
often 0 — the autograder is not reading the submission, and that is exactly
what you wanted to find out before the assignment opened.

This makes real grading calls and costs money, the same as any other
`llmgrader_test run`. It is one call per question, so it is a small run; check
it first with `--dry-run`.

## Choosing which answer goes in

A test case file holds several cases per question — a correct solution, and one
per misconception the rubric is meant to catch. A submission holds one answer
per question. So something has to choose, and `--gradescope` will not choose
silently.

**A question with one selected case answers itself.** If your run has exactly
one case for each question, nothing more is needed:

```bash
llmgrader_test run unit1/tests/calculus_tests.xml \
    --case by_parts_partial --case graphing_partial --gradescope
```

`--case` is the same filter it always was: it narrows the run, and here it also
narrows the submission to one answer per question. Naming the cases explicitly
is the most useful form, because you choose what the submission scores — a
full-credit case for one question, a partial-credit case for another, a zero
for a third — and you know before you upload what Gradescope should display.

**A question with several selected cases is an error**, naming the cases that
competed:

```
error: --gradescope: qtag 'Integration by parts' has 3 selected cases
(`by_parts_full`, `missing_limits`, `forgot_half_in_v`), and a submission holds
one answer per question. Choose one with --case, or pass --first-case to take
the first in document order.
```

**`--first-case` accepts document order.** When you want a submission from a
whole test file without listing case ids, this answers each question with the
first case written for it:

```bash
llmgrader_test run unit1/tests/calculus_tests.xml --gradescope --first-case
```

Whichever way you choose, the run still grades every case you selected and
reports on all of them as usual — the submission is written alongside the
normal report, not instead of it.

## What gets written

`--gradescope` takes an optional directory:

| Form | Writes |
|---|---|
| `--gradescope` | `./submission/` and `./submission.zip` |
| `--gradescope DIR` | `DIR/` and `DIR.zip` |

The default is deliberately a plain name rather than one built from the unit
title. The folder is written into the unit's own directory, where the title
would add length without adding information — and a title with a colon in it
is not a legal Windows path. The unit is named on the first line of
`results.txt` if you need to tell two of them apart.

You get both the folder and the zip because the folder is what you read and the
zip is what you upload. The folder holds exactly what the portal puts in a
download:

| File | Content |
|---|---|
| `results.json` | The Gradescope results file: a total score, and one entry per **required** question with its score, its maximum and the feedback |
| `results.txt` | The same feedback laid out to be read, one block per question |
| `signature.txt` | Only for a unit with `<digitalsign>true</digitalsign>` — see below |
| `images/<qtag>/` | Any images the cases attached, as a student's uploaded work would appear |

The folder is rebuilt from scratch on each run, the way `build_autograder`
rebuilds `autograder/`. A directory that does not look like a submission — one
with files in it and no `results.json` — is refused rather than deleted, so a
mistyped path cannot take your course repository with it.

### Questions with no case

Only **required** questions go into a submission, because those are the only
ones the portal submits. A required question that none of the selected cases
answers is still in the file, scoring 0 with no feedback — exactly what a
student who skipped it would upload. That is a useful thing to test on purpose:
it is the case where a Gradescope assignment's **Autograder Points** setting
disagrees with the unit's total.

A case answering an **optional** question is dropped, and the run says so:

```
  note: 1 case(s) answer optional questions and are not in the submission
  (log_method_correct); the portal submits required questions only.
```

## Signed units

If the unit has `<digitalsign>true</digitalsign>`, the portal signs each
submission and the autograder verifies it. A built submission is signed the
same way, with the private key from `LLMGRADER_PRIVATE_KEY`:

```bash
export LLMGRADER_PRIVATE_KEY=...   # the key generate_signing_keys produced
llmgrader_test run unit1/tests/calculus_tests.xml --gradescope --first-case
```

The run refuses to start if the unit is signed and the variable is not set. An
unsigned zip would be rejected by the autograder with a message telling the
student to re-download from the portal — accurate for a student, and no help at
all when the real problem is a missing environment variable on your machine.
The public half must be the one `build_autograder` embedded in the zip you
uploaded; see [Submission Signing Keys](../setup/gskeys.md).

One consequence: the signature covers the exact bytes of `results.json`, so
editing that file by hand invalidates it. For a signed unit, re-run the command
rather than editing the folder.

## Options

Everything on [`llmgrader_test run`](../buildcourse/solntest.md) still applies.
These are the two this page adds:

| Option | Meaning |
|---|---|
| `--gradescope [DIR]` | Also write a submission: the folder `DIR` and `DIR.zip` beside it. Defaults to `./submission` |
| `--first-case` | When a question has several selected cases, answer it with the first in document order instead of refusing to choose |

And these interact with it:

| Option | Interaction |
|---|---|
| `--case ID` | Narrows the run, and so chooses which case answers each question |
| `--dry-run` | Prints the path it would write and which case would answer each question, and makes no calls. This is where an ambiguous question or a missing signing key shows up, for free |
| `--repeat N` | Grades each case N times as usual; the submission uses the first grade, since a student submits one answer, not N |
| `--fail-fast` | Refused with `--gradescope`: it stops the run at the first failing case, which leaves questions with no grade to submit |

A run whose submission could not be written exits non-zero and says why, even
when every case passed — the JSON and HTML reports are still written, so a run
is never wasted on a submission that failed to build.

## A suggested workflow

1. Build and upload the autograder as usual — see
   [Building the Gradescope Autograder](./gradescope.md).
2. Pick the answers you want to test with, and check the plan for free:

   ```bash
   llmgrader_test run unit1/tests/calculus_tests.xml \
       --case by_parts_partial --case graphing_partial --gradescope --dry-run
   ```

3. Drop `--dry-run` and note the score the run prints.
4. Upload the `.zip` under **Configure Autograder → Test autograder**.
5. Check that Gradescope displays the same score and the same per-question
   breakdown.

Step 5 is the whole point. The autograder does no grading of its own, so any
disagreement between the two numbers is a problem with the assignment
configuration or the upload — and it is far better to find it now than from a
student in week 10.
