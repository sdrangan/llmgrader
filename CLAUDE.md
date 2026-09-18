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

# Check a course's grading tests against its units (free, no API key)
llmgrader_test check example_repo/unit1/tests/calculus_tests.xml

# Grade those cases for real (costs money; --dry-run prints the call count)
llmgrader_test run example_repo/unit1/tests/calculus_tests.xml --repeat 3 --html report.html

# Have a model answer a unit blind, as a rubric stress test (--dry-run is free)
llmgrader_answer example_repo/unit1/calculus.xml --dry-run --cost
llmgrader_answer example_repo/unit1/calculus.xml --out ai_answers.xml
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

### Portal storage vs. course content

`llmgrader/services/portal_storage.py` holds `PortalStorage`: the half of the
old `Grader` that is global to a deployed portal rather than to a course -- the
SQLite path and its `DB_SCHEMA`/`init_db`/`temp_modify_db`/`insert_submission`,
the `admin-config.json` path, the `soln_images/` path, and the `FIELD_FORMAT`
display rules for a submission row. `Grader` keeps the course: units,
`course_info`, the solution package, the scratch directory and the grading
path, and holds a `PortalStorage` on `self.storage`.

`Grader` still exposes delegating shims (`db_path`, `get_admin_pref_path`,
`format_db_entry`, ...) because `routes/api.py`, `services/gradetests.py`,
`tools/replay_submissions.py` and several test modules reach through a grader
for them. They are labelled as shims in the source; new code should use
`grader.storage`.

Scratch ownership is decided in `claim_scratch_dir` (`grader.py`) and recorded
on `Grader.owns_scratch`: the first Grader to claim a directory clears it, later
ones sharing that path do not. Before the split, every `Grader.__init__`
rmtree'd unconditionally, so a second instance erased the first's staged
package. That set is process-global, so it guards several Graders in one
process and says nothing about a second gunicorn worker -- which is why the
scratch path itself carries the pid, below.

### Course registry

`llmgrader/services/course_registry.py` holds `CourseRegistry`: which courses
this portal serves, where each one's files live, and one `Grader` per course --
all sharing the single `PortalStorage`, so the database is opened and migrated
once per process. Exactly one course is registered today; the registry is what
lets a second one arrive later without another storage-layout migration.

```
<storage>/
  db/ pref/ soln_images/      # global, PortalStorage's
  courses/
    courses.json              # the registry file
    <course_id>/
      soln_pkg/               # the extracted package that is served
      uploads/                # archives as uploaded, newest three kept
      scratch/pid-<pid>/      # per course *and* per process
```

**A course id is resolved once and then read.** `<course>` in
`llmgrader_config.xml` gains an optional `<course_id>`, pattern-constrained in
`llmgrader_config.xsd` because it becomes a directory name and later a URL path
segment. When it is absent the id comes from
`LLMGRADER_MIGRATE_COURSE_ID` if that is set, and otherwise is slugged from
`<name>` + `<semester>`. Either way it is written to `courses.json` at
registration with an `id_source` of `authored`, `env` or `derived`, and every
later boot reads it from there -- so an
instructor's typo fix in `<name>` cannot silently rename the course out from
under its submissions, its storage directory and its saved student state.

**Booting a pre-registry portal migrates it.** `<storage>/soln_pkg` with no
`courses.json` is moved under `courses/<id>/soln_pkg` and registered as the
default, with no admin action. That package predates `<course_id>` by
definition, which is exactly why the slug fallback exists.

`run.py --soln_pkg <dir>` is unchanged: it registers that directory as the sole
course, uses the scratch directory it is given verbatim, and writes no registry
file.

### Model registry

`llmgrader/services/models.py` is the single source of truth for the supported model slate. Every model id, price, capability flag and tier default lives there; the front end reads it through `GET /api/models`, and the grader, the CLI tools and the admin allow-list import from it. Add or retire a model by editing that file alone — see `docs/developer/models.md`.

Tiers (`simple`, `standard`, `complex`) name the **difficulty of the graded problem**, not the price of the model. `DEFAULT_MODEL_SIMPLE` / `_STANDARD` / `_COMPLEX` are derived from the `tier_default` flags; never hard-code a model id elsewhere. Course XML selects a model with `preferred_model`, which accepts a tier name (preferred, survives a slate refresh) or a concrete id.

