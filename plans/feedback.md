# Plan: Collapse student feedback to a single field

Status: **decided, not yet implemented** — see Implementation below.
Date: 2026-08-22 (decisions recorded 2026-08-27)
Origin: instructor observation that `full_explanation` no longer earns its keep.

## Motivation

`GradeResult` carries two prose fields:

- `feedback` — student-facing.
- `full_explanation` — originally internal notes.

Two things have eroded the split:

1. `full_explanation` is shown to students in practice anyway, because the
   short `feedback` was not enough to follow the grading reasoning.
2. Its other purpose was to force the model to reason before committing to a
   score. Rubrics now do that job — `rubric_eval` requires per-item evidence.

## Findings from the code

### The rubric templates already demoted the field

Every rubric template says the same thing (`services/prompt.py:225`, `:275`,
`:324`, and the binary variants at `:377`, `:426`, `:474`):

> `"full_explanation"`: a concise grading summary ... **Do not repeat the full
> per-rubric detail already captured in `"rubric_eval"`.**

Meanwhile `rubric_eval.evidence` is specified as *"concise factual evidence ...
This text may be shown to the student"*, and `append_rubric_feedback`
(`services/grader.py:864`) already appends the whole rubric table — id,
description, points, evidence — to `feedback`. So students already receive the
per-item reasoning. In rubric mode `full_explanation` summarizes a table the
student can see.

### The scratchpad effect is already mostly gone

Requested field order in `partial_multi_all` is:

    point_parts -> rubric_eval -> full_explanation -> feedback

The score is emitted **before** any prose. So `full_explanation` is not acting
as think-before-answer today. Moving `rubric_eval` ahead of `point_parts` would
recover far more of that effect than keeping `full_explanation` does. Worth
doing in the same pass.

## Caveats — the real work

### 1. No-rubric questions have no rubric to lean on

`services/prompt.py:761` branches:

    if rubrics:  -> RUBRIC_TEMPLATES
    else:        -> NO_RUBRIC_TEMPLATES

On the `else` branch `full_explanation` is the *only* reasoning surface —
"explain your reasoning step by step" (`prompt.py:50`, `:75`, `:96`, `:123`,
`:147`, `:172`). The premise "rubrics guide the model anyway" is false there.

~~Decision needed: keep the field on the no-rubric path, or declare rubrics
mandatory and delete `NO_RUBRIC_TEMPLATES` (all six keys) outright.~~
**Resolved 2026-08-27** — keep the field on the no-rubric path for now; delete
`NO_RUBRIC_TEMPLATES` only in commit 3, after the rubric backfill. See Decisions
below.

### 2. The field is a diagnostics channel, not just an LLM output

Three non-LLM writers append to `full_explanation`:

| Writer | Location |
|---|---|
| tool usage / tool-call summary | `append_tool_summary`, `grader.py:851`; called at `:1088`, `:1122`, `:1156`, `:1181` |
| grader error text | `invalid_grade`, `grader.py:936` |
| API-key wizard sentinel `__START_API_KEY_WALKTHROUGH__` | `grader.py:1433`, consumed at `static/js/app.js:1648` |

So separate two decisions:

- **stop asking the LLM for it** — yes, low risk;
- **drop the column** — no. Keep `full_explanation` as a backend-populated
  internal diagnostics/audit field. That keeps the SQLite column
  (`grader.py:368`), the admin view, and the key wizard working, and makes the
  change much smaller.

### 3. Instructors lose the cross-item "why" for a contested grade

Rubric evidence is per-item and deliberately avoids revealing the reference
solution. Cross-item judgment lands in `full_explanation`: `one_of` tie-breaks,
double-counting decisions, "the rubric did not resolve this so I used the
grading notes" (`prompt.py:216`). That is the only record if a student disputes
a score.

**Do before deciding:** pull a sample of real submissions from SQLite and read
what the model actually wrote in `full_explanation` on rubric-graded questions.
If it is pure summary, caveat 3 is void. If it carries tie-break reasoning,
fold that into `feedback` as an explicit instruction rather than dropping it.

## Decisions (2026-08-27)

### Caveat 1 resolved: rubrics are *not* universal, and the interim rule is "leave them alone"

Measured over the canonical `units/` files in `hwdesign-soln` (autograder copies
excluded): **46 of 94 questions (49%) carry no rubric items.**

| Unit file | Questions | No rubric |
|---|---|---|
| unit02_fsm/prob/fsm.xml | 8 | 8 |
| unit03_fixp/prob/fixp.xml | 6 | 6 |
| unit04_procif/prob/procif.xml | 7 | 7 |
| unit05_fifo/prob/fifo.xml | 10 | 10 |
| unit06_timing/prob/timing.xml | 6 | 1 |
| demo_unit/simp_lin_reg.xml | 5 | 4 |
| unit04 + unit06 `prob/grade_schema.xml` | 10 | 10 (likely stale duplicates) |
| units 00, 01, 07-10, demo.xml | 42 | 0 |
| **Total** | **94** | **46** |

`example_repo` is 12/12 rubric-graded. No question anywhere has a *partial*
rubric -- every item defaults to `part="all"` -- so per-part coverage gaps do not
exist.

The long-term intent is for rubrics to become universal. Until that backfill
lands, **`NO_RUBRIC_TEMPLATES` stays exactly as it is**: those 46 questions keep
`full_explanation` as their reasoning surface and keep today's grading quality.
They lose only the *display* of the field. That is the accepted interim cost.

When enforcement does arrive, put it in `PromptBuilder.build_task_prompt`
(`prompt.py:761`), **not** in `unit.xsd` or `_validate_unit_semantics` -- a
validation error drops the entire unit file from the site behind a vague banner
(`unit_parser.py:183`), whereas a raise in the prompt builder fails only the one
question and surfaces through the job error path (`routes/api.py:378`).

