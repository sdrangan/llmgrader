"""``llmgrader_answer`` against the real API -- the paid half of its pair.

``tests/services/test_answers.py`` checks everything this suite checks except
the one thing a fake caller cannot: that a real model, given the prompt this
tool builds, returns prose that survives the emitter and comes back out of
``load_test_file`` intact.  A renamed model id, a provider that starts
refusing a bare prompt with no ``text.format``, or a reply shape the caller
mis-reads would all pass the free suite and fail here.

Gated exactly as the rest of ``tests/live`` is, by ``live_enabled``: both
``LLMGRADER_RUN_LIVE_TESTS=1`` and ``OPENAI_API_KEY``, plus the ``-m live``
selection ``pyproject.toml`` deselects by default.

One question, one call, on the cheapest tier -- this is a smoke test of the
path, not a measurement of how well models do on the course.  That is what
running the tool for real is for.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llmgrader.services.answers import (
    EXPECT_FULL,
    AnswerOptions,
    run_answers,
)
from llmgrader.services.gradetests import (
    LEVEL_ERROR,
    check_file,
    load_test_file,
    load_unit,
    validate_test_file,
)


pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_UNIT = REPO_ROOT / "example_repo" / "unit1" / "calculus.xml"

#: The cheapest question in the example course: binary, one part, no images.
SMOKE_QTAG = "Exponential derivative"


def test_answer_cli_writes_a_file_llmgrader_test_accepts(live_enabled, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    report = run_answers(
        [str(EXAMPLE_UNIT)],
        AnswerOptions(
            api_key=os.environ["OPENAI_API_KEY"],
            model="simple",
            qtags=[SMOKE_QTAG],
            jobs=1,
            expect=EXPECT_FULL,
        ),
    )

    assert not report.errors, [result.error for result in report.errors]
    assert len(report.written) == 1

    answer = report.results[0]
    assert answer.text.strip(), "the model returned nothing at all"
    assert answer.tokens_in > 0 and answer.tokens_out > 0

    path = Path(report.written[0])
    assert validate_test_file(str(path)) == []

    test_file = load_test_file(str(path))
    assert [case.qtag for case in test_file.cases] == [SMOKE_QTAG]
    # The emitter must hand back exactly what the model said, CDATA and all.
    assert test_file.cases[0].solution.strip() == answer.text.strip()

    findings = check_file(test_file, load_unit(str(EXAMPLE_UNIT)), coverage=False)
    assert [f.message for f in findings if f.level == LEVEL_ERROR] == []
