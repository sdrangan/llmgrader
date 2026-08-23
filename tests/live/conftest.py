"""Session plumbing for the opt-in live model suite.

These tests put real requests on the OpenAI API and cost real money, so they
are gated twice over -- see :func:`live_enabled` -- and excluded from a bare
``pytest`` run by the ``-m 'not live'`` default in ``pyproject.toml``.

The suite grades through the real :class:`~llmgrader.services.grader.Grader`
against a tiny course package under ``fixtures/``.  Nothing here hand-rolls an
``openai`` call: a hand-rolled call would test the test rather than the app,
and the failure this suite exists to catch -- a retired or renamed model id --
only shows up on the path the app actually takes.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from llmgrader.services.grader import Grader
from llmgrader.services.gradetests import LONG_CONTEXT_CAVEAT, price_call
from llmgrader.services.models import get_spec


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
REPORT_PATH = Path(__file__).resolve().parent / "_report.json"

#: Generous next to the 20 s app default: these are reasoning models, one of
#: the questions enables web search, and a timeout here would read as an
#: unreachable model.
LIVE_TIMEOUT = 90.0

#: `long_context_threshold` is a guess (see plan section 9 -- OpenAI publishes
#: the two rate pairs but not the token count where the second begins), so any
#: cost priced at the long rate is a floor, not a figure to quote.  The text and
#: the pricing arithmetic now live in `services/gradetests.py`, so this suite
#: and `llmgrader_test run --cost` cannot drift apart; they are re-exported here
#: because this is where they were first written down.


@pytest.fixture(scope="session")
def live_enabled() -> None:
    """Gate the suite on two independent conditions, both required.

    Skips -- never fails -- when either is missing: a developer without a key
    should be able to run the whole suite and see it skip cleanly.
    """
    if os.getenv("LLMGRADER_RUN_LIVE_TESTS") != "1":
        pytest.skip("set LLMGRADER_RUN_LIVE_TESTS=1 to run live model tests")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


@pytest.fixture(scope="session")
def live_grader(live_enabled, tmp_path_factory):
    """A Grader loaded with the fixture course package, on throwaway storage.

    ``LLMGRADER_STORAGE_PATH`` is redirected so the run's submissions land in a
    temporary SQLite database rather than the developer's ``local_data/``.  The
    package is staged into a temp directory because the parser stages units out
    of it into the scratch tree.
    """
    root = tmp_path_factory.mktemp("live")
    pkg = root / "pkg"
    shutil.copytree(FIXTURE_DIR, pkg)

    mp = pytest.MonkeyPatch()
    mp.setenv("LLMGRADER_STORAGE_PATH", str(root / "storage"))
    try:
        grader = Grader(scratch_dir=str(root / "scratch"), soln_pkg=str(pkg))
        assert not grader.unit_validation_errors, grader.unit_validation_errors
        yield grader
    finally:
        mp.undo()


def _last_submission(grader: Grader) -> dict:
    """Token counts and latency for the most recent grade, from the app's DB.

    ``Grader.grade`` returns only the GradeResult; it records usage by writing
    a submission row.  Reading that row keeps the cost report measuring what
    the app measures, rather than a second accounting maintained by the tests.
    """
    conn = sqlite3.connect(grader.db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT model, tokens_in, tokens_out, latency_ms, timed_out "
            "FROM submissions ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else {}


class CostRecorder:
    """Accumulates one row per live call, for the end-of-session report."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, model_id: str, scenario: str, usage: dict,
               tool_enabled: bool = False) -> None:
        spec = get_spec(model_id)
        tokens_in = int(usage.get("tokens_in") or 0)
        tokens_out = int(usage.get("tokens_out") or 0)
        usd, long_rate = price_call(spec, tokens_in, tokens_out)
        self.calls.append(
            {
                "model": model_id,
                "scenario": scenario,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "seconds": round((usage.get("latency_ms") or 0) / 1000.0, 3),
                "usd": usd,
                "long_context_rate": long_rate,
                # Search results land in the next request's input, so a
                # tool-enabled call runs ~10x the input of a routine one.
                # Averaging the two together would inflate the per-question
                # figure roughly 3x, which is the figure the slate is argued
                # from -- so they are counted separately.
                "tool_enabled": tool_enabled,
            }
        )

    def by_model(self) -> dict:
        totals: dict = {}
        for call in self.calls:
            entry = totals.setdefault(
                call["model"],
                {
                    "calls": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "seconds": 0.0,
                    "usd": 0.0,
                    "long_context_calls": 0,
                    "grading_calls": 0,
                    "usd_grading": 0.0,
                    "tool_calls": 0,
                    "usd_tool": 0.0,
                },
            )
            entry["calls"] += 1
            entry["tokens_in"] += call["tokens_in"]
            entry["tokens_out"] += call["tokens_out"]
            entry["seconds"] += call["seconds"]
            entry["usd"] += call["usd"]
            entry["long_context_calls"] += 1 if call["long_context_rate"] else 0
            if call["tool_enabled"]:
                entry["tool_calls"] += 1
                entry["usd_tool"] += call["usd"]
            else:
                entry["grading_calls"] += 1
                entry["usd_grading"] += call["usd"]

        for entry in totals.values():
            entry["seconds"] = round(entry["seconds"], 3)
            entry["mean_seconds"] = round(entry["seconds"] / entry["calls"], 3)
            entry["usd_per_call"] = entry["usd"] / entry["calls"]
            # The headline the slate is argued from: what 1000 routine graded
            # questions cost at this model's measured request shape.
            # Tool-enabled calls are excluded -- see `record`.
            grading = entry["grading_calls"]
            entry["usd_per_question"] = entry["usd_grading"] / grading if grading else None
            entry["usd_per_1000_questions"] = (
                entry["usd_per_question"] * 1000 if grading else None
            )
            tool = entry["tool_calls"]
            entry["usd_per_tool_call"] = entry["usd_tool"] / tool if tool else None
        return totals


