# Plan: practice grading through the course MCP

Two new course MCP tools let a student's own AI grade an answer the way the
portal would: same prompt, same scoring and the same feedback layout. The
grade itself comes from whatever model the student is chatting with, so the
result is a **practice estimate** and never a grade for credit.

```
student: "here's my answer to 3b, how would it score?"
  AI → get_grading_prompt(course_id, unit, qtag, part="b")
       ← the portal's grading prompt, the reply schema, solution figures
  AI    grades the answer from the chat against that prompt
  AI → score_grade(course_id, unit, qtag, part="b", grade={...})
       ← validated GradeResult: points, max_points, feedback table
  AI    shows the student the feedback and says it is an estimate
```

## Motivation

A student working in Claude or Gemini already asks "is this right?", and the
AI already has what it needs to answer: `get_rubric` returns the rubric and
`grading_notes`, and `get_solution` returns the worked solution. What it
lacks is the portal's own way of grading:

- **The prompt.** `PromptBuilder` picks one of six templates from the
  question's `partial_credit` mode and its parts, and adds the
  `rubric_total` rule (`sum_positive`, `sum_negative`, `flexible`). An AI
  improvising from `get_rubric` applies none of this, so its "7/10" can mean
  something different from the portal's 7/10.
- **The arithmetic.** `Grader.grade_post_process` strips scores from
  feedback-only items, totals part points, classifies results, and builds
  the rubric table students see on the portal. Models add up points
  unreliably; the server can do the sums instead.

So both tools are thin wrappers over code the portal already runs. Neither
tool calls a model.

## What already exists

| Need | Already in the tree |
| --- | --- |
| The grading prompt | `Grader.build_task_prompt(question, student_soln, part_label)` → `PromptBuilder.build_task_prompt` (`services/prompt.py`) |
| The reference-image annotation | `_build_message_content` (`services/grader.py`), which appends the `--- REFERENCE SOLUTION IMAGES ---` line |
| Reply schema | `GraderRawResult` (`services/grader.py`) |
| Scoring and the feedback table | `Grader.grade_post_process(...)` → `GradeResult` |
| Question lookup with helpful errors | `content.resolve_question` |
| Solution figures, sized and labelled | `content.solution_figures`, `server._with_figures` (JSON last, for Gemini) |
| Tutor posture | `content.TUTOR_INSTRUCTION` |
| Usage logging with redaction | `coursemcp/usage.py`: `IDENTIFIER_ARGUMENTS`, `REDACTED_ARGUMENTS` |

## Design decisions

### 1. The model call stays on the client (no OpenAI call from the MCP)

The other option was for the MCP to call OpenAI itself. Rejected, for three
reasons:

- **The key has nowhere safe to come from.** A key passed as a tool argument
  ends up in the chat transcript and the AI vendor's logs. Using the
  instructor's admin key means paying for every call, and the MCP has no
  per-student identity to limit use by.
- **It would block the Render worker.** The portal has one sync worker and a
  grading call takes 30–60 s. A synchronous tool would freeze every
  student's grading for that long; making it asynchronous means a job id
  plus polling, which chat clients handle poorly.
- **It repeats the portal.** The portal already grades with the real model
  and the student's own key, and only the portal produces a signed
  submission for Gradescope. An MCP grade would be an unsigned second copy
  of that.

Both new tools are local computation only. They should answer in
milliseconds, and a test holds them to a time limit.

### 2. The student's answer never goes to the server for the prompt

`get_grading_prompt` takes **no answer argument**. It calls
`build_task_prompt` with an empty student solution, so the prompt ends at
`--- STUDENT SOLUTION ---`, and the result's `instruction` tells the AI that
the student's answer from the conversation goes there. The student's words,
and any photo of handwritten work, never reach the server for this step.

`score_grade` does have to receive the AI's grade, and its `evidence` and
`feedback` fields paraphrase the student's work. The `grade` argument goes
in `REDACTED_ARGUMENTS`; it is used for the one computation and is not
logged, written to `submissions` or kept anywhere else.

