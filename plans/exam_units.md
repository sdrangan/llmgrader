# Plan: exam units -- typed units, MCP-only units, and printed exams

Let a course publish past exams to the course MCP without putting them on the
portal, tell the student's assistant what kind of unit each one is, and print a
unit as a paper exam with a title page and room to write.

The first user is the Spring 2026 midterm, already converted to
`hwdesign-soln/exams/MidtermS2026/midterm_s2026.xml`: five problems, corrected
solutions, rubrics with skill tags, variation guidance.

## Motivation

- **Past exams belong in the MCP.** A student who asks for "a midterm-style
  problem on unit 2" gets homework-style problems today, because nothing tells
  the assistant what a midterm looks like. A real past exam, with rubrics, and a
  description of this term's exam format, fix that.
- **But not on the portal.** Every unit in `llmgrader_config.xml` appears in the
  portal's unit menu, and an old exam there next to the homework is confusing.
- **And an exam has to be printed.** The paper exam needs a title page and blank
  pages to write on; `create_qfile` already renders a unit to PDF with MathJax,
  and a mock-up with exam styling looked close to the LaTeX exams.

## What already exists

| Need | Already in the tree |
| --- | --- |
| Unit XML with questions, parts, rubrics, solutions | `schemas/unit.xsd`, `UnitParser` |
| MCP-only material in its own config, built into the package | `llmgrader_mcp_config.xml`, `coursemcp/materials.py` (`read_config`, `build_materials`), `create_soln_pkg` |
| Loading built material per package, reloaded on upload | `materials.load_materials` (cached on manifest mtime) |
| The unit tools | `coursemcp/server.py`: `list_units`, and `list_questions`, `get_question`, `get_rubric`, `get_solution` via `coursemcp/content.py` (`resolve_unit`, `unit_names`) |
| Unit XML to HTML to PDF, with or without solutions | `scripts/create_qfile.py` (`parse_xml_file`, `generate_html`, `generate_pdf_from_html`) |

## Design decisions

### 1. A unit has a type, and optionally a semester

Two optional attributes on `<unit>` in `unit.xsd`:

```xml
<unit id="midterm_s2026" title="Midterm, Spring 2026" version="1.0"
      unit_type="midterm" semester="Spring 2026">
```

- **`unit_type`** defaults to `problem_set`. Any short tag is allowed --
  `midterm`, `final`, `quiz` -- pattern-constrained (`[a-z][a-z0-9_-]*`) since it
  is a key. Not an enumeration: courses name their own assessments.
- **`semester`** is free text, for past material. Optional.

Both are attributes, not elements, because they describe the unit rather than
contain it, and because existing units stay valid untouched. `UnitParser`
records them per unit; the grader ignores them.

The MCP reports the type as **`unit_type`**, not `type`: `list_units` already
uses `type` to tell a section heading from a unit.

### 2. MCP-only units are listed in `llmgrader_mcp_config.xml`

```xml
<units>
  <unit section="Past exams">exams/MidtermS2026/midterm_s2026.xml</unit>
</units>
```

- **The build** (`build_materials`, so `create_soln_pkg` too) copies each listed
  file into `mcp_materials/units/`, with its adjacent `images/` directory under
  the same `<dest_stem>_images` convention `create_soln_pkg` uses for portal
  units, so a figure's `/pkg_assets/...` path resolves the same way. The
  manifest records each unit's file and section.
- **Only what is listed is published**, as for slides.
- **A unit listed in both configs is an error** at build time: the point of the
  second list is units the portal does not have, and one unit in both places
  would be served twice.
- **The portal never reads `mcp_materials/units/`.** It is not in
  `llmgrader_config.xml`, so `UnitParser` never parses it for grading.

### 3. The MCP serves both kinds of unit through the same tools

A small loader, beside `load_materials` and cached the same way, parses the
package's MCP-only units with `UnitParser` and exposes them with their sections.
The content tools look units up through one function that sees the portal's
units followed by the MCP-only ones, in configured order:

- `list_units` lists both, each with `unit_type` and `semester`, and the
  MCP-only ones under their sections.
