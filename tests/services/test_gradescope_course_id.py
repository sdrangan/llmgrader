"""``course_id`` in the Gradescope submission, and the autograder's grace period.

``plans/multicourse.md`` decision 8.  A student with two courses on one portal
downloads two files both called ``submission.zip``; without a course in the
file, uploading the wrong one earns a plausible-looking score against questions
they never answered.

The delicate part is that the autograder verifies an Ed25519 signature over the
exact ``results.json`` bytes, so the two writers of that file -- ``gradetests``
here and ``buildResultsJson`` in ``static/js/dashboard.js`` -- have to agree
character for character. A key in a different position is a submission that
will not verify.
"""

import json
import re
from pathlib import Path

import pytest

from llmgrader.services.gradetests import (
    SubmissionQuestion,
    _synthesized_course_block,
    submission_results_json,
)

DASHBOARD_JS = Path(__file__).resolve().parents[2] / "llmgrader" / "static" / "js" / "dashboard.js"
AUTOGRADE_PY = Path(__file__).resolve().parents[2] / "llmgrader" / "gradescope" / "autograde.py"

QUESTIONS = [
    SubmissionQuestion(
        qtag="q1", case_id="c1", score=10, max_score=10,
        feedback="Good", explanation="Because",
    )
]


# ---------------------------------------------------------------------------
# What the runner writes
# ---------------------------------------------------------------------------


def test_results_json_carries_the_course() -> None:
    payload = json.loads(submission_results_json(QUESTIONS, "intro_prob"))
    assert payload["course_id"] == "intro_prob"


def test_a_package_with_no_course_writes_an_empty_string() -> None:
    """Empty, not null: the portal writes "" when it has no course, and these
    bytes are signed, so the two writers must not disagree on the spelling."""
    raw = submission_results_json(QUESTIONS, "")
    assert '"course_id": ""' in raw
    assert "null" not in raw


def test_the_key_sits_between_output_and_tests() -> None:
    """Key order is part of the signed bytes, not a matter of taste."""
    raw = submission_results_json(QUESTIONS, "intro_prob")
    assert list(json.loads(raw)) == ["score", "output", "course_id", "tests"]
    assert raw.index('"output"') < raw.index('"course_id"') < raw.index('"tests"')


def test_the_front_end_writes_the_same_key_in_the_same_place() -> None:
    """The two writers must stay in lockstep; this fails if one moves.

    Read out of dashboard.js rather than asserted in prose, because the file
    they have to match is the one that ships.
    """
    js = DASHBOARD_JS.read_text(encoding="utf-8")
    match = re.search(r"return \{\s*(score:.*?)\n    \};", js, re.DOTALL)
    assert match, "could not find the buildResultsJson return block"

    keys = re.findall(r"^\s*(\w+):", match.group(1), re.MULTILINE)
    assert keys == ["score", "output", "course_id", "tests"]


# ---------------------------------------------------------------------------
# Where the id comes from when there is no registry
# ---------------------------------------------------------------------------


def test_a_synthesized_package_keeps_the_real_courses_identity(tmp_path: Path) -> None:
    """The runner builds a package around a loose unit file; that stand-in has
    to carry the real course's identity, or the zip names a course nobody runs."""
    config = tmp_path / "llmgrader_config.xml"
    config.write_text(
        "<llmgrader><course><course_id>intro_prob</course_id>"
        "<name>Intro Probability</name><semester>Spring 2026</semester></course>"
        "<units></units></llmgrader>",
        encoding="utf-8",
    )

    block = _synthesized_course_block(str(config))

    assert "<course_id>intro_prob</course_id>" in block
    assert "<name>Intro Probability</name>" in block


def test_a_loose_unit_file_with_no_config_names_no_course() -> None:
    """Nothing to read means nothing to claim, and the placeholder stays."""
    block = _synthesized_course_block(None)

    assert "course_id" not in block
    assert "Grading tests" in block


# ---------------------------------------------------------------------------
# The autograder: warn, then fail
# ---------------------------------------------------------------------------


@pytest.fixture()
def autograder(tmp_path: Path, monkeypatch):
    """The real autograde module, pointed at a temp submission tree."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("autograde_under_test", AUTOGRADE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    submission = tmp_path / "submission"
    submission.mkdir()
    module.SUBMISSION_DIR = submission
    module.RESULTS_PATH = tmp_path / "results" / "results.json"
    module.SIGNING_KEY_PATH = tmp_path / "signing_public_key.txt"
    module.EXPECTED_COURSE_PATH = tmp_path / "expected_course.txt"
    return module


def write_submission(module, payload: dict) -> None:
    (module.SUBMISSION_DIR / "results.json").write_bytes(
        json.dumps(payload, indent=2).encode("utf-8")
    )


def graded(module) -> dict:
    return json.loads(module.RESULTS_PATH.read_text(encoding="utf-8"))


def test_a_matching_course_is_graded(autograder) -> None:
    autograder.EXPECTED_COURSE_PATH.write_text("intro_prob", encoding="utf-8")
    write_submission(autograder, {"score": 10, "course_id": "intro_prob", "tests": []})

    autograder.main()

    assert graded(autograder)["score"] == 10


def test_a_submission_from_another_course_is_refused(autograder) -> None:
    autograder.EXPECTED_COURSE_PATH.write_text("intro_prob", encoding="utf-8")
    write_submission(autograder, {"score": 10, "course_id": "signals", "tests": []})

    autograder.main()

    result = graded(autograder)
    assert result["score"] == 0
    # Both courses named, and told what to do about it.
    assert "signals" in result["output"]
    assert "intro_prob" in result["output"]
    assert "wrong submission.zip" in result["output"]


def test_a_submission_with_no_course_is_accepted_with_a_warning(autograder, capsys) -> None:
    """The one-release grace period: submissions downloaded before the field
    existed are still in flight, and failing them would punish students for a
    server-side change."""
    autograder.EXPECTED_COURSE_PATH.write_text("intro_prob", encoding="utf-8")
    write_submission(autograder, {"score": 10, "tests": []})

    autograder.main()

    assert graded(autograder)["score"] == 10
    assert "does not name a course" in capsys.readouterr().out


def test_an_empty_course_id_is_treated_as_absent(autograder) -> None:
    """A portal with no course writes "", which is not a claim to be checked."""
    autograder.EXPECTED_COURSE_PATH.write_text("intro_prob", encoding="utf-8")
    write_submission(autograder, {"score": 10, "course_id": "", "tests": []})

    autograder.main()

    assert graded(autograder)["score"] == 10


def test_an_autograder_with_no_expected_course_checks_nothing(autograder) -> None:
    """Existing autograders keep working untouched: no file, no check."""
    write_submission(autograder, {"score": 10, "course_id": "anything", "tests": []})

    autograder.main()

    assert graded(autograder)["score"] == 10


def test_unparseable_results_json_does_not_become_a_zero_here(autograder) -> None:
    """The course check must not be a second way for a valid submission to fail.

    Signature verification has already run by this point; a parse problem in
    the course check means "no course named", not "reject".
    """
    autograder.EXPECTED_COURSE_PATH.write_text("intro_prob", encoding="utf-8")
    (autograder.SUBMISSION_DIR / "results.json").write_bytes(b"{not json at all")

    autograder.main()

    assert autograder.RESULTS_PATH.read_bytes() == b"{not json at all"
