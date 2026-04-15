---
title:  Creating a Unit
parent: Building a Course Package
nav_order: 3
has_children: false
---

# Unit XML Format 

Each unit in the course is described by a **unit XML file**.
This file defines the questions, reference solutions, grading rubrics and notes, point assignments, and other metadata needed by the LLM grader.
Two examples available in the repository at:

```
llmgrader/example_repo/unit1/unit1_calculus.xml
llmgrader/example_repo/unit1/unit1_python.xml

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

        <parts>...</parts>
        <required>...</required>
        <tool>...</tool>
        <preferred_model>...</preferred_model>
        <rubrics>...</rubrics>
        <grading_notes>...<grading_notes>
    </question>

    <!-- Additional <question> elements -->
</unit>
```

The `<unit>` element is the root.  Each `<question>` element defines one question within the unit.

---

## 🏷️ `<unit>` Element

| Attribute | Required | Description |
|----------|----------|-------------|
| `id` | Yes | A unique identifier for the unit (e.g., `calculus`) |

The `<unit>` element contains one or more `<question>` elements.

---

## ❓ `<question>` Element

Each question is defined by a `<question>` block.

| Attribute | Required | Description |
|----------|----------|-------------|
| `qtag` | Yes | A short identifier for the question (e.g., `q1`, `q2a`) |
| `points` | Yes | Total points assigned to the question |

A question typically contains:

- `<question_text>` — the question prompt (HTML allowed)
- `<solution>` — the reference solution (HTML allowed)
- `<parts>` — optional breakdown of points
- `<required>` — optional flag controlling whether the question is required in normal grading/export flows
- `<tool>` — optional built-in tool request for the grader
- `<preferred_model>` — optional model hint for the grader
- `<rubrics>` — optional grading rubrics
- `<grading_notes>` — instructor notes for the grader

The `rubrics` and `grading_notes` elements are described in the [next section](./rubrics.md).

---

## 📝 `<question_text>` Element

Contains the question prompt.  HTML is allowed and often wrapped in CDATA:

```xml
<question_text><![CDATA[
    <p>Find the derivative of \( y = a e^{bx} \).</p>
]]></question_text>
```

### Including Images in Question Text

If your question requires a diagram or figure, add the file or directory to the
`<assets>` section of `llmgrader_config.xml`. The unit XML should then reference
the packaged asset path using the `/pkg_assets/` URL prefix.

For example, if the config contains:

```xml
<assets>
    <asset>
        <source>unit1/images</source>
        <destination>unit1_assets</destination>
    </asset>
    <asset>
        <source>shared/func.png</source>
        <destination>unit1_assets/func.png</destination>
    </asset>
</assets>
```

Reference the image in your `<question_text>` using the `/pkg_assets/` URL prefix:

```xml
<question_text><![CDATA[
    <p>Consider the circuit shown below:</p>
        <img src="/pkg_assets/unit1_assets/circuit_diag.png" alt="Circuit diagram">
    <p>Find the output for the given inputs.</p>
]]></question_text>
```

The URL pattern is:

```
/pkg_assets/<asset-destination-path>
```

where `<asset-destination-path>` is the path created in the solution package by the
`<assets>` section of `llmgrader_config.xml`. For example, if an asset is copied to
`unit1_assets/func.png`, it is served at `/pkg_assets/unit1_assets/func.png`.

For backward compatibility, `create_soln_pkg` still recognizes an `images/` directory
next to a unit XML file and copies it to `<destination-stem>_images/`. New course
packages should prefer explicit `<assets>` mappings.

> **Note:** The `/pkg_assets/` path is served by the LLM Grader web application.
> When generating standalone HTML or PDF with `create_qfile`, pass the related
> `llmgrader_config.xml` (or keep it in a parent directory so it can be found
> automatically). `create_qfile` rewrites `/pkg_assets/...` URLs to local file
> paths for the generated document.

---

## 🧠 `<solution>` Element

Contains the reference solution.  Also supports HTML and CDATA.
This is what the grader uses to evaluate student responses.

---

## 🧩 `<parts>` Element (Optional)

Breaks the question into sub‑components for partial credit.

Structure:

```xml
<parts>
    <part id="a" points="5">Correct formula</part>
    <part id="b" points="5">Correct numeric evaluation</part>
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

Next: Go to [Uploading a Solution Package](./upload.md) for instructions on packaging and uploading units to the admin interface.