# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode
pip install -e .

# Run dev server (http://127.0.0.1:5000, debug mode)
python run.py

# Run all tests (live model tests are deselected by default)
pytest

# Run a single test
pytest tests/services/test_unit_parser.py::test_validate_unit_file_accepts_demo_unit

# Run the Playwright UI suite
pytest tests/ui/ --browser chromium

# Run the live model tests -- real OpenAI calls, ~$0.08 a run
LLMGRADER_RUN_LIVE_TESTS=1 OPENAI_API_KEY=... pytest tests/live -m live
```

## Architecture

LLM Grader is a Flask web application that grades engineering submissions using LLMs (OpenAI). It also ships an MCP server for course-authoring assistance.

### Grading flow

```
HTTP POST /grade  (APIController, routes/api.py)
  → spawns background thread
  → Grader.grade()  (services/grader.py)
      → UnitParser  – loads question/solution/rubric from XML course package
      → PromptBuilder – assembles LLM prompt with student answer + rubric
      → OpenAI API call
      → parses GraderRawResult → GradeResult (Pydantic models)
  → client polls /grade/<job_id> until job state = completed
```

### Model registry

`llmgrader/services/models.py` is the single source of truth for the supported model slate. Every model id, price, capability flag and tier default lives there; the front end reads it through `GET /api/models`, and the grader, the CLI tools and the admin allow-list import from it. Add or retire a model by editing that file alone — see `docs/developer/models.md`.

Tiers (`simple`, `standard`, `complex`) name the **difficulty of the graded problem**, not the price of the model. `DEFAULT_MODEL_SIMPLE` / `_STANDARD` / `_COMPLEX` are derived from the `tier_default` flags; never hard-code a model id elsewhere. Course XML selects a model with `preferred_model`, which accepts a tier name (preferred, survives a slate refresh) or a concrete id.

`GradeResult` is the canonical output: `points`, `max_points`, `feedback`, `full_explanation`, and per-rubric-item `rubric_eval` (evidence, point_awarded, result).

### Course content format

Courses are defined as **XML files** validated against `llmgrader/schemas/unit.xsd` (questions/solutions/rubrics) and `llmgrader/schemas/llmgrader_config.xsd` (course metadata and unit references). `UnitParser` handles schema validation, CDATA cleaning, and line-number mapping for error reporting.

`PromptBuilder` selects from several prompt templates depending on grading mode: `partial_multi_all`, `partial_multi_single`, `partial_single`, and binary-credit equivalents.

### MCP server

`llmgrader/mcp/server.py` is a FastMCP server (`llmgrader_mcp_server` entry point, stdio transport) that exposes tools for authoring course XML: skeleton generation, validation, repo scanning, question examples, and rubric guidance. It is separate from the Flask app and has its own test suite under `tests/mcp/`.

### Authentication

Controlled by `LLMGRADER_AUTH_MODE` env var (`normal` = Google OAuth, `dev-open` = no auth). OAuth credentials: `LLMGRADER_GOOGLE_CLIENT_ID`, `LLMGRADER_GOOGLE_CLIENT_SECRET`, `LLMGRADER_GOOGLE_REDIRECT_URI`. Initial admin seeded via `LLMGRADER_INITIAL_ADMIN_EMAIL`. User/admin data stored in SQLite.

### Gradescope integration

`llmgrader/gradescope/autograde.py` reads a submission results JSON and writes the Gradescope-formatted output to `/autograder/results/results.json`. This runs outside the Flask app as a standalone script.