`GradeResult` is the canonical output: `points`, `max_points`, `feedback`, `full_explanation`, and per-rubric-item `rubric_eval` (evidence, point_awarded, result).

### Grading tests

`llmgrader/services/gradetests.py` is the single place the grading-test logic lives: parsing `<unit_test>` files, checking them against a unit, and running them through the real `Grader`. The `llmgrader_test` console script and both pytest suites (`tests/services/test_gradetests_static.py`, `tests/live/test_course_cases.py`) sit on it and add nothing of their own.

`run --gradescope` also lives there: it writes the submission zip a student would have downloaded, built from the graded cases instead of a portal session, so an uploaded autograder can be tested without answering questions by hand. The layout mirrors `downloadSubmission` in `llmgrader/static/js/dashboard.js` entry for entry — the autograder verifies its signature over the exact `results.json` bytes, so both text files are written as bytes rather than in text mode. Everything the submission can be refused for (an ambiguous qtag, a missing `LLMGRADER_PRIVATE_KEY`, an unsafe target directory) is resolved in `plan_gradescope_submission` before any grading call.

Which assertion elements a case may carry depends on the question's `<partial_credit>` mode, which lives in a different file, so `unit_test.xsd` is deliberately permissive and `check` carries roughly half the validation. The runner redirects `LLMGRADER_STORAGE_PATH` to a temp tree -- `Grader.__init__` clears the scratch dir it owns and writes a submission row per grade -- and looks token counts up by the synthetic `session_id` it passes, never by newest row. See `docs/admin/buildcourse/gradetests.md` for the instructor-facing contract.

### Answering a unit blind

`llmgrader/services/answers.py` + the `llmgrader_answer` console script ask a
model to answer a unit's questions from the **question text alone** and write
the answers as a `<unit_test>` file that `llmgrader_test run` then grades. The
planner mirrors `gradetests._plan_run` and the runner mirrors `_execute_run`,
with the grading call swapped for a free-form sibling of
`grader._make_openai_caller` -- same client construction and same
`spec.supports_temperature` gate, but no `text.format` and no
`GraderRawResult`.

The property the tool rests on is that `build_answer_prompt` sees
`question_text`, the part labels and their points, and question images, and
nothing else: never `solution`, `solution_images`, `grading_notes`, `rubrics`
or `rubric_total`. A sentinel test guards each of those fields, because a leak
there leaves every number the tool prints meaningless while still looking
fine. Provenance goes in `<description>` and an XML comment -- `caseType` is a
closed `xs:all` shared with hand-written files, so `unit_test.xsd` does not
grow an attribute for it. Empty and refusing answers are emitted and marked,
never dropped; an unresolved question image is a loud warning naming `--pkg`
rather than the fatal error `run` raises, so an image-free unit works from a
loose unit file. See `docs/admin/buildcourse/aitest.md` and
`plans/answer_cli.md`.

### Course content format

Courses are defined as **XML files** validated against `llmgrader/schemas/unit.xsd` (questions/solutions/rubrics) and `llmgrader/schemas/llmgrader_config.xsd` (course metadata and unit references). `UnitParser` handles schema validation, CDATA cleaning, and line-number mapping for error reporting.

`PromptBuilder` selects from several prompt templates depending on grading mode: `partial_multi_all`, `partial_multi_single`, `partial_single`, and binary-credit equivalents.

### MCP server

`llmgrader/mcp/server.py` is a FastMCP server (`llmgrader_mcp_server` entry point, stdio transport) that exposes tools for authoring course XML: skeleton generation, validation, repo scanning, question examples, and rubric guidance. It is separate from the Flask app and has its own test suite under `tests/mcp/`.

### Authentication

Controlled by `LLMGRADER_AUTH_MODE` env var (`normal` = Google OAuth, `dev-open` = no auth). OAuth credentials: `LLMGRADER_GOOGLE_CLIENT_ID`, `LLMGRADER_GOOGLE_CLIENT_SECRET`, `LLMGRADER_GOOGLE_REDIRECT_URI`. Initial admin seeded via `LLMGRADER_INITIAL_ADMIN_EMAIL`. User/admin data stored in SQLite.

### Gradescope integration

`llmgrader/gradescope/autograde.py` reads a submission results JSON and writes the Gradescope-formatted output to `/autograder/results/results.json`. This runs outside the Flask app as a standalone script.
