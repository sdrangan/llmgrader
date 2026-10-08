---
title: Printing a Unit as an Exam
parent: Building a Course
nav_order: 5.2
has_children: false
---

# Printing a Unit as an Exam or Handout

A unit can say how it prints, in one or more optional `<print>` blocks **after
all its questions**. `create_qfile --print` renders a block to HTML and, with
`--pdf`, to a PDF: an exam with a title page, points and answer pages, or a
plain handout. One file holds both the questions and how to print them.

The portal and the course MCP ignore `<print>` entirely: students never see
it, and the grader and their assistants read the questions exactly as if it
were not there.

---

## A complete exam

```xml
<unit id="midterm_f2026" title="Midterm, Fall 2026" version="1.0"
      unit_type="midterm" semester="Fall 2026">
  <question qtag="Signed logic types"> ... </question>
  <question qtag="Simple division counter"> ... </question>
  <question qtag="FIFO"> ... </question>

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
    <question qtag="FIFO"/>
  </print>
</unit>
```

This prints:

1. **A title page**: the title, course, instructors, date and duration; a
   labelled line for each field; the instructions; and a table of each
   problem's points with the total and an empty score column.
2. **Each problem on a new page**, headed *Problem n (p points)*, followed by
   its **answer pages**, each headed *"Use this page for Problem n."*
3. **A footer on every page**: *Page n of N*.

Text and math are set in Computer Modern, so the PDF looks like a LaTeX exam.

## A handout

A problem-set handout needs one line:

```xml
  <print id="handout" answer_pages="0" page_per_question="false"/>
```

It prints the unit's title as a heading, then every question in order, run
together, with no answer pages.

---

## The `<print>` block

| Part | Meaning |
| --- | --- |
| `id` | Required. Names the block for `--print <id>`: lowercase letters, digits, `-` and `_`. Unique within the unit. |
| `answer_pages` | Blank pages after each question. Default **1** if the block has a `<title_page>`, **0** otherwise. |
| `page_per_question` | `true` starts each question on a new page. Default **true** with a `<title_page>`, **false** otherwise. |
| `<title_page>` | Optional. Without it, the unit's title is printed as a heading. |
| `<question qtag answer_pages>` | Optional, repeated. The questions to print, **in printed order**; `answer_pages` overrides the block's default for that question. Without any, every question prints in document order. |

Everything is optional except `id`. A `<print>` block must come after the
last `<question>`.

**The question list is the printed order, and may be a subset.** One unit can
print a makeup exam, or a shorter version, from a second block, without its
questions being edited. A `qtag` that is not a question in the unit, or one
listed twice, is a validation error: it would otherwise drop a problem from
the paper without a word.

### `<title_page>`

Every element is optional, in any order.

| Element | Printed |
| --- | --- |
| `<title>` | The heading. Default: the unit's `title`. |
| `<course>`, `<instructors>` | Lines under the title. |
| `<date>`, `<duration>` | One line, joined with a comma. |
| `<fields>` | One `<field>` per labelled line to fill in: *Name*, *NetID*, ... |
| `<instructions>` | One `<item>` per bullet. An item may contain inline HTML such as `<code>`. |

**Points** come from each question's `<parts>`: shown in each problem's
heading and totalled on the title page. A question with no points shows none.

**Problem titles.** A problem is headed *Problem n*, followed by its `qtag`
unless the question text already opens with it -- a question that starts
`<strong>FIFO.</strong>` is not titled twice.

**Answer page headers are generated**, never written by hand, so they cannot
go stale when questions are reordered.

---

## Running `create_qfile --print`

```bash
create_qfile --input exams/midterm_f2026.xml --print exam --pdf
```

writes `exams/midterm_f2026_exam.html` and `exams/midterm_f2026_exam.pdf`.

| Option | Effect |
| --- | --- |
| `--print <id>` | Render the block with that `id`. |
| `--print` | Render the unit's only block. With several, it asks for an id; with none, it prints the unit's title and every question. |
| `--soln` | **The key**: each question is followed by its solution, and the answer pages are left out. Writes `..._exam_soln.html`. |
| `--pdf` | Also write the PDF, with the *Page n of N* footer. |
| `--config` | As without `--print`: resolves `/pkg_assets/...` figures (see [Creating HTML Files](./htmlnotes.md)). |

The PDF needs Playwright and an internet connection, as without `--print`:
MathJax and the Computer Modern fonts are loaded when the page renders.

**Check the PDF before printing.** A long question can run past one page;
that is the question's length, not a setting -- give it a second answer page,
or split it.
