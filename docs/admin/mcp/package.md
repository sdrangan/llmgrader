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
- **Course materials**: lecture slides, demos, labs, handouts -- whatever your
  course has. These are not part of the grading package, so they are declared
  in a second file, `llmgrader_mcp_config.xml`, and built into the same
  package. You still upload one archive per course.

The same file can also publish units the portal does not serve, such as past
exams, and describe each kind of unit; see
[Past Exams and Unit Types](./units.md). Material kept in a public GitHub
repository -- demo code, lab starting files, a docs site -- can be served
straight from it, without rebuilding the package for every fix; see
[Material from a Public Repository](./sources.md).

If you only want to publish questions, skip to [Deploying](./deploy.md).

---

## The model

Courses' material is shaped differently -- one has slides and Jupyter
notebooks, another LaTeX handouts and MATLAB scripts, another a lab manual in
PDF -- so you describe yours with four ideas, and the tools stay the same.

| Idea | What it is |
| --- | --- |
| **Kind** | A label you choose -- `slides`, `demo`, `lab`, `handout` -- with a sentence the assistant reads, and a policy. |
| **Unit** | A unit `<name>` from `llmgrader_config.xml`, or a **material unit** you declare here for material that has no questions: course setup, a lecture with no problem set. |
| **Item** | What a student is pointed to: an id, a title, a kind, one or more units, and its **parts** (files or folders). A demo used in Units 4 and 5 is one item with two units. |
| **Format** | How a file is read. It follows from the file, never from the kind, so you never explain how to read your own kinds. |

**Formats:**

| Format | Files | A student's assistant gets |
| --- | --- | --- |
| `slides` | a `.pptx`, with its PDF export | each slide's image, title, text, speaker notes and figure description |
| `pdf` | a `.pdf`: a handout, problem sheet, paper, lab manual | each page's image, text and figure description |
| `page` | Markdown in a docs tree published as a site ([Sources](./sources.md)) | the text, with a link to the published page |
| `text` | code, LaTeX, Markdown, notebooks (outputs removed), anything else that is text | numbered lines |

LaTeX is read as text. Publish its compiled PDF as a second part of the same
item and the assistant can use either.

**Policies**, one per kind:

| Policy | Served | For |
| --- | --- | --- |
| `open` (default) | as it is | slides, demos, labs, handouts |
| `tutor` | with the instruction `get_solution` carries: help the student reason toward the answer, and show it only if they ask | worked solutions you want available as a tutor |
| `private` | listed by title and kind, so the assistant can say it exists; never read or searched, and **never built into the package** | answer keys, material under embargo |

---

## Step 1: Install the build tools

Building slides and PDFs needs two extra Python packages, used only on your
machine -- the portal does not need them. In the environment where you run
`create_soln_pkg`:

```bash
pip install -e "path/to/llmgrader[mcp-build]"
```

(or `pip install "llmgrader[mcp-build]"` for an installed copy). This adds
`python-pptx`, which reads the slide text and notes, and `pymupdf`, which
renders slide and PDF pages and reads a PDF's text.

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
`llmgrader_config.xml`**, with a `<materials>` element:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<llmgrader_mcp>
  <!-- Where the files live.  Paths are relative to this file. -->
  <roots>
    <root id="pub" path="../hwdesign"/>
    <root id="soln" path="."/>
  </roots>

  <materials>
    <kind id="slides" description="Lecture slides, one or two decks per unit"/>
    <kind id="handout" description="Handouts and problem sheets"/>
    <kind id="lab-solution" policy="tutor" description="Worked solutions to the labs"/>
    <kind id="answer-key" policy="private" description="Exam answer keys"/>

    <unit id="setup" name="Course setup" description="Installing Vitis and the Python environment"/>

    <item id="fsm" kind="slides" root="pub" unit="Unit 2:  Sequential Logic and FSMs"
          path="units/unit02_fsm/fsm.pptx" pdf="units/unit02_fsm/fsm.pdf"/>

    <!-- A PDF is read page by page. -->
    <item id="kmaps" kind="handout" root="pub" unit="Unit 1:  Data Types and Combinational Logic"
          path="handouts/kmaps.pdf"/>

    <!-- A folder is read file by file; build output and binaries are left out. -->
    <item id="cubic-soln" kind="lab-solution" root="soln"
          unit="Unit 3:  Floating and Fixed-Point" path="labs/cubic/soln"/>

    <!-- Private: listed, never built into the package. -->
    <item id="midterm-key" kind="answer-key" root="soln"
          unit="Unit 5:  FIFOs and Streaming Interfaces" path="exams/midterm_key.pdf"/>

    <!-- An item can have several parts, and several units. -->
    <item id="install" kind="handout" root="pub" unit="setup" also="Unit 0:  Introduction to Hardware Design"
          title="Installing the tools">
      <description>Step-by-step installation, with the LaTeX source.</description>
      <part path="handouts/install.pdf"/>
      <part path="handouts/install.tex"/>
    </item>
  </materials>
