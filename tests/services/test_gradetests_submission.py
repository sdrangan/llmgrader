"""``run --gradescope``: the submission zip, built without spending anything.

The zip these tests check is not a format of this repository's own choosing.
It is what ``downloadSubmission`` in ``llmgrader/static/js/dashboard.js``
produces, and the autograder verifies a signature over the exact
``results.json`` bytes -- so a difference of a single newline between the two
producers is a submission Gradescope rejects, on the instructor's machine
only, after they have already paid for the run that built it.

Two tests here earn their place ahead of the rest:

* the signature test, because text-mode writing on Windows would translate the
  LFs ``json.dumps`` emits into CRLFs *after* the signature was computed, and
  the zip would then verify for whoever built it on macOS and fail for
  everyone else;
* the two refusal tests, because both conditions are knowable from the test
  file and the unit, and discovering either one after the grading calls means
  discovering it after the bill.

The OpenAI client is the same fake ``test_gradetests_run`` uses.
"""

from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path

import pytest

from test_gradetests_run import (
    EXAMPLE_UNIT,
    FakeOpenAIFactory,
    _install_fake,
    _partial_reply,
)

from llmgrader.services.gradetests import GradeTestError, RunOptions, run_test_files
from llmgrader.services.signing import generate_key_pair, verify_signature


# ---------------------------------------------------------------------------
# Fixtures: the two required questions of the demo unit
# ---------------------------------------------------------------------------


#: `Integration by parts` -- partial credit, a single part labelled `all`.
BY_PARTS_CASE = """
  <case id="by_parts_partial" qtag="Integration by parts">
    <description>Correct antiderivative, limits never evaluated.</description>
    <solution><![CDATA[Let u = x, dv = e^{2x} dx. The antiderivative is (1/4)(2x-1)e^{2x} + C.]]></solution>
    <expected_points>
      <part label="all" min="4" max="8"/>
    </expected_points>
  </case>
"""

#: A second case for the same qtag, so a run has something to be ambiguous about.
BY_PARTS_SECOND_CASE = """
  <case id="by_parts_full" qtag="Integration by parts">
    <description>Full-credit control.</description>
    <solution><![CDATA[Integrating by parts and applying the limits gives the value.]]></solution>
    <expected_points>
      <part label="all" min="8" max="10"/>
    </expected_points>
  </case>
"""

#: `Exponential graphing` -- partial credit over two parts, a and b.
GRAPHING_CASE = """
  <case id="graphing_partial" qtag="Exponential graphing">
    <description>Critical point found, sketch missing its labels.</description>
    <solution><![CDATA[The critical point is at x=1 where f(1)=1/e.]]></solution>
    <expected_points>
      <part label="a" min="4" max="5"/>
    </expected_points>
  </case>
"""

#: `Exponential derivative` is <required>false</required> in the demo unit.
OPTIONAL_CASE = """
  <case id="log_method_correct" qtag="Exponential derivative">
    <description>Full-credit control on the optional question.</description>
    <solution><![CDATA[Take logs: ln y = x ln a, so y' = a^x ln(a).]]></solution>
    <expected_result>pass</expected_result>
  </case>
"""


BY_PARTS_REPLY = _partial_reply(
    6.0,
    {
        "correct_u_dv": 3.0,
        "correct_du_v": 3.0,
        "correct_integration_by_parts": 0.0,
        "apply_limits": 0.0,
    },
)

GRAPHING_REPLY = {
    "point_parts": [5.0, 2.0],
    "full_explanation": "Part (a) is complete; the sketch in (b) is unlabelled.",
    "feedback": "Label the critical point and the limit on your graph.",
    "rubric_eval": {
        "identify_critical_point": {"evidence": "Solves f'(x)=0 at x=1.", "point_awarded": 3.0},
        "evaluate_critical_value": {"evidence": "States f(1)=1/e.", "point_awarded": 2.0},
        "limit_at_infinity": {"evidence": "Not addressed.", "point_awarded": 0.0},
        "value_at_zero": {"evidence": "Not addressed.", "point_awarded": 0.0},
        "curve_shape": {"evidence": "Shape is right.", "point_awarded": 2.0},
        "label_critical_point_on_graph": {"evidence": "Unlabelled.", "point_awarded": 0.0},
    },
}

OPTIONAL_REPLY = {
    "result": "pass",
    "full_explanation": "The logarithm method is applied correctly.",
    "feedback": "Correct: taking logs of both sides is a valid route.",
    "rubric_eval": {
        "taking_logarithm": {"evidence": "Takes ln of both sides.", "result": "pass"},
        "exponential_form": {"evidence": "Not the method used.", "result": "n/a"},
        "polynomial_confusion": {"evidence": "No power rule applied.", "result": "n/a"},
        "final_answer": {"evidence": "Gives y' = a^x ln a.", "result": "pass"},
    },
}

