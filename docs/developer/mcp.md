---
title: How the course MCP works
parent: Developer Guide
nav_order: 4
has_children: false
---

# How the Course MCP Works

The course MCP lets a student's own AI assistant read the course: its units,
problems, rubrics, worked solutions and lecture slides. This page is how it is
built. For why it exists, see [The Course MCP](../overview/mcp.md); for
deploying it, the [administrator guide](../admin/mcp/deploy.md).

**The short version: there is no RAG.** No chunking, no embeddings, no vector
database, and no language model on the server at all. The server publishes the
course's structure through a handful of lookup tools, and the student's
assistant navigates it the way a person uses a table of contents.

---

## The request path

The MCP is not a separate service. It is mounted inside the same Flask portal
that grades submissions, on the same Render instance, and reads the same course
packages.

```
 Student's assistant (claude.ai, VS Code, Claude Code, ...)
        │  HTTPS POST /mcp   one JSON-RPC message: "call get_rubric(...)"
        ▼
 Render ──► gunicorn (one sync worker) ──► run:app  (the Flask WSGI app)
                                              │
                         werkzeug DispatcherMiddleware
                     /mcp ─────────────┴──────────── everything else
                       │                              │
                       ▼                              ▼
             CourseMCPRunner (mount.py)         Flask portal routes
             · non-POST → 405 "it is running"    (grading, admin, ...)
             · optional token check
             · mint Mcp-Session-Id on initialize
             · record the call (usage.py)
                       │
                 a2wsgi ASGIMiddleware  (WSGI → ASGI, on a private event loop)
                       │
                 MCPServer (mcp 2, stateless, JSON responses)
                       │  the tools in coursemcp/server.py
                       ▼
     ┌─────────────────┴─────────────────────────────┐
     │                                               │
 CourseRegistry ─► Grader.units                 load_materials(soln_pkg)
 (the parsed unit XML the portal               (mcp_materials/: per-slide JSON,
  already grades against)                        JPEG images, BM25 index in memory)
```

**Why it looks like this:**

- **Mounted in the portal, not a second service.** The tools read the course
  exactly as the portal has it: `CourseRegistry.grader_for(course_id).units`,
  the same parsed unit XML the grader uses. An upload updates both at once, and
  a deployment is still "fork llmgrader, point Render at it".
- **WSGI to ASGI with `a2wsgi`.** The portal is a WSGI app run by `gunicorn
  run:app`; the MCP library is ASGI. Rather than move the portal to an ASGI
  server, the MCP app is wrapped as WSGI and dispatched by path, so Flask and the
  start command are unchanged.
- **Started lazily, per process.** The MCP's event loop runs in a daemon thread.
  It is started on the first `/mcp` request inside the process serving it, never
  at app creation: gunicorn may load the app before forking its worker, and a
  thread does not survive the fork. That bug froze the live portal once.
- **Nothing but POST reaches the MCP.** Render runs one *sync* gunicorn worker,
  so any request that stays open holds the whole portal. mcp 2 opens a
  never-closing event stream for a GET that accepts `*/*` -- every browser -- so
  `CourseMCPRunner` answers non-POST requests itself with a 405 page. For the
  same reason the server is stateless with JSON responses, and
  `subscriptions/listen` is off.
- **Stateless.** Each request is answered on its own, so any worker can take
  any request. The MCP's 2026-07-28 protocol revision makes every request
  self-contained anyway; for 2025-protocol clients, `CourseMCPRunner` mints an
  `Mcp-Session-Id` on `initialize` so usage can be grouped into sessions without
  the server keeping any state.

## The tools

| Tool | Reads | Returns |
| --- | --- | --- |
| `list_courses`, `list_units` | `CourseRegistry`, `content.course_units` | titles, question counts, `unit_type` and `semester`, package version |
| `list_unit_types` | `course_units`, the manifest's `unit_types` | each type used or described: title, description, its units |
| `list_questions` | `content.course_units` | per question: unit, qtag, a 100-character label, parts, points; filter by `unit` or `unit_type` |
| `get_question` | one question dict | its HTML text with `[Figure n]` placeholders, the figures as image blocks, `variation_guidance` |
| `get_rubric` | one question dict | rubric items, grading notes |
| `get_solution` | one question dict | the worked solution and its figures |
| `list_materials`, `get_outline` | `mcp_materials/` | slide decks; a deck's slide titles |
| `search_slides` | the in-memory BM25 index | ranked slides with snippets and a link |
| `get_slide` | `mcp_materials/slides/<deck>/` | one slide's image, text, notes, figure description, link |

The code: tools in `coursemcp/server.py`; question lookups and figure
resolution in `coursemcp/content.py`; slides in `coursemcp/materials.py`;
the mount, access, sessions and usage hook in `coursemcp/mount.py`; usage rows
in `coursemcp/usage.py`.