- `list_questions`, `get_question`, `get_rubric` and `get_solution` work on
  either kind unchanged; `resolve_unit` searches both.
- `list_questions` gains an optional `unit_type` filter, so "all past midterm
  problems" is one call.

No new tools for the units themselves: an exam is, to the assistant, a unit
with a type.

### 4. Unit types are described once, in the MCP config

```xml
<unit_types>
  <unit_type id="midterm" title="Midterm exam">
    Pen and paper, closed book. Each problem takes about five minutes, and any
    syntax a problem needs is given in it. Covers units 0 to 5.
  </unit_type>
</unit_types>
```

- **A new tool, `list_unit_types`**, returns each type used by the course with
  its title and description. `problem_set` needs no entry; an undescribed type
  is listed with its id alone.
- **The server instructions** tell the assistant to read a type's description
  before writing practice problems "like the midterm".
- The descriptions are not repeated in `list_units`, which would carry them on
  every call that lists units.

This is where an instructor's exam notes live: the description of `midterm`
*is* "what this term's midterm is like", and it changes each term without
touching the past exam itself.

### 5. Print layout lives at the end of the unit, in its own block

A unit can say how it prints, in one or more optional `<print>` blocks **after
all its questions**. One file holds the content and how to print it, and
keeping the blocks at the end, rather than between questions, keeps the
questions contiguous for everything that reads them. The grader and the MCP
ignore `<print>` entirely: `UnitParser` skips it, and it never reaches a
question dict or a tool result.

It is for any printout, not only exams: a problem-set handout is a short block,
an exam a longer one.

```xml
<unit id="midterm_f2026" title="Midterm, Fall 2026" unit_type="midterm" semester="Fall 2026">
  <question qtag="Signed logic types"> ... </question>
  <question qtag="Simple division counter"> ... </question>
  ...

  <print id="exam">
    <title_page>
      <title>Midterm, Fall 2026</title>
      <course>ECE-GY 6463: Advanced Hardware Design</course>
      <instructors>Profs. Sundeep Rangan, Siddharth Garg</instructors>
      <date>October 28, 2026</date>
      <duration>75 minutes</duration>
      <fields>
        <field>Name</field>
        <field>NetID</field>
        <field>Signature</field>
      </fields>
      <instructions>
        <item>Closed book; no calculators or electronic aids.</item>
        <item>Write your answers in the space provided.</item>
      </instructions>
    </title_page>
    <question qtag="Signed logic types" answer_pages="1"/>
    <question qtag="Simple division counter" answer_pages="2"/>
  </print>

  <print id="makeup">
    ... a different title page, a subset of the questions ...
  </print>
</unit>
```

A problem-set handout needs much less:

```xml
  <print id="handout" answer_pages="0" page_per_question="false"/>
```

- **Everything in `<print>` is optional.** No `<title_page>` prints the unit's
  title as a heading. No `<question>` list prints every question in document
  order. Block-level `answer_pages` (default 1 for a block with a title page, 0
  otherwise) and `page_per_question` (default true with a title page) set the
  defaults; a `<question>` entry overrides `answer_pages` for that question.
- **The `<question>` list is the printed order**, and may be a subset, so one
  unit prints a makeup or a shortened version without its questions being
  edited. A listed qtag that is not in the unit is a validation error.
- **Answer pages are headed automatically** *"Use this page for Problem n"*:
  generated, never authored, so the header cannot go stale when questions move.
- **Points** come from the unit's parts, shown with each question and totalled
  on the title page.
- **A unit with no `<print>` block** prints as `create_qfile` prints it today.

`create_qfile --print <id>` renders the named block (the only block if there is
one) with the print styling from the mock-up: Computer Modern for text and
math, a page footer "Page n of N", one question per page when
`page_per_question` is on. `--soln` adds the solutions from the same file, for
the key.

**The block is not published**: the MCP strips nothing because it never reads
it, and the portal ignores it. It does travel inside the package, which is
harmless -- a title page and page counts.

### 6. Practice grading is not on the portal, for now