#: Markers keyed to the solution text of each case above.
ALL_REPLIES = {
    "antiderivative": BY_PARTS_REPLY,
    "Integrating by parts and applying": _partial_reply(
        10.0,
        {
            "correct_u_dv": 3.0,
            "correct_du_v": 3.0,
            "correct_integration_by_parts": 2.0,
            "apply_limits": 2.0,
        },
    ),
    "critical point is at x=1": GRAPHING_REPLY,
    "Take logs": OPTIONAL_REPLY,
}


def _case_file(tmp_path: Path, *cases: str, unit: Path | None = None) -> Path:
    path = tmp_path / "cases.xml"
    unit_path = (unit or EXAMPLE_UNIT).as_posix()
    path.write_text(
        f'<unit_test unit="{unit_path}">\n' + "\n".join(cases) + "\n</unit_test>\n",
        encoding="utf-8",
    )
    return path


def _options(tmp_path: Path, **overrides) -> RunOptions:
    base = dict(
        api_key="test-key",
        timeout=5.0,
        jobs=1,
        repeat=1,
        out=None,
        gradescope=str(tmp_path / "submission"),
    )
    base.update(overrides)
    return RunOptions(**base)


def _run(tmp_path, monkeypatch, *cases, replies=None, **overrides):
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory(replies if replies is not None else ALL_REPLIES)
    _install_fake(monkeypatch, factory)
    report = run_test_files([str(_case_file(tmp_path, *cases))], _options(tmp_path, **overrides))
    return report, factory


# ---------------------------------------------------------------------------
# The file the portal would have produced
# ---------------------------------------------------------------------------


def test_results_json_matches_the_portal_shape(tmp_path: Path, monkeypatch) -> None:
    """One entry per required question, scored from the graded case.

    ``buildResultsJson`` emits ``{score, output, tests[]}`` with one test per
    required qtag, and ``buildQuestionResult`` renders a whole-question grade
    as two ``[all]`` lines.  Every attempt here is graded with
    ``part_label="all"``, so that is the branch being mirrored.
    """
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE, GRAPHING_CASE)

    assert report.submission_error is None
    payload = json.loads((Path(report.submission.directory) / "results.json").read_text("utf-8"))

    assert payload["output"] == "See detailed feedback for individual questions"
    assert payload["score"] == 13  # 6 from by-parts, 7 from graphing
    assert [test["name"] for test in payload["tests"]] == [
        "Integration by parts",
        "Exponential graphing",
    ]

    by_parts = payload["tests"][0]
    assert by_parts["score"] == 6
    assert by_parts["max_score"] == 10
    assert by_parts["output"].startswith("[all] Feedback: See the rubric table")
    assert "\n[all] Explanation: Scored from the rubric items." in by_parts["output"]


def test_whole_numbers_are_written_as_integers(tmp_path: Path, monkeypatch) -> None:
    """``JSON.stringify`` writes 10, not 10.0, and so does this."""
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE)

    raw = (Path(report.submission.directory) / "results.json").read_text("utf-8")

    # Only the numeric fields: the feedback the grader wrote has its own rubric
    # table in it, and "3.0 / 3.0" there is the grader's rendering, not ours.
    assert '"score": 6,' in raw
    assert '"max_score": 10,' in raw
    assert '"max_score": 10.0' not in raw


def test_unanswered_required_question_scores_zero(tmp_path: Path, monkeypatch) -> None:
    """A required question no case answers is present, at zero, with no output.

    This is what the portal does for a question the student never submitted,
    and it is the reason a submission can be built from a single case.
    """
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE)

    payload = json.loads((Path(report.submission.directory) / "results.json").read_text("utf-8"))
    graphing = next(test for test in payload["tests"] if test["name"] == "Exponential graphing")

    assert graphing["score"] == 0
    assert graphing["max_score"] == 10  # a=5 plus b=5, from the unit
    assert graphing["output"] == ""


def test_results_txt_covers_every_required_question(tmp_path: Path, monkeypatch) -> None:
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE, GRAPHING_CASE)

    text = (Path(report.submission.directory) / "results.txt").read_bytes().decode("utf-8")

    assert text.startswith("Unit: ")
    assert "Question Integration by parts (selected part: all)" in text
    assert "Score: 6 / 10" in text
    assert "Question Exponential graphing (selected part: all)" in text
    assert text.count("-" * 40) == 2


