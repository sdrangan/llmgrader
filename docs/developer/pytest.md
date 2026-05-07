---
title: Unit testing and CI/CD
parent: Developer Guide
nav_order: 2
has_children: false
---

# Unit Testing and CI/CD

## What is Unit Testing and CI/CD

**Unit testing** means running automated checks that verify individual pieces of your code behave correctly. Each test calls a specific function or endpoint with known inputs and asserts the output matches what you expect. Tests catch regressions — bugs introduced by a change that accidentally breaks something that was previously working.

This project currently has unit tests covering:

- **Service layer** (`tests/services/`) — grading logic, XML parsing, prompt construction, authentication, and API routes
- **MCP server** (`tests/mcp/`) — course XML authoring tools, validation, and example browsing
- **Scripts** (`tests/scripts/`) — CLI utilities for building solution packages and question files

More tests will be added in the future.

There is also a separate UI test suite (`tests/ui/`) that drives a real browser using Playwright. These tests are slower and require additional setup, so they are excluded from the standard test run.

**CI/CD** (Continuous Integration / Continuous Deployment) means every time you push a commit or open a pull request, GitHub automatically runs your tests on a clean machine and reports whether they pass. "Continuous Integration" refers specifically to this automatic checking step. The "CD" (Continuous Deployment) part — automatically publishing a passing build — is not currently configured.

---

## Running Unit Tests Locally

### Prerequisites

Follow the [developer instructions](./setup.md) for creating a virtual environment with llmgrader as an editable package.

If you don't already have the test packages, install them:

```bash
pip install pytest pytest-flask pytest-mock
```

### Running the tests

Activate the virtual environment, and run all unit tests (excluding the browser-based UI suite):

```bash
pytest --ignore=tests/ui -v
```

Run a single test file:

```bash
pytest tests/services/test_unit_parser.py -v
```

Run a single test by name:

```bash
pytest tests/services/test_unit_parser.py::test_validate_unit_file_accepts_demo_unit
```

### Simulating CI locally

CI runs in a clean environment with only the dependencies in `pyproject.toml`. You can replicate this exactly before pushing to catch any missing dependencies early:

```bash
python -m venv ci-test-env
ci-test-env\Scripts\activate        # Windows
# source ci-test-env/bin/activate   # macOS / Linux

pip install -e .
pip install pytest pytest-flask pytest-mock
pytest --ignore=tests/ui -v

deactivate
```

Remove the environment when done:

```bash
rmdir /s /q ci-test-env   # Windows
# rm -rf ci-test-env       # macOS / Linux
```

## UI Tests

The UI test suite (`tests/ui/`) drives a real Chromium browser using Playwright and is excluded from the standard test run for speed. CI does not run these tests, but developers are encouraged to run them locally before merging changes that touch the frontend.

Install the browser once:

```bash
playwright install chromium
```

Then run the suite:

```bash
pytest tests/ui/ -v
```

---

## CI/CD in GitHub

### How it works

When you push a commit or open a pull request targeting `main`, GitHub automatically:

1. Spins up a fresh Ubuntu virtual machine
2. Checks out your code
3. Installs Python 3.12 and the project dependencies
4. Runs `pytest --ignore=tests/ui -v`
5. Reports the result back to GitHub

This is defined in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml). You don't need to configure anything on the GitHub website — GitHub detects the file automatically.

Pip packages are cached between runs (keyed to `pyproject.toml`), so subsequent runs skip re-downloading dependencies and complete faster.

### What you see on a check-in

After pushing, go to your commit on GitHub. You will see a small icon next to the commit hash:

- **Yellow circle** — tests are running
- **Green checkmark** — all tests passed
- **Red X** — one or more tests failed

On a pull request, the same status appears at the bottom of the PR page under "Checks". You can click through to see the full test output, including which test failed and the error message.

### What happens if tests fail

The red X is informational — it does not block you from merging by default. However, it is a signal that something is broken and should be investigated before merging.

To see what failed:

1. Click the red X on the commit or the "Details" link on the PR checks
2. Open the `unit-tests` job
3. Expand the "Run unit tests" step to see the full pytest output

Fix the failing test locally, push the fix, and a new check run starts automatically.

If you want to enforce that tests must pass before merging, enable branch protection rules under **Settings → Branches → Add rule** and check "Require status checks to pass before merging".