MCP-only units are graded by nobody: the portal does not have them. A student
can still practise a past exam through their assistant, which reads the rubric.
Portal grading of exam units -- unlisted, reachable by link -- is a later
decision.

## Status

Phases 1 to 3 are built (branch `feature/exam-units`), with their part of
phase 6: `docs/admin/mcp/units.md`, the `<unit>` table in
`docs/admin/buildcourse/unitxml.md`, and the tool tables in the MCP overview,
developer and student pages. Choices the plan left open:

- An MCP-only unit's name is `name=` on its `<unit>` entry, else the unit's
  `title`. A name the portal already uses is a build error, like a file in
  both configs.
- Its figures are rewritten at build time from `/pkg_assets/<stem>_images/`
  to `/pkg_assets/mcp_materials/units/<stem>_images/`, where the build puts
  them, so the author writes the portal convention and nothing downstream
  needs to know.
- `list_unit_types` also lists a type that is described but has no unit yet
  (a `final` description before any past final exists).
- `list_units` gives `semester` only when it is set.

## Phases

1. **Unit attributes.** `unit_type` and `semester` in `unit.xsd`, parsed by
   `UnitParser`, reported by `list_units`.
2. **MCP-only units.** `<units>` in `llmgrader_mcp_config.xsd`, the build step,
   the loader, the unified lookup, `list_questions`'s `unit_type` filter.
3. **Unit types.** `<unit_types>`, `list_unit_types`, the server instructions.
4. **Printing.** The `<print>` block in `unit.xsd`, skipped by `UnitParser`,
   and `create_qfile --print`.
5. **hwdesign-soln.** `unit_type="midterm"` and `semester` on the midterm;
   the midterm entry and a draft `midterm` description in its
   `llmgrader_mcp_config.xml`, for the instructor to edit; rebuild and upload.
6. **Docs.** Written with the code, so they describe what was built:
   - `docs/admin/buildcourse/`: a page on every new field -- `unit_type` and
     `semester` on `<unit>`, and the `<print>` block with each of its elements
     and defaults -- with a complete exam example and a one-line handout, and
     how to run `create_qfile --print`.
   - `docs/admin/mcp/`: publishing a unit that is not a problem set -- listing
     it in `llmgrader_mcp_config.xml` so it reaches the MCP and not the portal,
     and describing its `unit_type` for students' assistants.
   - The student page and `docs/developer/mcp.md`: the new `unit_type` field and
     `list_unit_types`.

   Already written, ahead of this plan, since they describe what is live:
   `docs/overview/mcp.md` (why the course MCP is published to students' own
   assistants rather than built in), the MCP section of `docs/index.md`, and
   `docs/developer/mcp.md` (how it works, and why it is not RAG).

Phases 1 to 3 land together; 4 is independent of them.  Phase 4 changes
`unit.xsd`, so it is checked against every existing unit, none of which
has a `<print>` block.

## Tests

- A unit without the attributes parses as `problem_set` with no semester; the
  parser snapshot is updated for the two new keys.
- A unit listed only in the MCP config is served by every unit tool and appears
  in `list_units` under its section, and is absent from the portal's `/units`.
- A unit listed in both configs fails the build.
- An MCP-only unit's figure resolves through `/pkg_assets` like a portal unit's.
- `list_questions(unit_type="midterm")` returns only exam questions.
- `list_unit_types` returns described types with their descriptions, and an
  undescribed type by id alone.
- `<print>` is invisible to the grader and the MCP: a unit with and without it
  parses to the same question dicts and the same tool results.
- `create_qfile --print`: the title page, points and total; answer pages after
  each question with the right problem number; a subset and reordering; a
  minimal handout block; a block naming an unknown qtag fails validation;
  `--soln` adds the solutions.

## Open questions

- **Exam guidance per unit as well as per type?** A specific past exam might
  deserve its own note ("this was a 140-minute exam with two cheat sheets"). The
  unit's `semester` and the type description may be enough; if not, an optional
  per-unit description.
- **Portal practice for exam units** (decision 6).
- **Answer space finer than a page?** `answer_pages` is whole pages; a
  fractional or "lines" option could come later if a quiz needs it.