**Every unit lookup goes through `content.course_units(grader)`**: the
portal's units (`Grader.units`, `units_order`, `unit_metadata`) followed by the
package's MCP-only units -- past exams listed in `llmgrader_mcp_config.xml`
and never in `llmgrader_config.xml`. Those are parsed by the same
`UnitParser._parse_unit_file` the portal uses, through `parse_unit_files`,
once per package: the result is cached on the `Materials` object, which is
itself replaced when an upload changes the manifest. The type is reported as
`unit_type`, not `type`, because `list_units` already uses `type` to tell a
section heading from a unit. See `plans/exam_units.md`.

**Results are bounded by construction.** A list returns labels, never full
text; figures travel only with a single question or slide. A whole course's
question index is a few thousand tokens.

## Where the material comes from

Everything the MCP serves is built ahead of time, on the instructor's machine,
into the course package that the portal already receives:

```
 hwdesign-soln/               hwdesign/ (slides repo)
   llmgrader_config.xml          units/*/deck.pptx
   llmgrader_mcp_config.xml      units/*/deck.pdf
   units/*/prob/*.xml
   llmgrader_mcp_descriptions/   ◄── llmgrader_mcp_build --describe
        │                              (vision model, once per slide image;
        │                               the only step that calls an AI)
        ▼
 create_soln_pkg ──► soln_package.zip
                       ├── llmgrader_config.xml, unit XML     ◄── served by the grader and the MCP
                       ├── mcp_materials/                     ◄── served by the MCP only
                       │     manifest.json
                       │     slides/<deck>/deck.json   (title, text, notes, description per slide)
                       │     slides/<deck>/slide-NNN.jpg
                       │     units/<stem>.xml, units/<stem>_images/   (MCP-only units)
                       └── package_info.json  (version: date + content hash; source commits)
        │
        ▼  Admin ▸ Load Course Package
 Render disk: <storage>/courses/<id>/soln_pkg/
```

Slide text and speaker notes come from the `.pptx`, and each slide's image from
the deck's PDF export. The vision-model descriptions of each slide's figures are
the one AI step, run once by the instructor and cached by image hash, so the
server never calls a model.

## Why not RAG

Retrieval-augmented generation chunks the material, embeds the chunks and
searches them by similarity, because the material is too large to hand an AI
whole. A course's problem set is not. So instead:

- **The structure is the index.** `list_questions` returns the whole course's
  question index in one call, a few thousand tokens. The assistant matches "the
  problem on the bouncing ball" against the labels itself, handling synonyms
  and paraphrase far better than a similarity search would, and it can notice
  when two problems look relevant and ask which one the student means.
- **Lookups are exact.** Rubrics and solutions are returned whole, as the
  instructor wrote them. Chunking a rubric would break exactly the items the
  grader scores separately, and break derivations mid-way.
- **The assistant is the retrieval loop.** One-shot RAG has a single chance to
  fetch the right chunks. An assistant with a search tool rephrases and searches
  again -- "FSM", then "state machine", then "next-state logic" -- so the search
  itself can be simple.
- **Slide search is keyword search.** `search_slides` is BM25 over slide titles,
  text, speaker notes and the figure descriptions, held in memory. It has no
  dependencies and needs no index rebuild beyond loading the package. Most of a
  slide's content is its figure, which is why the descriptions exist: they put a
  diagram's content into words keyword search can match.
- **No cost, no keys, no drift.** No embedding model to pay for or keep in step,
  no vector store to host, nothing to re-index when a package is uploaded.

**When retrieval would earn its place:** if a course's material grew to many
thousands of pages, or included unstructured or scanned documents with no
outline to navigate. The path then is to add embeddings as a second ranking
inside `search_slides` (or a document search), not to change the tools: the
assistant never sees which method answered.

## Usage recording

Each MCP request writes one row to its own SQLite file, `<storage>/db/mcp_usage.db`,
kept apart from the grading database so usage writes never contend with
grading for SQLite's lock. The row holds the tool, the resolved unit, question,
deck or slide, status, sizes, timing, a coarse client name, the protocol
version and the package version -- never the student's words (search queries
and any argument not listed as an identifier are redacted) and no identity. It
is written after the response is sent, and a failed write never fails the call.
See [what is recorded](../admin/mcp/deploy.md#what-is-recorded) and the
[MCP usage analytics](../analytics/mcp_usage.md).

## Testing

`tests/coursemcp/` covers the mount (including the fork and GET hazards, under
time limits so a regression fails rather than hangs), access, every tool against
small fixture courses, slide building and search, and usage recording. Most
tests drive the portal's own WSGI stack with Flask's test client, as gunicorn
would; slide-building tests need the `mcp-build` extra and are skipped without
it.
