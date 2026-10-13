# Plan: one materials model for the course MCP

**Status: built (2026-10-12), phases 1 to 4, on branch
`feature/unified-materials`; not yet deployed.**  hwdesign is migrated on
`mcp/unified-materials` in hwdesign-soln and hwdesign.  Departures from the
text below: a pattern name another item already has gets `-<kind>` after it
(`fsm-demo`, since hwdesign's decks and demos share names); `<items>` matches
a folder by `path` *or* `docs`, so a docs-only demo is still an item; the
repo's corrections file is `materials.xml` at the repo root; usage rows also
get a `kind` column; units in `llmgrader_config.xml` gained no `id`
(decision 1: material units are referenced by id, portal units by name).

**No backward compatibility.**  One course (hwdesign) uses the portal, and it
is migrated in the same change.  The old config elements (`<slides>`,
`<code>`, `demos/demos.xml`), the eight old tools and their analytics presets
are replaced, not kept alongside: no fallback for an unmigrated course, no
aliases, no dual-name queries.

Today the course MCP has two separate machines for course material: one for
lecture slide decks (`list_materials`, `get_outline`, `get_slide`,
`search_slides`) and one for demo code and its docs walkthroughs
(`list_demos`, `list_demo_files`, `get_demo_file`, `search_demos`).  Each
grew around one course's layout.  Labs fit neither: the take-home prompt
template in `hwdesign/labs/cmdresp/partial/prompt.md` was unreachable until a
config change made each lab pose as a demo.  A PDF handout or a LaTeX problem
sheet has nowhere to go at all.

This plan replaces both with **one model**: a course declares its own kinds
of material (slides, demo, lab, handout, ...), its units, and its items, and
four tools list, open, read and search all of them.

```
"Where do I start the take-home prompt?"
  list_materials(course_id, unit="Command-Response Mini-Project")
    -> kinds: lab "Lab instructions and starting files", slides, demo, ...
       items: cmdresp  lab   "Command-Response Mini-Project"
              fifo     slides "FIFOs and Streaming Interfaces"  (also Unit 5)
  get_material(course_id, "cmdresp")
    -> docs/labs/cmdresp/takehome.md  "Take-home: parts 3 and 4"  (page)
       labs/cmdresp/partial/prompt.md                            (text, 69 lines)
  read_material(course_id, "cmdresp", path="labs/cmdresp/partial/prompt.md")
    -> the template, with source_url
```

## Motivation

- **Professors' material is not shaped like this course's.**  One course has
  slides and Jupyter notebooks, another LaTeX handouts and MATLAB scripts,
  another a lab manual in PDF.  The tools should not have to change for each.
- **The assistant needs one map.**  A student asks "where is X?"; the answer
  may be a slide, a demo, a lab page or a handout.  Today that takes two
  searches with different tools, and an assistant that knows only one of them
  misses the other.
- **Solutions need a rule, not a convention.**  "lab-solution" is a natural
  kind for a professor to list, and it must not be served the way a lab is.

## What exists, and what stays

| Today | Fate |
|---|---|
| `<slides><deck>` in `llmgrader_mcp_config.xml`; `llmgrader_mcp_build` renders each deck's PDF pages and writes text, notes and model-written descriptions into `mcp_materials/` | Kept as the **slides format**.  A deck becomes an item of a slides kind. |
| `<code repo=... ><include path kind="code\|doc"/>`: a sparse, synced mirror of a public GitHub repo (`coursemcp/code.py`) | Kept as the **mirror source**.  Patterns stay allowed here, and only here (see Sources). |
| Demos derived from links between slides, docs and code (`demo_links.py`), corrected by `demos/demos.xml` in the repo | Kept as a **helper**: a report suggesting units and related slides for items (`--links`), and the pattern rule that pairs `docs/<x>/<name>` with `<x>/<name>`.  No longer the only way an item exists. |
| `<units><unit section=...>` (MCP-only unit XML, e.g. past exams) and `<unit_types>` | Unchanged.  They are graded-question content, served by the question tools. |
| Question tools: `list_units`, `list_unit_types`, `list_questions`, `get_question`, `get_rubric`, `get_solution` | Unchanged, except `list_units` also returns the material-only units below. |
| Usage log (`mcp_usage`): `deck`, `slide`, `demo`, `path` columns | Kept; new calls fill `material` and `path` (see Analytics). |

## The model

**Kind.**  A label the professor chooses, with a sentence the assistant
reads, and a policy.  For hwdesign: `slides`, `demo`, `lab`, `lab-solution`.

**Format.**  How a file is read.  It follows from the file, never from the
kind, so a professor never has to explain how to read their own kinds:

| Format | Files | Read as |
|---|---|---|
| `slides` | a `.pptx` with its PDF export | per slide: rendered image, title, text, speaker notes, description |
| `pdf` | a `.pdf` (handout, problem sheet, paper) | per page: extracted text, rendered image, description |
| `page` | Markdown in a docs tree that is published as a site | text, with `view_url` |
| `text` | code, LaTeX, plain Markdown, notebooks, anything else that is text | numbered lines, with `source_url` |

LaTeX is read as text.  If the compiled PDF is listed beside it, both are
parts of the same item, and the assistant picks.

**Unit.**  Either a unit `<name>` from `llmgrader_config.xml`, or a
material-only unit declared in the MCP config (`setup`, `project`).
Material-only units carry no questions.  They appear in `list_units` with
`questions: 0` and in `list_materials`.

**Item.**  The thing a student is pointed to: an id, a title, a one-line
description, a kind, **one or more units**, and its **parts** (files or
folders, each with its format).  A demo used in Units 4 and 5 is one item
with two units, not two items.

**Policy** (per kind):

| Policy | Served | For |
|---|---|---|
| `open` (default) | as is | slides, demos, labs, handouts |
| `tutor` | with the instruction `get_solution` already carries: help the student reason toward the answer, and reproduce it only if asked | worked solutions a professor wants available as a tutor |
| `private` | listed (title and kind only, so the assistant can say it exists), never read or searched | answer keys, material under embargo |

The grader's own `get_solution` is the `tutor` policy applied to question
solutions.  The two should share one implementation of the instruction text.

## Configuration

A new `<materials>` element in `llmgrader_mcp_config.xml` replaces `<slides>`
and `<code>`'s `<include>` list; `<code>` keeps only the mirror's repo and
branch.  hwdesign's, in full:

```xml
<materials>
  <kind id="slides" description="Lecture slides, one or two decks per unit"/>
  <kind id="demo" description="In-class demos: code with a docs walkthrough"/>
  <kind id="lab" description="Lab instructions and the files students start from, such as a prompt template"/>
  <kind id="lab-solution" policy="tutor" description="Worked solutions to the labs"/>

  <unit id="setup" name="Course setup" description="Installing Vitis, the Python environment and the agent"/>
  <unit id="project" name="Final project"/>

  <!-- Slides: today's <deck> entries, with kind and units. -->
  <item id="fifo" kind="slides" unit="Unit 5:  FIFOs and Streaming Interfaces"
        root="pub" path="units/unit05_fifo/fifo.pptx" pdf="units/unit05_fifo/fifo.pdf"/>
  ...

  <!-- One item per folder: labs/<name> with docs/labs/<name>, from the mirror. -->
  <items kind="lab" source="mirror" path="labs/*" docs="docs/labs/*"/>
  <items kind="demo" source="mirror" path="demos/*" docs="docs/demos/*"/>

  <!-- Units and corrections for pattern-made items. -->
  <item id="cmdresp" unit="Command-Response Mini-Project" also="Unit 5:  FIFOs and Streaming Interfaces"/>
  <item id="cubic" unit="Unit 3:  Floating and Fixed-Point"/>
  <item id="setup" kind="lab" unit="setup"/>
</materials>
```

Rules:

- **`<item>` with a path makes an item.**  `<item>` with only an id refines an
  item a pattern made (units, title, description, kind), the role
  `demos/demos.xml` plays today.  An id that matches nothing is an error at
  build time, not a silent no-op.
- **`<items>` makes one item per match.**  The id is the matched folder name;
  the title and description come from the docs folder's `index.md` (front
  matter `title`, first paragraph), as for documented demos today.  A match
  with no docs folder is still an item, titled by its folder name.
