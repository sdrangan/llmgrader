---
title:  Creating a Unit
parent: Building a Course Package
nav_order: 3
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
        <required>...</required>
        <tool>...</tool>
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
- `<required>` — optional flag controlling whether the question is required in normal grading/export flows
- `<tool>` — optional built-in tool request for the grader
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

## ✅ `<required>` Element (Optional)

Controls whether the question is treated as required by the grader and by submission/export workflows.

Example:

```xml
<required>true</required>
```

Allowed values:

- `true` — the question is required
- `false` — the question is optional

If omitted, the default is `true`.

Use `false` for questions that should remain available in the unit but should not be enforced as part of the standard required set.

---

## 🔧 `<tool>` Element (Optional)

Requests a built-in tool for the LLM grader when grading this question.

Example:

```xml
<tool>web_search</tool>
```

You may include more than one `<tool>` element, but currently only one tool value is supported:

- `web_search` — allows the model to search the web and open pages during grading

Why use `web_search`:

This is most commonly used to inspect a students GitHub repository say for projects.  The students
can provide a GitHub URL and the grader can inspect and critique the files.
Later we will use it for accessing programs written by the student and (with an python tool),
running those programs.

It can also be used:
- when correctness depends on current external information rather than only the reference solution
- when students must analyze live documentation, standards, product details, or public web resources
- when you want the grader to verify claims against an authoritative source during evaluation

Use it sparingly. Most questions should rely only on the provided question text, reference solution, and grading notes. Web search is most appropriate when the question genuinely depends on information outside the course package.

If an unsupported tool value is provided, the grader ignores it and logs a warning during unit-package loading.

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