---
title:  Creating a Unit
parent: Building a Course Package
nav_order: 2
has_children: false
---

# Unit XML Format 

Each unit in the course is described by a **unit XML file**.
This file defines the questions, reference solutions, grading notes, point assignments, and other metadata needed by the LLM grader.
A complete example is available in the repository at:

```
llmgrader/example_repo/unit1/basic_logic.xml
```

This document explains the structure and meaning of each element in the unit XML schema.

---

## 🧱 Overall Structure

A unit XML file has the following high‑level structure:

```xml
<unit id="...">
    <question ...>
        <text>...</text>
        <solution>...</solution>
        <grading_notes>...</grading_notes>
        <parts>...</parts>
        <preferred_model>...</preferred_model>
    </question>

    <!-- Additional <question> elements -->
</unit>
```

The `<unit>` element is the root.  Each `<question>` element defines one question within the unit.

---

## 🏷️ `<unit>` Element

| Attribute | Required | Description |
|----------|----------|-------------|
| `id` | Yes | A unique identifier for the unit (e.g., `unit1_basic_logic`) |

The `<unit>` element contains one or more `<question>` elements.

---

## ❓ `<question>` Element

Each question is defined by a `<question>` block.

| Attribute | Required | Description |
|----------|----------|-------------|
| `qtag` | Yes | A short identifier for the question (e.g., `q1`, `q2a`) |
| `points` | Yes | Total points assigned to the question |

A question typically contains:

- `<text>` — the question prompt (HTML allowed)
- `<solution>` — the reference solution (HTML allowed)
- `<grading_notes>` — instructor notes for the grader
- `<parts>` — optional breakdown of points
- `<preferred_model>` — optional model hint for the grader

---

## 📝 `<text>` Element

Contains the question prompt.  HTML is allowed and often wrapped in CDATA:

```xml
<text><![CDATA[
    <p>Explain the propagation delay of this circuit.</p>
]]></text>
```

---

## 🧠 `<solution>` Element

Contains the reference solution.  Also supports HTML and CDATA.
This is what the grader uses to evaluate student responses.

---

## 🧾 `<grading_notes>` Element

Optional instructor‑only notes that help guide the grader’s reasoning.  
These notes are not shown to students.  Examples include:

- common misconceptions  
- expected reasoning steps  
- acceptable alternate answers  

---

## 🧩 `<parts>` Element (Optional)

Breaks the question into sub‑components for partial credit.

Structure:

```xml
<parts>
    <part id="p1" points="5">Correct formula</part>
    <part id="p2" points="5">Correct numeric evaluation</part>
</parts>
```

| Attribute | Required | Description |
|----------|----------|-------------|
| `id` | Yes | Identifier for the part |
| `points` | Yes | Points assigned to this part |

If omitted, the grader treats the question as a single block worth the full `points`.

---

## 🤖 `<preferred_model>` Element (Optional)

Specifies which LLM model the grader should use for this question.

Example values:

- `gpt-4o-mini`
- `gpt-4o`
- `claude-3.5-sonnet`

If omitted, the grader uses the system default.

---

## 🧪 Validation Rules

The grader enforces:

- `<unit>` must contain at least one `<question>`
- Each `<question>` must have:
  - `qtag`
  - `points`
  - `<text>`
  - `<solution>`
- Points must be numeric
- `<parts>` (if present) must sum to the question’s total points

Malformed XML results in a clear error during upload.

---

## 📚 Example Reference

A complete, real‑world example is available at:

```
llmgrader/example_repo/unit1/basic_logic.xml
```

This is the best place to see the schema in action.

---

Next: Go to [Uploading a Solution Package](./upload.md) for instructions on packaging and uploading units to the admin interface.