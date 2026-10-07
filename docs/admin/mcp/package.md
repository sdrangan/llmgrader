---
title: Packaging the Course Material
parent: Course MCP
nav_order: 2
has_children: false
---

# Packaging the Course Material for the MCP

The course MCP serves two kinds of material:

- **Questions, rubrics and worked solutions.** These come from the course
  package you already build and upload for grading. Nothing extra is needed:
  a course that grades on the portal is served by the MCP.
- **Lecture slides.** These are not part of the grading package, so they are
  listed in a second file, `llmgrader_mcp_config.xml`, and built into the same
  package. You still upload one archive per course.

This page covers the slides. If you only want to publish questions, skip to
[Deploying](./deploy.md).

---

## What students get from the slides

For each slide: its title, its text, your speaker notes, an image of the slide,
and optionally a short description of its figures. Their assistant can list a
unit's decks, read a deck's outline, search all slides for a topic, and open
one slide -- so "where is this described in the class slides?" is answered with
a deck and slide number, and the slide itself.

The image matters: most of a lecture slide's content is its diagram, waveform
or equation, not its text.

---

## Step 1: Install the build tools

Building slides needs two extra Python packages, used only on your machine --
the portal does not need them. In the environment where you run
`create_soln_pkg`:

```bash
pip install -e "path/to/llmgrader[mcp-build]"
```

(or `pip install "llmgrader[mcp-build]"` for an installed copy). This adds
`python-pptx`, which reads the slide text and notes, and `pymupdf`, which
renders each slide's image from the PDF.

---

## Step 2: Export each deck to PDF

The slide images are rendered from a PDF export of each deck, so every deck
you publish needs an up-to-date PDF beside it. In PowerPoint:
**File → Export → Create PDF/XPS**, saved next to the `.pptx` with the same
name.

{: .warning }
**Re-export the PDF whenever you change the deck.** The build compares the
PDF's page count with the deck's slide count. If they differ, the PDF is out of
date -- its pages would be shown beside the wrong slides' text -- so the build
ignores it and publishes that deck **as text only**, with a warning. Matching
counts are the only check, so an edit that changes no slide count still needs a
fresh export to show up in the images.

A deck with no PDF is also published as text only. That works, but students'
assistants cannot see its figures.

---

## Step 3: Write `llmgrader_mcp_config.xml`

Create `llmgrader_mcp_config.xml` **in the same folder as
`llmgrader_config.xml`**. It lists each slide deck to publish:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<llmgrader_mcp>
  <!-- Where the slides live.  Paths are relative to this file. -->
  <roots>
    <root id="pub" path="../hwdesign"/>
  </roots>

  <slides>
    <deck id="fsm" root="pub"
          unit="Unit 2:  Sequential Logic and FSMs"
          pdf="units/unit02_fsm/fsm.pdf">units/unit02_fsm/fsm.pptx</deck>

    <deck id="fixp" root="pub"
          unit="Unit 3:  Floating and Fixed-Point"
          pdf="units/unit03_fixp/fixp.pdf">units/unit03_fixp/fixp.pptx</deck>

    <!-- A deck with no PDF is published as text only. -->
    <deck id="review-numbers" root="pub"
          unit="Unit 1:  Data Types and Combinational Logic"
          title="Review: number representations">units/unit01_basic_logic/review_numbers.pptx</deck>
  </slides>
