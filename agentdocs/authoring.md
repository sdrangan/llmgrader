# Agent Course-Authoring Workflow

This file is for AI agents editing llmgrader course content.

## 1) Identify the files to edit

- Course package config: `llmgrader_config.xml`
- Unit files referenced by `<units><unit><source>...</source></unit></units>` in `llmgrader_config.xml`
- Schema references:
  - `llmgrader/schemas/llmgrader_config.xsd`
  - `llmgrader/schemas/unit.xsd`
- Runtime validation logic:
  - `llmgrader/services/unit_parser.py`

## 2) Preserve required unit/question structure

For each `<question>` in a unit file:
- Required attribute: `qtag`
- Keep these elements present in practice:
  - `<question_text>`
  - `<solution>`
  - `<parts>` with at least one `<part>`
  - `<required>` (`true`/`false`)
  - `<partial_credit>` (`true`/`false`)
- Common optional elements:
  - `preferred_model` (attribute)
  - `<tool>`
  - `<rubrics>` (with `<item>` and optional `<group type="one_of">`)
  - `<rubric_total>` (`sum_positive`, `sum_negative`, `flexible`)
  - `<grading_notes>`

Notes from current parser/schema behavior:
- `question_text`, `solution`, and `grading_notes` may be empty but should remain valid XML.
- `<parts>` is required by schema.
- Part labels come from `<part_label>` (or `part id` fallback).
- For partial-credit + multi-part questions with `rubric_total` of `sum_positive`/`sum_negative`, rubric items must reference explicit parts (not `part="all"`).
- For `rubric_total=sum_positive` on multi-part questions, positive rubric totals per part must match each part's points.

## 3) Safe procedure to add a new `<question>`

1. Open the target unit XML from `llmgrader_config.xml`.
2. Copy a template from `agentdocs/templates/`.
3. Set `qtag` to a unique value in that unit.
4. Fill `<question_text>` and `<solution>` (CDATA is recommended for HTML/math-heavy content).
5. Define `<parts>` points first.
6. If using partial credit, set `<partial_credit>true</partial_credit>` and add rubric items with `point_adjustment` values consistent with parts/`rubric_total`.
7. Keep all edits local; do not reformat unrelated questions.

## 4) Validate after every edit set

Run from the course-authoring repo root:

```bash
create_soln_pkg --config llmgrader_config.xml
```

This validates config + referenced unit XML files before packaging.

For per-unit preview/validation:

```bash
create_qfile --input path/to/unit.xml --config llmgrader_config.xml
create_qfile --input path/to/unit.xml --config llmgrader_config.xml --soln
```

`create_qfile` validates the unit before generating HTML (and optional PDF with `--pdf`).
