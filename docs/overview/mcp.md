---
title: The Course MCP
parent: Overview
nav_order: 4
has_children: false
---

# The Course MCP: Your AI, the Course's Material

Most AI in education arrives as a walled garden: a tutor chat built into the
platform, running the vendor's model, on the vendor's terms. LLM Grader takes
the opposite approach. It publishes the course -- its problems, rubrics, worked
solutions and lecture slides -- as an **MCP server**, and students connect
**the AI assistant they already use**: Claude, ChatGPT, GitHub Copilot, or
whatever comes next.

This page explains that choice. For setting it up, see the
[administrator guide](../admin/mcp/overview.md); for using it, the
[student guide](../student/mcp.md); for how it works inside, the
[developer guide](../developer/mcp.md).

---

## Two ways to bring AI into a course

**The walled garden.** The platform builds its own AI tutor: a chat panel beside
each question, backed by a model the platform chooses and pays for. The tutor
knows the course material because it lives inside the platform. This is the
common product, from learning platforms' built-in assistants to course-specific
chatbots built on retrieval over uploaded notes.

**The open door.** The platform builds no chat at all. It exposes the course
material through the [Model Context Protocol](https://modelcontextprotocol.io)
(MCP), an open standard that lets any AI assistant call tools provided by
another service. The student adds one address to their own assistant, and from
then on the assistant can list the course's units, open a problem with its
figures, read the rubric it is graded against, check the worked solution, and
find where a topic is taught in the slides -- on its own, whenever a question
calls for it.

LLM Grader does the second.

## Why the open door

**The student's assistant is better than any tutor a course could build.** It is
a frontier model, it improves every few months without the course doing
anything, and it already knows the student: their history, their preferences,
the other courses they take. A built-in tutor would be a weaker copy of a tool
the student has open in the next tab -- and would need rebuilding every time the
models move on.

**It costs the course nothing to run.** Every answer is generated on the
student's own subscription. The MCP server only answers lookups, so it needs no
API key, no per-student budget and no usage cap. A built-in tutor would need all
three, and there is no way to charge its cost to the subscription the student
already pays for.

**What only the course can provide is the material.** No AI vendor can give a
student *this* course's problems, *this* instructor's rubrics and worked
solutions, and the slides they were taught from. That is exactly what the MCP
publishes. An assistant that can read the rubric gives feedback aimed at what
the course actually grades, rather than at what a generic answer to the topic
looks like; an assistant that can read the slides can say *"this is on slide 31
of the processor-interfaces deck"* and give the student the link.

**The course stays in control of its material, not of the conversation.** The
instructor decides what is published -- an explicit list, never "everything in
the repository" -- and can describe how it should be used: the server tells
every assistant that this is study material, to help the student reason toward
an answer and show a solution only when asked. What the student and their
assistant do with it is theirs.

## What it changes, and what it does not

- **Grading stays where it was.** Graded work is still answered and submitted on
  the LLM Grader portal, against the instructor's rubric, with a record. The MCP
  is for studying, and nothing done through it is graded.
- **"Give me another problem like this" becomes unlimited.** The assistant has a
  worked example, its rubric and the instructor's guidance on what may vary, so
  it can write fresh practice problems at the right level, on demand, and check
  the student's answers against the original rubric. The course does not need
  more problems -- it needs sharper ones, because each one seeds many more.
- **Nothing about the student is collected.** The server records which tools are
  called and which problems and slides are asked about, to show the instructor
  how the material is used. It never records what the student typed, and it has
  no identity to record: there is no login. See
  [what is and is not recorded](../admin/mcp/deploy.md#what-is-recorded).
- **Students without an AI subscription lose nothing.** Every problem is still on
  the portal. Claude's free plan currently allows one custom connector, which is
  enough for a course; other assistants vary.

## The honest limits

- **It assumes students use an AI assistant.** For most students today that is
  true; for the rest, the portal remains the whole course.
- **The instructor does not see the conversations.** Only which material was
  looked at, and how often. That is a deliberate privacy line, and it also means
  the MCP cannot tell an instructor *how* a student is struggling, only *where*.
- **Solutions are readable by anyone with the address**, unless the instructor
  sets an access token. That suits practice material, and is the instructor's
  choice per course.
- **It is new.** The protocol is still evolving -- its 2026 revision removed
  sessions to make servers scale like ordinary web APIs -- and LLM Grader's MCP
  will evolve with it.

## Why not RAG?

People often assume a course AI means retrieval-augmented generation: chunking
the notes, embedding them, and searching a vector database. LLM Grader does not,
at least for now. A course's problems and slides are small and highly structured
-- a whole course's problem index fits in a few thousand tokens -- so the server
publishes the structure and lets the student's assistant navigate it, the way a
person would use a table of contents. The [developer guide](../developer/mcp.md)
explains how that works and when retrieval would earn its place.
