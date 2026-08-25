---
nav_exclude: true
---

# LLM Grader

LLM Grader is an open-source autograding engine for engineering courses.  It is
built for the assignments traditional autograders cannot handle: multi-step
derivations, design tradeoffs, approximations, and open-ended justification.

Instructors define questions, reference solutions, and rubrics as structured XML.
Students answer in a web portal and get immediate, rubric-referenced feedback, so
they can iterate in a *try → grade → improve* loop.  Final grades still flow
through Gradescope and your LMS.

The tool is currently used in
[Introduction to Hardware Design](https://sdrangan.github.io/hwdesign/docs/), an
MS course at NYU.

## Key Features

- **Structured problem definitions** capturing instructor intent, reference
  solutions, rubrics, and grading notes
- **Agent-assisted authoring** via an MCP server, so an AI agent in VS Code can
  read your existing homework and draft the course XML
- **Testable grading** — write trial answers, declare the score each should
  receive, and re-run the suite from the command line to confirm a rubric edit or
  a model change still grades the way you intended
- **Transparent grading traces** showing why the model awarded each point
- **Gradescope export**, including a standalone autograder that makes no LLM calls
- **Privacy by design** — grading records are never linked to student identities,
  and student API keys are never stored on the server

## Quickstart

Get the example course running locally in about 15 minutes — no Google Cloud
setup, no deployment:

```bash
git clone https://github.com/<your-github-user>/llmgrader.git
cd llmgrader
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .
python run.py --soln_pkg example_repo/soln_package
```

Then open <http://127.0.0.1:5000/>, add your OpenAI key under
**File → Preferences**, and grade a question.

Full walkthrough: [Quickstart guide](https://sdrangan.github.io/llmgrader/docs/admin/gettingstarted/quickstart.html)

## Documentation

Full documentation is at
[sdrangan.github.io/llmgrader](https://sdrangan.github.io/llmgrader/docs).

- [What you need](https://sdrangan.github.io/llmgrader/docs/admin/gettingstarted/requirements.html)
- [Administrator guide](https://sdrangan.github.io/llmgrader/docs/admin/) — setup,
  authoring, deployment, Gradescope
- [Student guide](https://sdrangan.github.io/llmgrader/docs/student/)
- [Developer guide](https://sdrangan.github.io/llmgrader/docs/developer/)

## Status

LLM Grader is early-stage and evolving quickly, but it is in real classroom use.
Contributions, critiques, and experiments are welcome.

## People

Developed by
[Sundeep Rangan](https://wireless.engineering.nyu.edu/sundeep-rangan/), Professor
of Electrical and Computer Engineering at NYU and Director of NYU Wireless.

## License

See [LICENSE](LICENSE).
