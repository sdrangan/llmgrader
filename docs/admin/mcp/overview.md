---
title: Course MCP
parent: Administrator Guide
nav_order: 6
has_children: true
---

# Course MCP

The course MCP publishes a course's material -- units, questions, rubrics,
solutions and lecture slides -- as a set of tools that a student's own AI
assistant can call. A student adds one address to Claude, ChatGPT or VS Code,
and their assistant can then look up the course for itself.

- [Overview](./overview.md) -- this page: what it is, why, and its status
- [Packaging the course material](./package.md)
- [Deploying and enabling it](./deploy.md)

The student-facing instructions are in
[Studying with Your Own AI](../../student/mcp.md).

---

## Status

{: .note }
The course MCP serves questions, rubrics, worked solutions and lecture slides,
openly or behind an optional course access token. Lab instructions and other
documents are next.

| Piece | Status |
| --- | --- |
| Served by the portal at `/mcp`, behind `LLMGRADER_MCP_ENABLED` | Done |
| Optional course access token (`LLMGRADER_MCP_TOKEN`) | Done |
| `list_courses`, `list_units` | Done |
| `list_questions`, `get_question`, `get_rubric`, `get_solution` | Done |
| Lecture slides: `list_materials`, `get_outline`, `search_slides`, `get_slide` | Done |
| Descriptions of slide figures for search (optional, paid once) | Done |
| `llmgrader_mcp_config.xml` and the slide build | Done |
| Unit types, MCP-only units (past exams), `list_unit_types` | Done |
| Printing a unit as a paper exam (`create_qfile --print`) | Planned |
| Lab instructions and other documents | Planned |
| Skill tags in rubrics and a skill list | Planned |

### The tools a student's assistant gets

| Tool | Returns |
| --- | --- |
| `list_courses` | The courses on this portal |
| `list_units` | A course's units in teaching order, with question counts, each unit's `unit_type` and, for past material, its semester |
| `list_unit_types` | Each kind of unit (`problem_set`, `midterm`, ...) with your description of it, and its units |
| `list_questions` | Every question (or one unit's, or one unit type's): unit, qtag, a short label, parts and points |
| `get_question` | One question's full text and figures, and your `variation_guidance` if any |
| `get_rubric` | One question's rubric items and grading notes |
| `get_solution` | One question's worked solution and its figures |
| `list_materials` | The slide decks, by unit |
| `get_outline` | A deck's slide titles |
| `search_slides` | The slides that mention a topic, best match first |
| `get_slide` | One slide's image, text, speaker notes and figure description |

The server also tells every assistant that the material is for studying: help
the student reason toward an answer, use the rubric and solution to check
their work or build a hint, and show the solution only when they ask for it.

**Quick check that it is running:** open `https://<portal>/mcp` in a browser.
*"This is the course MCP server, and it is running."* means the MCP is up; an
HTML **Not Found** page means it is not mounted. See
[Checking that it works](./deploy.md#checking-that-it-works) for what to do
next.

---

## What an MCP is

The **Model Context Protocol** is an open standard for exposing tools to AI
assistants. A server publishes a list of tools -- each a name, a description and
the arguments it takes. The assistant reads those descriptions, decides on its
own when a tool would help answer the user, calls it, and uses the result.

The server contains no AI. Every tool is an ordinary lookup: "return the units
of this course", "return this question's rubric". All of the reasoning happens
on the student's side, in the assistant they already use.

---

## Why an MCP instead of more portal

The obvious way to bring AI help into a course is to build it into the portal:
a chat tab next to each question. LLM Grader deliberately does not, for three
reasons.

**The student already has a better chat than we could build.** Every feature
a portal chat would offer -- explanation, hints, follow-up questions, "give me
another one like this" -- is something the student's own assistant does already,
and keeps improving at without our involvement. A portal chat would be a worse
copy of a tab the student already has open.

**It costs the course nothing to run.** The inference runs on the student's own
subscription. A portal chat would need an API key on the server and a budget
for every student's every question, and there is no way to route that spend to
a consumer subscription.

**What the course can uniquely provide is the material, not the chat.** No
vendor can give a student *this* course's questions, *this* instructor's
rubrics, the worked solutions, and the slides they were taught from. That is
what the MCP publishes. An assistant that can read the rubric gives feedback
aimed at what the course actually grades, rather than at what a generic answer
to the topic looks like.

So the portal keeps doing what only it can -- grading, against the instructor's
rubric, with a record -- and the MCP gives everything else to the assistant the
student already has.

**The portal stays.** Students who do not use an AI assistant, or whose plan
does not allow custom connectors, lose nothing: every question is still
answered and graded on the portal.

---

## How it is served

The MCP is part of the portal: the same Render service, the same process, at
`https://<portal>/mcp`. It reads courses from the portal's own course registry,
so a course package uploaded through the portal is what the MCP serves, with
no separate copy to keep in sync. A course id is resolved the same way as in
the portal's own URLs: an unknown or archived course is an error, never a quiet
fall back to the default course.

It is off unless `LLMGRADER_MCP_ENABLED` is set; see [Deploying](./deploy.md).

---

## What it exposes, and what it does not

Solutions, rubrics and grading notes **are** exposed, for every unit: this is
practice material, and an assistant that cannot see the solution cannot check a
student's reasoning or build a useful hint.

By default anyone with the address can use the MCP, so students need nothing
else and the address can go on the course web page. If you reuse problems and
would rather not leave their solutions readable by anyone, set the optional
token -- see [Deploying](./deploy.md).

Grading notes go to students' assistants as part of `get_rubric`, so keep them
to what you would say to a student: common mistakes and what is accepted, not
remarks meant only for TAs.

What is published is chosen by an explicit list in the
[MCP package configuration](./package.md), never by "everything in the repo":
a course repository typically also holds exams, autograder keys and lab
solution code, none of which should reach a student.

Nothing a student does through the MCP is graded. The portal counts which tools
are called and on which questions and slides, anonymously and never with what
the student asked; see [what is recorded](./deploy.md#what-is-recorded).