def test_the_zip_holds_the_folder(tmp_path: Path, monkeypatch) -> None:
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE)
    submission = report.submission

    assert Path(submission.zip_path) == Path(str(tmp_path / "submission") + ".zip")
    with zipfile.ZipFile(submission.zip_path) as archive:
        assert sorted(archive.namelist()) == ["results.json", "results.txt"]
        # Byte-identical to the folder, so uploading either is the same test.
        assert archive.read("results.json") == (
            Path(submission.directory) / "results.json"
        ).read_bytes()


def test_default_directory_is_plain_submission(tmp_path: Path, monkeypatch) -> None:
    """``--gradescope`` with no path writes ``./submission`` and ``./submission.zip``.

    Deliberately not named after the unit: the folder is written into the
    unit's own directory, and a title like ``Unit 1: Calculus Review`` would
    put a long path with a colon in it -- illegal on Windows -- where a short
    one carries the same information.
    """
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE, gradescope="")

    assert Path(report.submission.directory) == tmp_path / "submission"
    assert Path(report.submission.zip_path) == tmp_path / "submission.zip"
    assert (tmp_path / "submission").is_dir()

    # The unit is still identified, inside the zip rather than by the path.
    text = (tmp_path / "submission" / "results.txt").read_bytes().decode("utf-8")
    assert text.startswith("Unit: Unit 1: Calculus Review")


# ---------------------------------------------------------------------------
# Choosing which case answers a question
# ---------------------------------------------------------------------------


def test_two_cases_for_one_qtag_are_refused_before_any_call(tmp_path: Path, monkeypatch) -> None:
    """The refusal has to come out of the plan, not out of the results.

    Grading first and then discovering that the submission cannot be built
    charges for a run that produced nothing the instructor asked for, so this
    asserts on the fake having seen no prompt at all.
    """
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory(ALL_REPLIES)
    _install_fake(monkeypatch, factory)

    path = _case_file(tmp_path, BY_PARTS_CASE, BY_PARTS_SECOND_CASE)
    with pytest.raises(GradeTestError) as excinfo:
        run_test_files([str(path)], _options(tmp_path))

    message = str(excinfo.value)
    assert "Integration by parts" in message
    assert "by_parts_partial" in message and "by_parts_full" in message
    assert "--first-case" in message
    assert factory.prompts == []


def test_first_case_resolves_the_ambiguity_by_document_order(tmp_path: Path, monkeypatch) -> None:
    report, _ = _run(
        tmp_path, monkeypatch, BY_PARTS_CASE, BY_PARTS_SECOND_CASE, first_case=True
    )

    answered = {
        question.qtag: question.case_id
        for question in report.submission.questions
        if question.answered
    }
    assert answered == {"Integration by parts": "by_parts_partial"}
    assert report.submission.score == 6


def test_a_single_case_for_a_qtag_needs_no_flag(tmp_path: Path, monkeypatch) -> None:
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE, GRAPHING_CASE)

    assert report.submission_error is None
    assert len(report.submission.answered) == 2


def test_a_case_for_an_optional_question_is_dropped_and_named(tmp_path: Path, monkeypatch) -> None:
    """The portal submits required questions only, so an optional case has
    nowhere to go -- but dropping it silently would leave the instructor
    hunting for a score that was never going to be in the file."""
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE, OPTIONAL_CASE)

    qtags = [question.qtag for question in report.submission.questions]
    assert "Exponential derivative" not in qtags
    assert report.submission_plan.optional_case_ids == ["log_method_correct"]


def test_only_the_first_attempt_answers_a_repeated_case(tmp_path: Path, monkeypatch) -> None:
    """``--repeat`` reads one submission N times; a student submits one of them."""
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE, repeat=3)

    assert len(report.cases[0].attempts) == 3
    assert report.submission.score == 6


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def _signed_unit(tmp_path: Path) -> Path:
    """The demo unit with signing turned on, copied so the original is left alone."""
    source = EXAMPLE_UNIT.read_text(encoding="utf-8")
    marker = ">"
    head, rest = source.split(marker, 1)
    signed = tmp_path / "signed_calculus.xml"
    signed.write_text(head + marker + "\n    <digitalsign>true</digitalsign>\n" + rest, "utf-8")
    return signed


