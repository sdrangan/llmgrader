---
title: Course MCP
parent: Administrator Guide
nav_order: 6
has_children: true
---

# Course MCP

The course MCP publishes a course's material -- units, questions, rubrics,
solutions, and course materials such as lecture slides, demos and labs -- as
a set of tools that a student's own AI assistant can call. A student adds one address to Claude, ChatGPT or VS Code,
and their assistant can then look up the course for itself.

- [Overview](./overview.md) -- this page: what it is, why, and its status
- [Packaging the course material](./package.md) -- kinds, units and items
- [Past exams and unit types](./units.md)
- [Material from a public repository](./sources.md) -- demos, labs, docs pages
- [Deploying and enabling it](./deploy.md)

The student-facing instructions are in
[Studying with Your Own AI](../../student/mcp.md).

---

## Status

{: .note }
The course MCP serves questions, rubrics, worked solutions, and every kind of
material a course declares -- slides, demos, labs, handouts -- openly or
behind an optional course access token.

| Piece | Status |
| --- | --- |
| Served by the portal at `/mcp`, behind `LLMGRADER_MCP_ENABLED` | Done |
| Optional course access token (`LLMGRADER_MCP_TOKEN`) | Done |
| `list_courses`, `list_units` | Done |
| `list_questions`, `get_question`, `get_rubric`, `get_solution` | Done |
| Materials: `list_materials`, `get_material`, `read_material`, `search_materials` | Done |
| Kinds, material-only units and items in `llmgrader_mcp_config.xml` | Done |
| Formats: slides, PDFs page by page, docs pages, text and code | Done |
| Policies per kind: open, tutor, private | Done |
| Material from a public GitHub repository, synced (`LLMGRADER_MCP_CODE`) | Done |
| Descriptions of slide and PDF figures for search (optional, paid once) | Done |
| Unit types, MCP-only units (past exams), `list_unit_types` | Done |
| Printing a unit as a paper exam (`create_qfile --print`) | Done |
| Skill tags in rubrics and a skill list | Planned |

### The tools a student's assistant gets

| Tool | Returns |
| --- | --- |
| `list_courses` | The courses on this portal |
| `list_units` | A course's units in teaching order, with question counts, each unit's `unit_type` and, for past material, its semester; a unit that holds only material has type `material` and no questions |
| `list_unit_types` | Each kind of unit (`problem_set`, `midterm`, ...) with your description of it, and its units |
| `list_questions` | Every question (or one unit's, or one unit type's): unit, qtag, a short label, parts and points |
| `get_question` | One question's full text and figures, and your `variation_guidance` if any |
| `get_rubric` | One question's rubric items and grading notes |
| `get_solution` | One question's worked solution and its figures |
| `list_materials` | The course's kinds of material with your description of each, its units, and every item: id, title, kind, units |
| `get_material` | One item: its units and how each was found, its parts (a deck with its outline, docs pages, files), and the slides that cite it |
| `read_material` | One slide or PDF page (image, text, notes, figure description), or one file's lines, with a link the student can open |
| `search_materials` | Slides, PDF pages, docs pages and code that mention a topic or an identifier, best match first |

An **item** is what a student is pointed to: a lecture deck, a demo with its
docs pages and code, a lab with its instructions and starting files, a
handout. You name the kinds; the tools are the same for all of them. See
[Packaging](./package.md#the-model).

The server also tells every assistant that the material is for studying: help
the student reason toward an answer, use the rubric and solution to check
their work or build a hint, and show the solution only when they ask for it.
The same instruction comes with every worked solution, whether it is a
question's (`get_solution`) or an item of a kind you mark `tutor`.

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
rubrics, the worked solutions, and the slides, demos and labs they were
taught from. That is
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

What is published is chosen in the [MCP package configuration](./package.md),
never by "everything in the repo". Material comes from two sources, kept apart
on purpose:

- **The package**: files from any repository, including your private one, by
  **explicit path only**. A course repository also holds exams, autograder
  keys and solutions, and a new one must never be published because nobody
  remembered to exclude it.
- **A public repository** the portal keeps a copy of ([Sources](./sources.md)).
  Patterns such as "one item per folder of `labs/`" are allowed there, because
  everything in it is public already.

Each kind of material has a policy. `open` material is served as it is.
`tutor` material -- worked lab solutions, say -- is served with the
instruction to help the student reason toward the answer. `private` material
is listed by title, so the assistant can say it exists, and never read,
searched, or even built into the package.

Nothing a student does through the MCP is graded. The portal counts which tools
are called and on which questions, materials and files, anonymously and never with what
the student asked; see [what is recorded](./deploy.md#what-is-recorded).
