---
title: Past Exams and Unit Types
parent: Course MCP
nav_order: 2.5
has_children: false
---

# Publishing Past Exams and Describing Unit Types

A past exam is useful to a student's assistant: asked for "a midterm-style
problem on FSMs", it can model one on a real midterm problem, with its rubric,
instead of on homework. But it does not belong on the portal, where every unit
in `llmgrader_config.xml` appears in the unit menu beside the homework.

So a unit can be published **to the MCP only**, and every unit can say **what
kind of unit it is**. Both are optional; a course that uses neither is served
exactly as before.

---

## Step 1: Give the unit a type

Two optional attributes on the unit's `<unit>` element:

```xml
<unit id="midterm_s2026" title="Midterm, Spring 2026" version="1.0"
      unit_type="midterm" semester="Spring 2026">
```

| Attribute | Meaning |
| --- | --- |
| `unit_type` | What kind of unit this is. Default `problem_set`. Any short key you choose -- `midterm`, `final`, `quiz` -- in lowercase letters, digits, `-` and `_`. |
| `semester` | When the material was given, as free text. For past material; optional. |

The grader ignores both. The MCP reports them in `list_units`, and the
assistant can list every question of one type: "all past midterm problems" is
one call.

---

## Step 2: List the unit in `llmgrader_mcp_config.xml`, not `llmgrader_config.xml`

A unit listed in [`llmgrader_mcp_config.xml`](./package.md#step-3-write-llmgrader_mcp_configxml)
is built into the package and served by the MCP, and the portal never sees
it:

```xml
<llmgrader_mcp>
  <slides>
    ...
  </slides>

  <units>
    <unit section="Past exams">exams/MidtermS2026/midterm_s2026.xml</unit>
  </units>
</llmgrader_mcp>
```

| Part | Meaning |
| --- | --- |
| `<unit>` text | The unit XML file, relative to this config file (or to `root`). |
| `section` | Optional. A heading the unit is listed under in `list_units`, after the portal's units. Consecutive units with the same section share one heading. |
| `name` | Optional. What the assistant calls the unit. Default: the unit's `title` attribute. |
| `root` | Optional. A `<root>` the path is relative to, as for slide decks. |

The `<units>` element goes after `<slides>` (and `<slides>` may be left out).

**A unit listed in both configs is an error**, and so is a `name` the portal
already uses: the second list is for units the portal does not have.

**Figures** follow the portal's convention: put them in an `images/` folder
beside the unit file and reference them as
`/pkg_assets/<file stem>_images/<file>` -- for `midterm_s2026.xml`,
`/pkg_assets/midterm_s2026_images/fsm.png`.

**Nobody grades an MCP-only unit.** The portal does not have it. A student can
still practise it through their assistant, which reads its rubric.

---

## Step 3: Describe each unit type

Tell students' assistants what each kind of unit is like, in the same file:

```xml
  <unit_types>
    <unit_type id="midterm" title="Midterm exam">
      Pen and paper, closed book, 75 minutes. Each problem takes about five
      minutes, and any syntax a problem needs is given in it. Covers units 0
      to 5.
    </unit_type>
  </unit_types>
```

`<unit_types>` goes after `<units>`. The `id` is a `unit_type` value; the text
is the description. `problem_set` needs no entry.

The new tool `list_unit_types` returns each type with its title, its
description and the units of that type, and the server tells assistants to
read a type's description before writing a practice problem "like the
midterm". A type you describe is listed even before any unit has it -- a
description of `final` says what this term's final will be like.

This is where your exam notes live. The description of `midterm` *is* "what
this term's midterm is like": update it each term, and leave the past exams
themselves untouched.

---

## Step 4: Check, build and upload

```bash
llmgrader_mcp_build --dry-run
```

now lists the MCP-only units after the slide decks, with their files. Then
build and upload as usual (`create_soln_pkg`, then **Load Course Package**).
The build prints one line per unit:

```text
Building course MCP material from llmgrader_mcp_config.xml:
  [fsm] 41 slides, with images, 41 described
  [unit] Midterm, Spring 2026 (Past exams)
```

An MCP-only unit is checked against the unit schema when the package is
built, so a broken one stops the build rather than disappearing on the
server.
