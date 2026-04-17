# LLMGrader Agent Entry Point

Use this repo guidance when your task is **course authoring**: editing `llmgrader_config.xml` and/or unit XML files that define `<unit>` and `<question>` content.

Authoring instructions live in:
- `agentdocs/authoring.md`
- `agentdocs/templates/minimal_question.xml`
- `agentdocs/templates/partial_credit_question.xml`

Rules for edits:
- Keep edits minimal and localized; do not refactor unrelated XML.
- Preserve XML validity and existing structure.
- After edits, run validation/preview commands before finishing:
  - `create_soln_pkg --config <path/to/llmgrader_config.xml>` (validates config + referenced units)
  - `create_qfile --input <path/to/unit.xml> [--config <path/to/llmgrader_config.xml>] [--soln] [--pdf]`