### The final UI is one box, and the summary is already in it

`grade_post_process` composes `feedback` as **model prose first, rubric table
second** (`grader.py:969` -> `append_rubric_feedback`, `grader.py:880`), and both
halves render into `#feedback-box`. "Full Explanation" is a *separate* box below
it (`grade.html:68-69`). One box is therefore reached by deleting the second box;
no prompt change is required for the layout.

```
+-- Not graded / Correct --- 8 / 10 --- required --+

Feedback
+---------------------------------------------------+
| You set up the timing path correctly and got the  |
| right critical delay, but part (b) used setup     |
| time where hold time was required.                |
|                                                   |
| Rubric evaluation:                                |
| | Criteria           | Points | Evaluation     |  |
| | Part a: Path sum   | 3 / 3  | Summed 4+2+1   |  |
| | Part b: Hold slack | 0 / 2  | Used t_setup   |  |
+---------------------------------------------------+
```

Mobile is the same: `#mobile-feedback` drops its second div.

## Implementation

### Commit 1 -- UI only, no prompt change

Fully reversible; grading behaviour is untouched. Ship this first so the real
layout can be seen before the prompt work starts.

| File | Change |
|---|---|
| `static/views/grade.html` | delete `:68-69` (`<h3>Full Explanation</h3>` + `#full-explanation-box`) and `:24` (`#mobile-explanation-box`) |
| `static/js/app.js` | drop the `ex`/`mex` mirror in `mirrorFeedbackWhenReady` (`:639`), the mirror in `initializeGradeViewMobile` (`:677`), the `explanationBox` branch in `restorePartUI` (`:1226-1235`), and the render at `:1714` |
| `services/grader.py` | fold error detail into `feedback` -- see below |

**Keep** the API-key sentinel at `app.js:1699` (it reads `full_explanation` but
never renders it), the session cache write at `app.js:1734`, and the
`dashboard.js:15` export fallback.

**The error paths must be fixed in the same commit.** Every error path sets a
generic `feedback` and puts the real detail in `full_explanation`; hiding the box
without this makes every failure undiagnosable for the student:

| Path | `feedback` today | detail that would disappear |
|---|---|---|
| `grader.py:1455` | `reason or ""` | API-key walkthrough reason |
| `grader.py:1484` | "Initialization failed." | `Failed to initialize LLM client: ...` |
| `grader.py:1512` | "openai server not responding in time." | timeout values |
| `grader.py:1525` | "The grading request took too long to process." | SDK timeout detail |
| `grader.py:1533` | "There was an error while trying to grade..." | **the 401 / API error text** |

Fold each detail into `feedback`; keep writing `full_explanation` as well, for
the DB column and the admin view.

Between commits 1 and 2, do plan step 1 (sample real `full_explanation` values
from SQLite on rubric-graded questions). It is free and it decides whether the
extra `feedback` sentence in commit 2 is needed or redundant.

### Commit 2 -- prompt change, rubric path only

1. In all six `RUBRIC_TEMPLATES`: delete the `"full_explanation"` field bullet
   and its numbered step (step 7 in `partial_multi_all`), and renumber.
2. Reorder `rubric_eval` ahead of `point_parts` / `points` in both the field list
   and the numbered steps -- this recovers the think-before-scoring effect.
3. Extend the `feedback` bullet: if a `one_of` tie-break or an overlap
   suppression affected the score, require one sentence saying so.
4. `grader.py:801` -- stop reading `raw_grade.get("full_explanation")` on the
   rubric path. The field stays populated by backend writers only.
5. `prompt.py:17` `PROMPT_PREAMBLE` names both fields; update it.
6. Leave `NO_RUBRIC_TEMPLATES` untouched.

Gate with `llmgrader_test run` on `unit01_basic_logic/prob/data_types.xml` or
`unit07_loopopt/prob/loopopt.xml` (both 100% rubric-graded), `--repeat 3`, before
and after. If scores hold, the field was not loadbearing.

### Commit 3 -- later, after the rubric backfill

Delete all six `NO_RUBRIC_TEMPLATES` keys and raise in `build_task_prompt` for a
question with no rubric items. Blocked on authoring rubrics for the 46 questions
above (~32 in live teaching units, once the two stale `grade_schema.xml` files
are confirmed dead and deleted).

## Files affected

| File | What |
|---|---|
| `llmgrader/services/prompt.py` | templates, preamble; `NO_RUBRIC_TEMPLATES` deleted in commit 3 only |
| `llmgrader/services/grader.py` | `:785` parse, error dicts at `:1455`/`:1484`/`:1512`/`:1525`/`:1533` |
| `llmgrader/static/js/app.js` | `:639`, `:677`, `:1226-1235`, `:1714` |
| `llmgrader/static/views/grade.html` | `:24`, `:68-69` |
| `llmgrader/static/js/dashboard.js` | `:15` export fallback -- unchanged |
| `llmgrader/templates/admin_submission_detail.html` | `:211` -- unchanged |
| `tests/services/test_auth.py` | `:178`, `:242`, `:302` stubs return the field -- unchanged |
| `CLAUDE.md` | `:38` describes `GradeResult` |

## Open questions

- ~~Are rubrics now universal in real course packages?~~ Answered above: no, 49%
  of live questions have none. Backfill tracked as commit 3.
- Should the rubric table appended by `append_rubric_feedback` stay verbatim, or
  be trimmed once it is the primary student artifact?
- Are `unit04_procif/prob/grade_schema.xml` and `unit06_timing/prob/grade_schema.xml`
  live or stale? unit06's qtags do not match `timing.xml`, which suggests stale.
