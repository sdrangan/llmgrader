# Plan: Collapse student feedback to a single field

Status: **not started** — analysis only, no code changed.
Date: 2026-08-22
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

Decision needed: keep the field on the no-rubric path, or declare rubrics
mandatory and delete `NO_RUBRIC_TEMPLATES` (all six keys) outright.

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

## Proposed shape

Keep exactly one LLM-authored prose field.

1. Sample real `full_explanation` values (caveat 3) before committing.
2. Decide the no-rubric question (caveat 1).
3. Remove `full_explanation` from the JSON contract in `RUBRIC_TEMPLATES`
   (all six keys) — the field list and step 7 of the numbered instructions.
4. Reorder `rubric_eval` before `point_parts` / `points` in those templates.
5. If caveat 3 bites, extend the `feedback` instruction to require a sentence
   on any cross-item judgment (group tie-breaks, overlap suppression).
6. Keep the `full_explanation` column and `GradeResult` field; populate it only
   from the backend (tool summary, errors, sentinel). Drop
   `raw_grade.get("full_explanation")` at `grader.py:785` on the rubric path.
7. Update `PROMPT_PREAMBLE` (`prompt.py:17`) which names both fields.

## Files affected

| File | What |
|---|---|
| `llmgrader/services/prompt.py` | templates, preamble; possibly delete `NO_RUBRIC_TEMPLATES` |
| `llmgrader/services/grader.py` | `:785` parse, `:936` `invalid_grade`, `append_tool_summary` call sites |
| `llmgrader/static/js/app.js` | `:1207` part render, `:1663` `full-explanation-box`, `:1683` cache |
| `llmgrader/static/js/dashboard.js` | `:15` export falls back to `full_explanation` |
| `llmgrader/templates/*.html` | `full-explanation-box` element; admin detail at `admin_submission_detail.html:211` stays |
| `tests/services/test_auth.py` | `:178`, `:242`, `:302` stubs return the field |
| `CLAUDE.md` | `:38` describes `GradeResult` |

If the field stops being LLM-authored but stays in the schema, the UI and
dashboard changes shrink to "stop showing it to students" only.

## Open questions

- Are rubrics now universal in real course packages, or do no-rubric questions
  still ship? Determines caveat 1.
- Should the rubric table appended by `append_rubric_feedback` stay verbatim,
  or be trimmed once it is the primary student artifact?