### 3. The prompt is exactly the portal's, byte for byte

The tool returns `build_task_prompt(question, "", part)` with the image
annotation from `_build_message_content`, and nothing reworded. Students
don't read this text; it exists so the AI grades the way the portal does.
A test compares it with what `Grader.grade` would send for the same
question and part, so a later template change can't make the two drift.

The template's own instruction to "return exactly one valid JSON object and
nothing else" is written for the API. For a chat model, the `instruction`
field sets it in context: produce that JSON, pass it to `score_grade`, and
don't show the raw JSON to the student.

### 4. Same availability as `get_solution`

The prompt contains the reference solution and grading notes, so
`get_grading_prompt` is available exactly when `get_solution` is: the same
`require_course` and `resolve_question` path, nothing extra. Its
instruction also carries the tutor rule, because the AI now holds the
worked solution and shouldn't paste it into its feedback unless the student
asks. (It is reworded rather than `TUTOR_INSTRUCTION` spliced in, which read
as "the prompt contains the worked solution: This is a worked solution".)

### 5. `score_grade` uses the portal's post-processing and does not second-guess it

It validates `grade` against `GraderRawResult` and runs `grade_post_process`
with the question's `partial_credit`, parts, rubrics and `rubric_total`. That
reproduces what the portal does with a model's reply, including clamping,
dropping awards on feedback-only items, part totals, and the rubric table
in `feedback`.

It adds no checks of its own. The portal already re-totals points from
`rubric_eval` under `sum_positive` and `sum_negative`, and that total wins
over the model's own `points` and `point_parts`. Any extra check here
would make the estimate disagree with the portal.

A malformed grade is a `ToolError` that names the failing fields and the
expected shape, so the AI can fix it and call again. An error is better
than a guessed score.

`grade_post_process` always appends a `Tools: ...` line to
`full_explanation`. Pass the question's `tools` through, the same as the
portal, and accept the line.

### 6. Every result says it is an estimate

The result carries `estimate: true` and a fixed `disclaimer`: the grade came
from the student's AI, not from the model the portal uses, and only a
submission on the portal counts. The server instructions change to match.
The sentence "nothing done through these tools is graded" becomes roughly:
"get_grading_prompt and score_grade give a practice estimate in the
portal's format; only the portal grades for credit." Different models grade
differently, and a model talking to a student tends to be lenient, so the
label matters more than any polish on the tool.

## Tools

```python
@mcp.tool()
def get_grading_prompt(course_id: str, unit: str, qtag: str,
                       part: str = "all") -> list:
    """... returns, JSON last (after the solution figures):
    {
      "unit", "qtag", "part",
      "grading_mode": "partial_multi_single",      # PromptBuilder.get_grading_mode
      "max_points": 4.0,                           # max_points_part
      "prompt": "...",                             # the portal's task prompt
      "response_schema": {...},                    # GraderRawResult.model_json_schema()
      "instruction": "...",                        # see decisions 2-4
    }
    """

@mcp.tool()
def score_grade(course_id: str, unit: str, qtag: str, grade: dict | str,
                part: str = "all") -> dict:      # str: a client that sends JSON text
    """... returns GradeResult.model_dump() plus
    { "unit", "qtag", "part", "estimate": true, "disclaimer": "..." }
    """
```

`part` is checked against the question's part labels, and an unknown one is
a `ToolError` listing the valid labels, the same way `resolve_question`
handles an unknown qtag.

## Changes

| File | Change |
| --- | --- |
| `llmgrader/coursemcp/server.py` | the two tools in `_add_content_tools` (or wherever `get_solution` is registered); update `CONTENT_INSTRUCTIONS`; update the `log_call` docstring ("these tools are never sent it" is no longer true of `score_grade`) |
| `llmgrader/coursemcp/content.py` | `GRADING_INSTRUCTION`, `ESTIMATE_DISCLAIMER`; a `resolve_part` helper |
| `llmgrader/coursemcp/usage.py` | `part` → `IDENTIFIER_ARGUMENTS`; `grade` → `REDACTED_ARGUMENTS` |
| `llmgrader/services/grader.py` | possibly split the image annotation out of `_build_message_content` so the MCP reuses it rather than copying the string |
| `docs/admin/mcp/overview.md`, `deploy.md` | add both tools to the tool tables |

