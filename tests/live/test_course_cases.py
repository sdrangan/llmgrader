"""The course's own grading tests, run against the real API.

Every ``<case>`` in every ``example_repo/**/tests/*.xml`` becomes a separately
named test, so a failure says which case broke rather than which file.  The
cases themselves are instructor content: they live in the course repo, they
diff cleanly, and they say what the grader is supposed to do with a given
student answer.

This is the paid half of the pair.  ``tests/services/test_gradetests_static.py``
checks the same files for free -- schema, qtag resolution, band sanity, rubric
coverage -- and runs in a bare ``pytest``.  Both sit on
``llmgrader/services/gradetests.py``, so a case that passes here passes in the
CLI for the same reason.

Gated exactly as the rest of ``tests/live`` is, by ``live_enabled``: both
``LLMGRADER_RUN_LIVE_TESTS=1`` and ``OPENAI_API_KEY``, plus the ``-m live``
selection that ``pyproject.toml`` deselects by default.

By default each question is graded with its own ``preferred_model``, so a run
tests exactly what students hit.  ``LLMGRADER_GRADETEST_MODEL`` overrides that
with a tier name or a model id, which is how to run the suite cheaply.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llmgrader.services.gradetests import (
    DEFAULT_TIMEOUT,
    FAILING_VERDICTS,
    RunOptions,
    expand_paths,
    load_test_file,
    run_test_files,
)


pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parents[2]
COURSE_TEST_GLOB = str(REPO_ROOT / "example_repo" / "**" / "tests" / "*.xml")


def _discover_cases() -> list:
    """Every case in the course repo, as one parametrization each.

    Collection happens on a bare ``pytest`` too, so a file that cannot be read
    must not take the whole suite down with it: the static suite is where a
    broken test file is meant to be reported.
    """
    params = []
    try:
        paths = expand_paths([COURSE_TEST_GLOB])
    except Exception:
        return params

    for path in paths:
        try:
            test_file = load_test_file(path)
        except Exception:
            continue
        for case in test_file.cases:
            params.append(
                pytest.param(path, case.case_id, id=f"{Path(path).stem}:{case.case_id}")
            )
    return params


COURSE_CASES = _discover_cases()


def _failure_report(case_run) -> str:
    lines = [
        f"case `{case_run.case_id}` ({case_run.qtag}) came out {case_run.verdict}",
        " ".join(case_run.description.split()),
    ]
    for attempt in case_run.attempts:
        if attempt.error is not None:
            lines.append(f"  error: {attempt.error}")
        for failure, evidence in attempt.failure_lines():
            lines.append(f"  {failure}")
            if evidence:
                lines.append(f'    evidence: "{" ".join(evidence.split())}"')
        lines.append(f"  feedback: {' '.join(attempt.feedback.split())[:300]}")
    return "\n".join(lines)


@pytest.mark.skipif(not COURSE_CASES, reason="no grading test files found under example_repo/")
@pytest.mark.parametrize("test_path,case_id", COURSE_CASES)
def test_course_case(live_enabled, cost_recorder, test_path: str, case_id: str) -> None:
    """Grade one instructor-authored case and hold it to its own claims."""
    options = RunOptions(
        case_ids=[case_id],
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.getenv("LLMGRADER_GRADETEST_MODEL") or None,
        timeout=DEFAULT_TIMEOUT,
        jobs=1,
        # The runner's own JSON report would be rewritten once per test; the
        # suite reports through pytest and the shared cost recorder instead.
        out=None,
    )

    report = run_test_files([test_path], options)
    assert report.cases, f"case `{case_id}` was not found in {test_path}"

    (case_run,) = report.cases
    for attempt in case_run.attempts:
        cost_recorder.record(
            attempt.model,
            f"gradetest:{case_id}",
            {
                "tokens_in": attempt.tokens_in,
                "tokens_out": attempt.tokens_out,
                "latency_ms": attempt.latency_ms,
            },
        )

    assert case_run.verdict not in FAILING_VERDICTS, _failure_report(case_run)