</llmgrader_mcp>
```

| Part | Meaning |
| --- | --- |
| `<root id path>` | A folder the slides are read from, usually another repository. `path` is relative to this file. Give each a short `id`. |
| `<deck>` text | The `.pptx`, relative to its root. |
| `id` | Short name the assistant uses for the deck: lowercase letters, digits, `-` and `_`. Must be unique. |
| `unit` | The unit the deck belongs to. Copy the unit's `<name>` from `llmgrader_config.xml` **exactly**, including double spaces, so a student asking about "unit 2" gets both its problems and its slides. A deck for something that is not a graded unit can use any text. |
| `pdf` | The PDF export of the same deck, relative to the same root. Optional. |
| `title` | Optional. Without it, the deck is named by its first slide's title. |
| `root` | Which `<root>` the paths are relative to. Without it, they are relative to this file. |

**Only what is listed is published.** There are no wildcards: a course
repository also holds exams, autograder keys and lab solutions, and a new file
must never be published because nobody remembered to exclude it.

---

## Step 4: Check what will be published

From the folder with the two config files:

```bash
llmgrader_mcp_build --dry-run
```

It lists every deck and every file it would read, and builds nothing.
**Read this list before every upload.** If your slides repository is somewhere
other than the `path` in the config, point to it without editing the file:

```bash
llmgrader_mcp_build --dry-run --root pub=C:/path/to/hwdesign
```

---

## Step 5 (optional): Describe the slides' figures

Search works on words, and much of a slide is a picture: a state diagram's
"Moore machine" may appear in no slide's text at all. This optional step asks
an OpenAI vision model to write a few sentences about each slide's figures, so
search can find them, and an assistant knows what a figure shows before it
opens it.

It is the one step that **costs money**, so it is separate and never runs on its
own. It costs very little -- about **$0.27 for 500 slides** with the default
model -- and you pay **once per slide**: results are saved in a
`llmgrader_mcp_descriptions/` folder beside your config, one file per deck, and
reused by every later build.

1. **Make sure the PDFs are up to date** (step 2). Only slides with an image
   can be described; text-only decks are skipped.
2. **Set your OpenAI key** in the shell, the same key the grader tools use:

   ```bash
   # PowerShell
   $env:OPENAI_API_KEY = "sk-..."
   # bash
   export OPENAI_API_KEY=sk-...
   ```

3. **See how many slides need describing, and the estimated cost.** This
   spends nothing:

   ```bash
   llmgrader_mcp_build --describe --dry-run
   ```

4. **Describe them.** It shows the estimate again and asks before spending:

   ```bash
   llmgrader_mcp_build --describe
   ```

   It takes a few minutes, and prints progress every 25 slides. If it is
   interrupted, or some calls fail, run it again: what was already described
   is saved, and only the rest is sent.

5. **Spot-check a few descriptions** against the slides. Each deck has its own
   file -- `llmgrader_mcp_descriptions/fsm.json` and so on -- listing its
   slides in order with their number, title and description. They are written
   by a model; an occasional detail may be wrong.
6. **Commit the `llmgrader_mcp_descriptions/` folder** with your course files,
   so the next build -- on any machine -- reuses it. It is the only copy of
   what you paid for.

**When you change slides:** re-export the PDF and run `--describe` again. Each
description is matched to its slide by the slide's image, so only slides that
actually look different are sent; unchanged slides, even renumbered ones, cost
nothing, and their files are renumbered to match.

**To redo descriptions** -- with a stronger model, or because a deck's came out
poorly -- use `--force`, optionally limited with `--deck`:

```bash
llmgrader_mcp_build --describe --deck fsm --force
```

Deleting a deck's file and running `--describe` does the same for that deck.

The folder's location can be changed in `llmgrader_mcp_config.xml`, as the
first element: `<descriptions path="some/other/folder"/>`, relative to the
config file.

To use a stronger model, pass `--model standard` (about ten times the cost).
`--model` accepts a tier name or a model id from the
[model list](../../developer/models.md); it must accept images.

---

## Step 6: Build and upload the package

Build the course package as usual:

```bash
create_soln_pkg --config llmgrader_config.xml
```

Because `llmgrader_mcp_config.xml` is beside it, `create_soln_pkg` now also
builds the slides into the package (under `mcp_materials/`), including any
descriptions from step 5. It prints one line per deck:

```text
Building course MCP material from llmgrader_mcp_config.xml:
  [fsm] 41 slides, with images, 41 described
  [review-numbers] 15 slides, text only  WARNING: no PDF given; slides are served as text only
```

| Warning | What to do |
| --- | --- |
| `... has 42 pages but ... has 41 slides -- re-export the PDF` | The PDF is out of date. Re-export it (step 2) and rebuild. |
| `no PDF given` | Add a `pdf=` to the deck, or accept text only. |

The slide images make the archive larger -- about 20 MB for 275 slides. Then
[upload `soln_package.zip`](../buildcourse/upload.md) as usual. The MCP serves
the new slides as soon as the upload finishes.

{: .note }
If `create_soln_pkg` stops with an error about `pptx` or `pymupdf`, the build
tools are not installed (step 1). If you do not want to publish slides at all,
remove or rename `llmgrader_mcp_config.xml`.

---

## Planned

- **Lab instructions and other documents**, listed in the same file.
- **Per-unit control of solutions.** Today every unit's solutions are served.