## Tests (`tests/coursemcp/test_course_grading.py`)

- **Prompt parity:** for one question in each of the six grading modes, the
  tool's `prompt` equals `Grader.build_task_prompt(question, "", part)` plus
  the image annotation when the question has solution images.
- **No answer argument:** the tool's input schema has no free-text
  parameter beyond the identifiers. This guards decision 2.
- **Scoring parity:** a fixed `GraderRawResult` gives the same `GradeResult`
  through `score_grade` as through `grade_post_process`, for a multi-part
  partial-credit question, a binary question, and a question with a
  feedback-only item that the AI scored anyway (the score is stripped).
- **Malformed grade:** a missing `feedback` field or a string for `points`
  gives a `ToolError` that names the field.
- **Rubric totals win:** a `point_parts` that disagrees with the rubric
  awards is overridden by them, as on the portal.
- **Portal error:** a reply the portal would mark `error` (no awards, no
  `point_parts`) is a `ToolError` that says to call again.
- **Unknown part:** a `ToolError` that lists the valid part labels.
- **Usage:** the existing argument-coverage test in `test_mcp_usage.py`
  covers `part` and `grade`; add a test that a `score_grade` row never
  contains any text from `grade`.
- **No model call, no wait:** with the OpenAI client patched to raise, both
  tools still succeed, within a one-second limit.

## Out of scope

- Grading for credit, signing, or Gradescope output. That stays on the
  portal.
- Storing practice grades or showing them in Analytics. The usage row
  records that `score_grade` was called on a question, which is enough to
  see whether the tools are used.
- Calling OpenAI from the MCP, including with an instructor key (decision 1).
- A UI "render" tool. MCP results are shown by the client; the `feedback`
  markdown table is the rendering.

## Open questions

- **Rate of use on exam units.** Exam units are already fully readable
  through `get_solution`, so this adds no exposure. Still worth checking
  the usage data after a few weeks to see whether students grade past
  midterms this way.
- **Client compliance.** Whether Claude and Gemini actually call
  `score_grade` rather than presenting their own total. If they don't, a
  stronger `instruction`, or folding a "how to grade" note into
  `get_question`'s description, is the next thing to try.

## Implementation status, 2026-10-14

Built as planned, in `coursemcp/content.py` (`grading_prompt`,
`score_grade`, `resolve_part`, the instruction and disclaimer texts) and
`coursemcp/server.py` (the two tools). Tests are in
`tests/coursemcp/test_course_grading.py`, plus a redaction test in
`test_mcp_usage.py`.

Where the build differs from the plan:

- **Rubric totals.** Decision 5 originally proposed a `note` when the
  rubric awards did not add up to `points`. `grade_post_process` already
  re-totals from `rubric_eval`, so there is nothing to note, and the note
  was dropped.
- **No change to `grader.py`.** `_build_message_content(task, solution_images,
  [])` gives the image annotation as it is, so it was not split.
- **The placeholder is text, not empty.** The portal's image annotation
  comes after the student solution, so an empty answer would leave the
  prompt's end ambiguous. `STUDENT_ANSWER_PLACEHOLDER` stands where the
  answer goes.
- **A portal "error" becomes a ToolError.** When the AI's reply is
  structurally incomplete (for example no awards and no `point_parts`
  on a multi-part question), `grade_post_process` returns result `error`.
  The tool turns that into a `ToolError` with the reason, so the AI can fix
  the reply instead of showing the student "error".
- **`grade` may be a JSON string.** Some clients send an object argument
  as its text.
- **Rubric row order is the order of the keys sent.** Flask's test client
  sorts JSON keys, so the parity test sorts too; a real client keeps the
  order the AI wrote.