- **Units are required.**  An item with no unit after refinement fails the
  build, with the list of such items, as `--links` reports "NO UNIT" today.
  Derived links (a slide that cites a demo's code) may supply a unit; the
  build prints where each unit came from.
- **Repo-side corrections stay possible.**  The mirror may carry a
  `materials.xml` (replacing `demos/demos.xml`, same schema as the
  `<item id>` refinements) read on every sync, so retitling or re-unit-ing a
  mirrored item needs no package rebuild.  Its refinements apply after the
  config's.

## Sources

Two sources, kept apart on purpose:

- **Package** (`root=...`, explicit paths only): files from any repo,
  including the private solution repo, built into `mcp_materials/` by
  `llmgrader_mcp_build`.  **No patterns.**  The config schema's existing rule
  stands: a course repository also holds exams, autograder keys and
  solutions, and a new one must not be published because nobody remembered
  to exclude it.
- **Mirror** (`source="mirror"`): the public repo `<code>` already syncs.
  Patterns are allowed, because everything there is public already.

A `pdf`-format part may come from either.  A mirrored PDF is rendered on
sync, like the code snapshot is built today, and cached by content hash so a
sync that did not change it does no work.

## Tools

Four material tools replace eight.  All take `course_id`.

| Tool | Returns | Replaces |
|---|---|---|
| `list_materials(unit?, kind?)` | the kinds (id, description, policy), the units (graded and material-only), and the items (id, title, description, kind, units, part count) | `list_materials` (decks), `list_demos` |
| `get_material(id)` | the item and its parts: for slides, the outline (slide number and title); for a folder, its files with format, title or line count; related slides from the link report | `get_outline`, `list_demo_files` |
| `read_material(id, path?, page?, start_line?, end_line?)` | one slide or page (image + text + description), or one file's lines, with `view_url` / `source_url` | `get_slide`, `get_demo_file` |
| `search_materials(query, unit?, kind?, format?)` | hits across every item: id, kind, part, slide or page or line, snippet, url | `search_slides`, `search_demos` |

- **Search keeps today's two rankings**, applied by format: identifier-aware
  whole-word matching with weak-hit cutting (`search_slides`, PR #36) for
  slides and pages; line search for text.  One call returns both, merged by
  score, each hit labelled with its kind.
- **`format` replaces `search_demos`'s `kind="code|doc"` filter**, since
  `kind` now means the professor's kind.
- **`private` items** appear in `list_materials` with `readable: false`, and
  are absent from `get_material`, `read_material` and `search_materials`.
- **`tutor` items** carry the tutoring instruction in every response that
  returns their content, as `get_solution` does.

**Names.**  Old tool names are removed, not aliased.  The usage log for
2026-10-07 to 10-12 shows no student sessions: the traffic is the
instructor's own sessions and a scripted sweep (46 matched
question/rubric/solution calls on each of two days, no client).  The cost is
that a claude.ai connection caches tool lists, so the instructor reconnects
once after the deploy.

## Analytics

- New columns: `material` (the item id) and `format`.  `path` and `slide`
  (now also a PDF page) stay.  `deck` and `demo` are no longer written; old
  rows keep them as history, and nothing queries them.
- `IDENTIFIER_ARGUMENTS` gains `id`, `page`, `format` and loses `deck` and
  `demo`; `query` stays redacted.
- The MCP presets in `static/js/analytics.js` are rewritten for the new tool
  names only.  New preset: "Calls per material and kind".

## Migration of hwdesign

1. The twelve `<deck>` entries become `<item kind="slides">`.
2. `<items>` patterns for `demos/*` and `labs/*`.
3. `demos/demos.xml` becomes `materials.xml` in the hwdesign repo, with the
   lab unit entries now on branch `mcp/lab-units`.
4. `lab-solution` items from `hwdesign-soln/labs/<lab>/` (package source,
   explicit paths, `tutor` policy), one per lab, if the instructor wants
   solutions available to tutor with.  Off by default: listing the kind
   alone publishes nothing.

The interim config on branches `hwdesign-soln:mcp/serve-labs` and
`hwdesign:mcp/lab-units` (labs as demos) is a subset of step 2 and needs no
work to carry over.

## Phases

**1. Model and config, no tool changes.**  `materials.py`: the `Material`,
`Part`, `Kind` and `Unit` types; the schema, with `<slides>` and
`<code><include>` removed; building the index from `<materials>`; and
hwdesign's config migrated (steps 1 to 3 below) in the same change.
`llmgrader_mcp_build --materials` prints the index: every item, its units and
where each came from, its parts and formats.  Until phase 2, the old tools
read the new index.

*Tests:* the hwdesign config builds the same items as today's decks plus
demos plus labs; an `<item id>` refinement with no match fails; an item with
no unit fails; `<items>` with `source="package"` is a schema error;
`private` and `tutor` round-trip.

**2. The four tools.**  Implement against the index; delete the eight old
tools; tool descriptions and the server's instructions rewritten around
"materials" with the kinds listed.

*Tests:* the scenarios that pass today, re-expressed (the `s_axilite` search
from `demo_code_mcp.md` finds the same code and doc; `get_slide` content
equals `read_material` of the deck); `list_materials(unit="Command-Response
Mini-Project")` returns `cmdresp`; `read_material` of
`labs/cmdresp/partial/prompt.md` returns its 69 lines with a `source_url`; a
`private` item is listed and unreadable; a `tutor` item's content carries the
instruction; path traversal is refused; the admin endpoints still never wait
on git (the one-second test).

**3. The pdf format.**  Rendering and text extraction (PyMuPDF), page
descriptions through the existing describe step, caching by content hash.

*Tests:* a two-page fixture PDF reads page by page; a changed PDF re-renders,
an unchanged one does not.

**4. Analytics, docs, rollout.**  The usage columns and presets;
`docs/admin/mcp/` rewritten around materials (overview, package, code
becomes "sources"); hwdesign migrated; package rebuilt and uploaded.

## Decisions to make

1. **Units by name or by id.**  Units are referenced by their `<name>` today
   ("Unit 5:  FIFOs and Streaming Interfaces", double space included).  An
   optional `id` on `<unit>` in `llmgrader_config.xml` would make references
   shorter and survive a retitle.  Proposed: accept either, prefer id.
2. **Where pattern-item units live.**  In the config (needs a package
   rebuild to change) or in the repo's `materials.xml` (read every sync).
   Proposed: both, repo last, as above.
3. **Notebooks.**  `.ipynb` read as `text` is noisy JSON.  A `notebook`
   format reading cells as Markdown and code is a small addition; proposed
   for phase 3 if a course needs it.
4. **Whether `lab-solution` ships for hwdesign at all.**  The model allows
   it; whether students' assistants should see lab solutions, even as a
   tutor, is the instructor's call, per kind.