@pytest.fixture(scope="session")
def cost_recorder(request) -> CostRecorder:
    """Session-wide collector; writes ``_report.json`` on teardown."""
    recorder = CostRecorder()
    request.session._llmgrader_cost = recorder
    yield recorder

    if not recorder.calls:
        return

    by_model = recorder.by_model()
    REPORT_PATH.write_text(
        json.dumps(
            {
                "note": LONG_CONTEXT_CAVEAT,
                "per_question_note": (
                    "usd_per_question and usd_per_1000_questions cover routine "
                    "grading calls only; a web-search call carries the search "
                    "results in its input and is reported separately as "
                    "usd_per_tool_call."
                ),
                "timeout_seconds": LIVE_TIMEOUT,
                "total_usd": sum(entry["usd"] for entry in by_model.values()),
                "by_model": by_model,
                "calls": recorder.calls,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.fixture(scope="session")
def run_grade(live_grader, cost_recorder):
    """Grade one answer against the fixture unit and record what it cost."""

    def _run(model_id: str, qtag: str, answer: str, scenario: str,
             solution_images: list | None = None) -> dict:
        question = live_grader.units["Live Smoke Unit"][qtag]
        tool_enabled = bool(question.get("tools"))
        grade = live_grader.grade(
            question,
            answer,
            unit_name="Live Smoke Unit",
            qtag=qtag,
            model=model_id,
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=LIVE_TIMEOUT,
            solution_images=solution_images,
        )
        cost_recorder.record(
            model_id, scenario, _last_submission(live_grader), tool_enabled=tool_enabled
        )
        return grade

    return _run


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Print the cost/latency table, the artifact the next slate refresh uses."""
    recorder = getattr(terminalreporter._session, "_llmgrader_cost", None)
    if recorder is None or not recorder.calls:
        return

    write = terminalreporter.write_line
    totals = recorder.by_model()

    write("")
    write("Live model cost / latency")
    header = (
        f"{'model':<16}{'calls':>6}{'tok in':>9}{'tok out':>9}"
        f"{'$ run':>9}{'$/question':>12}{'$/1000 q':>11}"
        f"{'$/web call':>12}{'mean s':>9}"
    )
    write(header)
    write("-" * len(header))
    for model_id, entry in sorted(totals.items()):
        per_question = entry["usd_per_question"]
        per_1000 = entry["usd_per_1000_questions"]
        per_tool = entry["usd_per_tool_call"]
        write(
            f"{model_id:<16}{entry['calls']:>6}{entry['tokens_in']:>9}"
            f"{entry['tokens_out']:>9}{entry['usd']:>9.4f}"
            f"{(f'{per_question:.6f}' if per_question is not None else '-'):>12}"
            f"{(f'{per_1000:.2f}' if per_1000 is not None else '-'):>11}"
            f"{(f'{per_tool:.6f}' if per_tool is not None else '-'):>12}"
            f"{entry['mean_seconds']:>9.1f}"
        )
    write("-" * len(header))
    write(f"total for this run: ${sum(e['usd'] for e in totals.values()):.4f}")
    write(
        "$/question covers routine grading only; a web-search call carries the "
        "search results in its input and costs several times more."
    )
    write(LONG_CONTEXT_CAVEAT)
    write(f"wrote {REPORT_PATH}")