</llmgrader_mcp>
```

**`<kind>`**, one per kind, first:

| Attribute | Meaning |
| --- | --- |
| `id` | Short name: lowercase letters, digits, `-` and `_`. |
| `description` | What a student's assistant reads about this kind. One sentence. |
| `policy` | `open` (default), `tutor` or `private`. |

**`<unit>`**, a material unit, after the kinds:

| Attribute | Meaning |
| --- | --- |
| `id` | Short name, so items can say `unit="setup"`. |
| `name` | What `list_units` and `list_materials` call it. |
| `description` | Optional. |

**`<item>`**:

| Part | Meaning |
| --- | --- |
| `id` | Short name the assistant uses: lowercase letters, digits, `-` and `_`. Unique in the course. A deck's id is also in its slide links. |
| `kind` | One of your kinds. |
| `unit`, `also`, `<unit>` | The units it goes with. Each is a unit's `<name>` from `llmgrader_config.xml` -- spacing and case do not matter -- or a material unit's id or name. **Every item needs at least one**, or the build stops and names it. |
| `path` | A file or folder, relative to its root. Read by its extension: a `.pptx` as slides, a `.pdf` page by page, a folder file by file, anything else as text. |
| `pdf` | With a `.pptx` path: its PDF export, for the slide images. |
| `<part path>` | More files or folders, in the same way (a `<part>` may carry its own `pdf`). |
| `title` | Optional. Without it, a deck or PDF is named by its first page's title. |
| `<description>` | Optional. One or two sentences, shown in `list_materials`. |
| `root` | Which `<root>` the paths are relative to. Without it, they are relative to this file. |
| `source` | `package` (default) for files built into the package; `mirror` for files in a public repository ([Sources](./sources.md)). |

**Only what is listed is published.** Package paths are explicit: no
wildcards. A course repository also holds exams, autograder keys and lab
solutions, and a new file must never be published because nobody remembered
to exclude it. A folder you list is published whole, minus build output and
binaries, so list the folder you mean -- `labs/cubic/soln`, not `labs/`.

**An `<item>` with only an id** changes an item made elsewhere rather than
making one: its `title`, `<description>` or `kind`, and more units.

```xml
<item id="fsm" title="Sequential logic and FSMs" also="Unit 3:  Floating and Fixed-Point"/>
```

An id that matches no item stops the build.

**Units by name.** Copy unit names from `llmgrader_config.xml`. A student
asking about "unit 2" then gets its problems and its materials together.

---

## Step 4: Check what will be published

From the folder with the two config files:

```bash
llmgrader_mcp_build --dry-run
```

It lists every item and every file it would read, and builds nothing.
**Read this list before every upload.** If your repository is somewhere other
than the `path` in the config, point to it without editing the file:

```bash
llmgrader_mcp_build --dry-run --root pub=C:/path/to/hwdesign
```

To see the index exactly as students' assistants will -- every item, its
kind, its units **and where each unit came from**, its parts and their
formats -- run:

```bash
llmgrader_mcp_build --materials
```

```text
  slides (12): Lecture slides, one or two decks per unit
    [fsm] Unit 2 Sequential Logic and FSMs  (package)
        unit  Unit 2:  Sequential Logic and FSMs    <- config
        parts 1 slides
  lab (6): Lab instructions and the files students start from
    [cmdresp] Command-Response Mini-Project  (mirror)
        unit  Command-Response Mini-Project    <- materials.xml
        parts 5 page, 1 text