def test_signature_verifies_over_the_exact_results_json_bytes(tmp_path: Path, monkeypatch) -> None:
    """The test this module exists for.

    ``json.dumps`` emits LF.  Writing the file in text mode on Windows would
    translate those to CRLF after the signature was taken over the untranslated
    string, producing a zip that verifies for its author and is rejected for
    everyone else -- with a message telling the student to re-download from the
    portal, which points nowhere near the cause.
    """
    private_key, public_key = generate_key_pair()
    monkeypatch.setenv("LLMGRADER_PRIVATE_KEY", private_key)

    unit = _signed_unit(tmp_path)
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory(ALL_REPLIES))

    path = _case_file(tmp_path, BY_PARTS_CASE, unit=unit)
    report = run_test_files([str(path)], _options(tmp_path))

    assert report.submission_error is None
    assert report.submission.signed

    directory = Path(report.submission.directory)
    results_bytes = (directory / "results.json").read_bytes()
    signature = (directory / "signature.txt").read_text(encoding="utf-8").strip()

    assert b"\r\n" not in results_bytes
    assert verify_signature(results_bytes, signature, public_key)

    # And the same bytes come back out of the zip, which is what gets uploaded.
    with zipfile.ZipFile(report.submission.zip_path) as archive:
        assert archive.read("results.json") == results_bytes
        assert verify_signature(results_bytes, archive.read("signature.txt").decode().strip(), public_key)


def test_a_signed_unit_without_a_key_is_refused_before_any_call(tmp_path: Path, monkeypatch) -> None:
    """An unsigned zip is rejected by the autograder with a message about
    re-downloading from the portal, which would not point back here."""
    monkeypatch.delenv("LLMGRADER_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory(ALL_REPLIES)
    _install_fake(monkeypatch, factory)

    path = _case_file(tmp_path, BY_PARTS_CASE, unit=_signed_unit(tmp_path))
    with pytest.raises(GradeTestError) as excinfo:
        run_test_files([str(path)], _options(tmp_path))

    assert "LLMGRADER_PRIVATE_KEY" in str(excinfo.value)
    assert factory.prompts == []


# ---------------------------------------------------------------------------
# The target directory
# ---------------------------------------------------------------------------


def test_a_directory_that_is_not_a_submission_is_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    """``--gradescope .`` must not rmtree the course repository.

    The folder is rebuilt from scratch on every run, the way
    ``build_autograder`` rebuilds ``autograder/``, but the path comes from the
    command line here.  A directory holding a ``results.json`` is one of ours;
    anything else with something in it is someone's work.
    """
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory(ALL_REPLIES)
    _install_fake(monkeypatch, factory)

    target = tmp_path / "submission"
    target.mkdir()
    (target / "lecture_notes.tex").write_text("weeks of work", encoding="utf-8")

    path = _case_file(tmp_path, BY_PARTS_CASE)
    with pytest.raises(GradeTestError) as excinfo:
        run_test_files([str(path)], _options(tmp_path))

    assert "refusing to overwrite" in str(excinfo.value)
    assert (target / "lecture_notes.tex").exists()
    assert factory.prompts == []


def test_rerunning_replaces_an_earlier_submission(tmp_path: Path, monkeypatch) -> None:
    """A folder of ours is rebuilt, and stale files in it do not survive."""
    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE)
    stale = Path(report.submission.directory) / "signature.txt"
    stale.write_text("a signature from a previous, signed run", encoding="utf-8")

    report, _ = _run(tmp_path, monkeypatch, BY_PARTS_CASE)

    assert report.submission_error is None
    assert not stale.exists()


# ---------------------------------------------------------------------------
# Failures that only surface after the calls
# ---------------------------------------------------------------------------


def test_a_case_that_did_not_grade_fails_the_submission_not_the_report(
    tmp_path: Path, monkeypatch
) -> None:
    """The reports are still worth what they cost, so the failure is carried
    back on the report rather than raised over it."""
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({}, default={"not": "a grade"}))

    path = _case_file(tmp_path, BY_PARTS_CASE)
    report = run_test_files(
        [str(path)], _options(tmp_path, out=str(tmp_path / "report.json"))
    )

    assert report.submission is None
    assert "by_parts_partial" in report.submission_error
    assert (tmp_path / "report.json").exists()


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


#: A 1x1 PNG, so a case can attach something real.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_a_case_image_lands_where_the_portal_puts_it(tmp_path: Path, monkeypatch) -> None:
    """``images/<qtag>/<index>.<ext>``, the same layout the portal writes."""
    (tmp_path / "work.png").write_bytes(_PNG)
    case = BY_PARTS_CASE.replace(
        "</case>", "    <images><image>work.png</image></images>\n  </case>"
    )

    report, _ = _run(tmp_path, monkeypatch, case)

    with zipfile.ZipFile(report.submission.zip_path) as archive:
        names = archive.namelist()
        assert "images/Integration by parts/0.png" in names
        assert archive.read("images/Integration by parts/0.png") == _PNG