```

It is free and builds nothing into the package. It uses `soln_package/` when
that has been built, and otherwise builds the package items into a temporary
folder first, which takes a minute for a few hundred slides.

---

## Step 5 (optional): Describe the figures

Search works on words, and much of a slide is a picture: a state diagram's
"Moore machine" may appear in no slide's text at all. This optional step asks
an OpenAI vision model to write a few sentences about each slide's figures --
and each page of a packaged PDF -- so search can find them, and an assistant
knows what a figure shows before it opens it. (PDFs in a public repository
are rendered by the portal and are not described.)

It is the one step that **costs money**, so it is separate and never runs on its
own. It costs very little -- about **$0.27 for 500 slides** with the default
model -- and you pay **once per slide**: results are saved in a
`llmgrader_mcp_descriptions/` folder beside your config, one file per deck, and
reused by every later build.

1. **Make sure the PDFs are up to date** (step 2). Only slides with an image
   can be described; text-only decks are skipped. The file for a deck is
   named by its item id.
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

**Slides with an empty description.** The model leaves a description empty
when it judges a slide to be text only. If some figure slides came back empty,
redo just those -- it costs a few cents:

```bash
llmgrader_mcp_build --describe --redo-empty
```

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
builds the package items (under `mcp_materials/`), including any descriptions
from step 5. It prints one line per deck or PDF, and one per item:

```text
Building course MCP material from llmgrader_mcp_config.xml:
  [fsm] 41 slides, with images, 41 described
  [kmaps] 6 pages, with images, 0 described
  [fsm] slides: 1 paged, 0 text file(s)
  [cubic-soln] lab-solution: 0 paged, 7 text file(s), 2 not servable and left out
  [midterm-key] answer-key, private: listed only, nothing built
```

| Message | What to do |
| --- | --- |
| `... has 42 pages but ... has 41 slides -- re-export the PDF` | The PDF is out of date. Re-export it (step 2) and rebuild. |
| `no PDF given` | Add a `pdf=` to the item, or accept text only. |
| `not servable and left out` | Binaries, build output, files over 256 KB or of an unknown type in a folder. Expected; list a file by itself to be told why it cannot be served. |

**The build stops**, naming what to fix, on an unknown kind or unit, a file
that is not there, two items with one id, an `<item id>` that changes no item,
or an item with no unit.

The slide images make the archive larger -- about 20 MB for 275 slides. Then
[upload `soln_package.zip`](../buildcourse/upload.md) as usual. The MCP serves
the new material as soon as the upload finishes.

{: .note }
If `create_soln_pkg` stops with an error about `pptx` or `pymupdf`, the build
tools are not installed (step 1). If you do not want to publish materials at
all, remove or rename `llmgrader_mcp_config.xml`.

{: .warning }
A package built before `<materials>` existed serves no slides on a portal
that has it: rebuild and upload the package when the portal is updated.

---

## Package versions

Every package `create_soln_pkg` builds carries a version, written into it as
`package_info.json` and printed at the end of the build:

```text
Package version: 2026-10-07.3f9c2a1
  hwdesign-soln: 54cc4a3 (clean)
  hwdesign: 089706c (6 uncommitted changes, 4 files not in git)
```

The version is the build date and the start of a hash over every file in the
package, so it is never typed by hand and two different packages never share
one. After you upload it, **Manage Courses** shows it beside the course, and
every grade and every MCP call records the version that answered, so either
can be traced back to the exact rubric, solution or slide.

Below it is each repository the package was built from, at its commit, with
a count of what that commit alone would not reproduce. Only the files the
package is built from are counted: unit files and their images, assets, the
package items' files (never a private item's), and the configuration files. A stray file elsewhere in
the repository is not. `uncommitted changes` are edited files; `files not in
git` are new or ignored ones. Commit them before building if you want the
package to be reproducible from the repositories.

A package built before versions existed, or by hand, is given one when the
portal loads it: `computed.` and the start of the same hash.

---

## Planned

- **Per-unit control of solutions.** Today every unit's question solutions are
  served; a kind's policy covers only materials.
- **A notebook format** reading a notebook's cells as Markdown and code, if a
  course needs more than today's text with outputs removed.
