"""The `run` half of grading tests, exercised without spending anything.

Every test here grades through the real :class:`~llmgrader.services.grader.Grader`
with the OpenAI client replaced by a fake that returns canned JSON.  That is
the only way to get deterministic ``rubric_eval`` payloads in both shapes,
which is exactly what the evaluation logic needs to be tested against --
including a negative rubric item scored the wrong way round, the case that
would otherwise cost the most to discover.

The first test is the one that matters most.  ``Grader.__init__`` rmtree's its
scratch directory and opens a SQLite database at ``get_storage_path()``,
writing a submission row for every grade.  A runner that inherits those
side effects fills the instructor's ``local_data/`` with fake submissions that
then show up in the dashboard and in any future replay run.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from llmgrader.services.gradetests import (
    VERDICT_ERROR,
    VERDICT_PASS,
    RunOptions,
    run_test_files,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_REPO = REPO_ROOT / "example_repo"
EXAMPLE_UNIT = EXAMPLE_REPO / "unit1" / "calculus.xml"
EXAMPLE_TESTS = EXAMPLE_REPO / "unit1" / "tests" / "calculus_tests.xml"


# ---------------------------------------------------------------------------
# A fake OpenAI client whose reply depends on the prompt it was handed
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, payload: str) -> None:
        self.output_text = payload
        self.usage = _FakeUsage(1234, 56)
        self.output = []


class FakeOpenAIFactory:
    """Builds a stand-in for ``openai.OpenAI`` that replies from a table.

    The reply is chosen by looking for a marker in the prompt, which is how a
    single fake covers several cases in one run: each test case's solution
    text is its own marker.
    """

    def __init__(self, replies: dict[str, dict], default: dict | None = None) -> None:
        self.replies = replies
        self.default = default
        self.prompts: list[str] = []

    def __call__(self, *args, **kwargs):
        factory = self

        class _FakeResponses:
            def create(self, **request):
                prompt = json.dumps(request.get("input", ""))
                factory.prompts.append(prompt)
                for marker, payload in factory.replies.items():
                    if marker in prompt:
                        return _FakeResponse(json.dumps(payload))
                if factory.default is None:
                    raise AssertionError(f"no canned reply matched the prompt: {prompt[:400]}")
                return _FakeResponse(json.dumps(factory.default))

        class _FakeClient:
            def __init__(self) -> None:
                self.responses = _FakeResponses()

        return _FakeClient()


#: Canned replies keyed by a phrase that appears only in that case's solution.
BINARY_PASS = {
    "result": "pass",
    "full_explanation": "The logarithm method is applied correctly.",
    "feedback": "Correct: taking logs of both sides is a valid route.",
    "rubric_eval": {
        "taking_logarithm": {"evidence": "Student takes ln of both sides.", "result": "pass"},
        "exponential_form": {"evidence": "Not the method used.", "result": "n/a"},
        "polynomial_confusion": {"evidence": "No power rule applied.", "result": "n/a"},
        "final_answer": {"evidence": "Gives y' = a^x ln a.", "result": "pass"},
    },
}

BINARY_FAIL = {
    "result": "fail",
    "full_explanation": "The student applied the power rule to an exponential.",
    "feedback": "a^x is not a power of x; the power rule does not apply.",
    "rubric_eval": {
        "taking_logarithm": {"evidence": "No logarithms taken.", "result": "n/a"},
        "exponential_form": {"evidence": "Not rewritten as e^{x ln a}.", "result": "n/a"},
        "polynomial_confusion": {"evidence": "Writes y' = x a^{x-1}.", "result": "fail"},
        "final_answer": {"evidence": "Answer is wrong.", "result": "fail"},
    },
}


def _partial_reply(points: float, awards: dict[str, float]) -> dict:
    return {
        "point_parts": [points],
        "full_explanation": "Scored from the rubric items.",
        "feedback": "See the rubric table for the breakdown.",
        "rubric_eval": {
            item_id: {"evidence": f"Evidence for {item_id}.", "point_awarded": award}
            for item_id, award in awards.items()
        },
    }


def _install_fake(monkeypatch, factory: FakeOpenAIFactory) -> None:
    monkeypatch.setattr("llmgrader.services.grader.OpenAI", factory)


def _options(**overrides) -> RunOptions:
    base = dict(api_key="test-key", timeout=5.0, jobs=1, repeat=1)
    base.update(overrides)
    return RunOptions(**base)


def _single_case_file(tmp_path: Path, case_xml: str, name: str = "cases.xml") -> Path:
    path = tmp_path / name
    path.write_text(
        f'<unit_test unit="{EXAMPLE_UNIT.as_posix()}">\n{case_xml}\n</unit_test>\n',
        encoding="utf-8",
    )
    return path


LOG_METHOD_CASE = """
  <case id="log_method_correct" qtag="Exponential derivative">
    <description>Full-credit control by the logarithm method.</description>
    <solution><![CDATA[Take logs: ln y = x ln a, so y' = a^x ln(a).]]></solution>
    <expected_result>pass</expected_result>
    <expected_rubrics>
      <item id="taking_logarithm" expect="pass"/>
      <item id="final_answer" expect="pass"/>
      <item id="polynomial_confusion" expect="n/a"/>
    </expected_rubrics>
  </case>
"""


# ---------------------------------------------------------------------------
# Storage isolation -- caveat 2, the highest-consequence bug in the runner
# ---------------------------------------------------------------------------


def test_run_never_writes_to_the_instructors_local_data(tmp_path: Path, monkeypatch) -> None:
    """A grading test run must leave no trace in the real storage directory.

    With ``LLMGRADER_STORAGE_PATH`` unset, ``Grader.get_storage_path`` falls
    back to ``<cwd>/local_data`` and creates it.  Running from a temp cwd with
    the variable cleared means any leak lands somewhere this test can see.
    """
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)

    factory = FakeOpenAIFactory({"Take logs": BINARY_PASS})
    _install_fake(monkeypatch, factory)

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files([str(path)], _options())

    assert report.calls == 1

    # The JSON report is a deliberate output and lands under local_data/.
    # Nothing else may: no database, no scratch tree, no staged package.
    written = sorted(path.relative_to(work).as_posix() for path in work.rglob("*") if path.is_file())
    assert written == ["local_data/gradetests/report.json"], written
    assert not (work / "local_data" / "db").exists()
    assert not (work / "local_data" / "soln_pkg").exists()


def test_run_restores_the_storage_environment_variable(tmp_path: Path, monkeypatch) -> None:
    """The variable is process-global; a run must put it back as it found it."""
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "real_storage"))
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory({"Take logs": BINARY_PASS})
    _install_fake(monkeypatch, factory)

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    run_test_files([str(path)], _options())

    assert os.environ["LLMGRADER_STORAGE_PATH"] == str(tmp_path / "real_storage")
    assert not (tmp_path / "real_storage" / "db").exists()


def test_run_removes_its_temporary_storage_unless_keep_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory({"Take logs": BINARY_PASS})
    _install_fake(monkeypatch, factory)
    path = _single_case_file(tmp_path, LOG_METHOD_CASE)

    report = run_test_files([str(path)], _options())
    assert not Path(report.storage_path).exists()

    report = run_test_files([str(path)], _options(keep_db=True))
    kept = Path(report.storage_path)
    assert kept.exists()
    rows = sqlite3.connect(str(kept / "db" / "llmgrader.db")).execute(
        "SELECT client_id FROM submissions"
    ).fetchall()
    assert rows == [("gradetest:log_method_correct#1",)]


# ---------------------------------------------------------------------------
# Token capture -- design decision 6
# ---------------------------------------------------------------------------


def test_usage_is_looked_up_by_session_id_not_by_newest_row(tmp_path: Path, monkeypatch) -> None:
    """Under --jobs the newest row is not necessarily the call that finished."""
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory(
        {"Take logs": BINARY_PASS, "power rule": BINARY_FAIL}
    )
    _install_fake(monkeypatch, factory)

    path = _single_case_file(
        tmp_path,
        LOG_METHOD_CASE
        + """
  <case id="power_rule_confusion" qtag="Exponential derivative">
    <description>Differentiates a^x as if it were x^a.</description>
    <solution><![CDATA[Using the power rule, y' = x a^{x-1}.]]></solution>
    <expected_result>fail</expected_result>
    <expected_rubrics>
      <item id="polynomial_confusion" expect="fail"/>
    </expected_rubrics>
  </case>
""",
    )
    report = run_test_files([str(path)], _options(jobs=4))

    attempts = {attempt.case_id: attempt for attempt in report.attempts}
    assert set(attempts) == {"log_method_correct", "power_rule_confusion"}
    for case_id, attempt in attempts.items():
        assert attempt.session_id == f"gradetest:{case_id}#1"
        assert attempt.tokens_in == 1234
        assert attempt.tokens_out == 56
        assert attempt.latency_ms is not None


# ---------------------------------------------------------------------------
# Evaluation -- binary mode
# ---------------------------------------------------------------------------


def test_binary_case_passes_when_result_and_rubrics_match(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files([str(path)], _options())

    assert report.verdicts == {"PASS": 1}
    assert report.failed == 0
    attempt = report.attempts[0]
    assert attempt.failures == []
    assert attempt.result == "pass"
    assert attempt.feedback.startswith("Correct:")


def test_binary_case_fails_and_names_the_misfiring_rubric_item(tmp_path: Path, monkeypatch) -> None:
    """The failure message names the item, not just "expected pass, got fail"."""
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    # The grader passes the answer but does not credit `taking_logarithm`.
    reply = json.loads(json.dumps(BINARY_PASS))
    reply["rubric_eval"]["taking_logarithm"]["result"] = "n/a"
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": reply}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files([str(path)], _options())

    assert report.failed == 1
    (failure,) = report.attempts[0].failures
    assert "taking_logarithm" in failure
    assert "pass" in failure and "n/a" in failure


def test_rubric_item_absent_from_the_response_is_a_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    reply = json.loads(json.dumps(BINARY_PASS))
    del reply["rubric_eval"]["taking_logarithm"]
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": reply}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files([str(path)], _options())

    (failure,) = report.attempts[0].failures
    assert "taking_logarithm" in failure
    assert "not evaluated" in failure


# ---------------------------------------------------------------------------
# Evaluation -- partial-credit mode
# ---------------------------------------------------------------------------


PARTIAL_CASE = """
  <case id="missing_limits" qtag="Integration by parts">
    <description>Correct antiderivative, limits never evaluated.</description>
    <solution><![CDATA[Let u = x, dv = e^{2x} dx. The antiderivative is (1/4)(2x-1)e^{2x} + C.]]></solution>
    <expected_points>
      <part label="all" min="4" max="8"/>
    </expected_points>
    <expected_rubrics>
      <item id="correct_u_dv" min="3" max="3"/>
      <item id="apply_limits" min="0" max="0"/>
    </expected_rubrics>
  </case>
"""


def test_partial_case_passes_on_bands(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(
        monkeypatch,
        FakeOpenAIFactory(
            {
                "antiderivative": _partial_reply(
                    6.0,
                    {
                        "correct_u_dv": 3.0,
                        "correct_du_v": 3.0,
                        "correct_integration_by_parts": 0.0,
                        "apply_limits": 0.0,
                    },
                )
            }
        ),
    )

    path = _single_case_file(tmp_path, PARTIAL_CASE)
    report = run_test_files([str(path)], _options())

    assert report.failed == 0
    attempt = report.attempts[0]
    assert attempt.points == 6.0
    assert attempt.max_points == 10.0
    assert attempt.margin == 2.0  # nearest edge of [4, 8]


def test_partial_case_fails_when_the_score_leaves_the_band(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(
        monkeypatch,
        FakeOpenAIFactory(
            {
                "antiderivative": _partial_reply(
                    9.0,
                    {
                        "correct_u_dv": 3.0,
                        "correct_du_v": 3.0,
                        "correct_integration_by_parts": 2.0,
                        "apply_limits": 1.0,
                    },
                )
            }
        ),
    )

    path = _single_case_file(tmp_path, PARTIAL_CASE)
    report = run_test_files([str(path)], _options())

    assert report.failed == 1
    failures = report.attempts[0].failures
    assert any("over by 1" in failure for failure in failures)
    assert any("apply_limits" in failure and "0" in failure for failure in failures)


def test_negative_rubric_item_scored_the_wrong_way_round_is_caught(tmp_path: Path, monkeypatch) -> None:
    """The expensive-to-discover case: a penalty the grader never applied.

    A ``point_adjustment="-2"`` item comes back as ``-2.0`` when the model
    finds the mistake and ``0.0`` when it does not.  A case asserting
    ``min="-2" max="-2"`` must fail on ``0.0`` -- and must not be fooled by the
    sign into thinking 0 is "greater" and therefore fine.
    """
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    unit = tmp_path / "neg_unit.xml"
    unit.write_text(
        """\
<unit id="neg" title="Negative item unit" version="1.0">
  <question qtag="Sign error question" preferred_model="simple">
    <question_text><![CDATA[Integrate.]]></question_text>
    <solution><![CDATA[The answer is 4.]]></solution>
    <partial_credit>true</partial_credit>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>10</points>
      </part>
    </parts>
    <rubrics>
      <item id="correct_setup" point_adjustment="+4">
        <display_text>Correct setup</display_text>
        <condition>Student sets the integral up correctly.</condition>
      </item>
      <item id="sign_error_penalty" point_adjustment="-2">
        <display_text>Sign error</display_text>
        <condition>Student flips the sign of the antiderivative.</condition>
      </item>
    </rubrics>
    <rubric_total>flexible</rubric_total>
  </question>
</unit>
""",
        encoding="utf-8",
    )

    path = tmp_path / "neg_cases.xml"
    path.write_text(
        f"""\
<unit_test unit="{unit.as_posix()}">
  <case id="penalty_must_fire" qtag="Sign error question">
    <description>Sign flipped, so the penalty must apply.</description>
    <solution><![CDATA[The antiderivative is negated: the answer is -4.]]></solution>
    <expected_rubrics>
      <item id="sign_error_penalty" min="-2" max="-2"/>
    </expected_rubrics>
  </case>
</unit_test>
""",
        encoding="utf-8",
    )

    _install_fake(
        monkeypatch,
        FakeOpenAIFactory(
            {"negated": _partial_reply(8.0, {"correct_setup": 4.0, "sign_error_penalty": 0.0})}
        ),
    )
    report = run_test_files([str(path)], _options())

    assert report.failed == 1
    (failure,) = report.attempts[0].failures
    assert "sign_error_penalty" in failure
    assert "-2" in failure
    assert "0" in failure
    assert "Evidence for sign_error_penalty" in report.attempts[0].rubric_eval["sign_error_penalty"]["evidence"]


def test_multi_part_bands_are_matched_to_the_right_part(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    reply = {
        "point_parts": [5.0, 1.0],
        "full_explanation": "Part (a) complete, part (b) barely attempted.",
        "feedback": "Sketch the curve for part (b).",
        "rubric_eval": {
            "identify_critical_point": {"evidence": "x = 1 found.", "point_awarded": 3.0},
            "evaluate_critical_value": {"evidence": "f(1) = 1/e.", "point_awarded": 2.0},
            "limit_at_infinity": {"evidence": "Stated.", "point_awarded": 1.0},
            "value_at_zero": {"evidence": "Not stated.", "point_awarded": 0.0},
            "curve_shape": {"evidence": "No sketch.", "point_awarded": 0.0},
            "label_critical_point_on_graph": {"evidence": "No sketch.", "point_awarded": 0.0},
        },
    }
    _install_fake(monkeypatch, FakeOpenAIFactory({"critical point": reply}))

    path = _single_case_file(
        tmp_path,
        """
  <case id="part_a_only" qtag="Exponential graphing">
    <description>Part (a) answered fully, part (b) not attempted.</description>
    <solution><![CDATA[(a) The critical point is (1, 1/e).]]></solution>
    <expected_points>
      <part label="a" min="4" max="5"/>
      <part label="b" min="4" max="5"/>
    </expected_points>
  </case>
""",
    )
    report = run_test_files([str(path)], _options())

    (failure,) = report.attempts[0].failures
    assert "part 'b'" in failure
    assert "under by 3" in failure


# ---------------------------------------------------------------------------
# Selection, dry runs and call budgets
# ---------------------------------------------------------------------------


def test_dry_run_makes_no_calls_and_reports_the_model_breakdown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory({})
    _install_fake(monkeypatch, factory)

    report = run_test_files([str(EXAMPLE_TESTS)], _options(dry_run=True, repeat=3))

    assert factory.prompts == []
    assert report.calls == 0
    assert report.planned_calls == 24
    assert sum(report.planned_by_model.values()) == 24


def test_max_calls_refuses_to_start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory({})
    _install_fake(monkeypatch, factory)

    from llmgrader.services.gradetests import GradeTestError

    with pytest.raises(GradeTestError, match="would make 8 calls"):
        run_test_files([str(EXAMPLE_TESTS)], _options(max_calls=4))

    assert factory.prompts == []


def test_case_selector_limits_what_is_graded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files(
        [str(path)], _options(case_ids=["log_method_correct"], qtags=["Exponential derivative"])
    )

    assert report.calls == 1


def test_model_override_replaces_the_questions_preference(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))
    path = _single_case_file(tmp_path, LOG_METHOD_CASE)

    from llmgrader.services.models import default_for_tier

    report = run_test_files([str(path)], _options(model="complex"))

    assert report.attempts[0].model == default_for_tier("complex").id


def test_unknown_model_is_rejected_before_any_call(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory({})
    _install_fake(monkeypatch, factory)
    path = _single_case_file(tmp_path, LOG_METHOD_CASE)

    from llmgrader.services.gradetests import GradeTestError

    with pytest.raises(GradeTestError, match="not a tier name or a known model"):
        run_test_files([str(path)], _options(model="gpt-from-the-future"))

    assert factory.prompts == []


# ---------------------------------------------------------------------------
# The JSON report -- design decision 5: nothing summarized away
# ---------------------------------------------------------------------------


def test_json_report_carries_the_whole_grader_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    out = tmp_path / "report.json"
    report = run_test_files([str(path)], _options(out=str(out)))

    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["summary"]["cases"] == 1
    assert payload["summary"]["calls"] == 1
    (record,) = payload["results"]

    assert record["case_id"] == "log_method_correct"
    assert record["qtag"] == "Exponential derivative"
    assert record["repeat"] == 1
    assert record["model"] == report.attempts[0].model
    assert record["max_points"] == 10.0
    # The stored feedback is exactly what a student would see: the model's
    # text plus the tables append_rubric_feedback adds.
    assert record["feedback"].startswith(BINARY_PASS["feedback"])
    assert "| Part | points | max_points | result |" in record["feedback"]
    assert record["full_explanation"].startswith(BINARY_PASS["full_explanation"])
    # The entire rubric_eval object, evidence included.
    assert record["rubric_eval"] == BINARY_PASS["rubric_eval"]
    assert record["expectations"]["result"] == "pass"
    assert record["failures"] == []
    assert record["tokens_in"] == 1234
    assert record["tokens_out"] == 56
    assert record["timed_out"] is False
    assert record["verdict"] == "PASS"
    assert record["description"].startswith("Full-credit control")
    assert record["solution"].startswith("Take logs")


def test_default_report_path_is_under_local_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    run_test_files([str(path)], _options())

    assert (tmp_path / "local_data" / "gradetests" / "report.json").exists()


# ---------------------------------------------------------------------------
# Package resolution -- caveat 3
# ---------------------------------------------------------------------------


def test_run_against_a_built_package(tmp_path: Path, monkeypatch) -> None:
    """--pkg passes straight through to Grader(soln_pkg=...)."""
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "unit1_calculus.xml").write_text(EXAMPLE_UNIT.read_text(encoding="utf-8"), encoding="utf-8")
    (pkg / "llmgrader_config.xml").write_text(
        """\
<llmgrader>
  <course><name>Demo</name><semester>Spring 2026</semester></course>
  <units>
    <unit>
      <name>Unit 1</name>
      <source>unit1/calculus.xml</source>
      <destination>unit1_calculus.xml</destination>
    </unit>
  </units>
</llmgrader>
""",
        encoding="utf-8",
    )

    path = tmp_path / "cases.xml"
    path.write_text(
        f'<unit_test unit="../unit1/calculus.xml">{LOG_METHOD_CASE}</unit_test>\n',
        encoding="utf-8",
    )

    report = run_test_files([str(path)], _options(pkg=str(pkg)))

    assert report.calls == 1
    assert report.failed == 0
    assert report.attempts[0].unit_name == "Unit 1"


def test_synthesized_package_carries_the_units_pkg_assets(tmp_path: Path, monkeypatch) -> None:
    """--unit must not silently drop a question's reference images.

    ``_extract_solution_images`` resolves ``/pkg_assets/...`` against the
    package root, and that mapping lives in the course config, not in the unit
    -- so the synthesized package has to replicate it.
    """
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    reply = {
        "point_parts": [4.0, 4.0],
        "full_explanation": "Both parts largely correct.",
        "feedback": "Good work.",
        "rubric_eval": {
            "identify_critical_point": {"evidence": "x = 1.", "point_awarded": 3.0},
            "evaluate_critical_value": {"evidence": "1/e.", "point_awarded": 1.0},
            "limit_at_infinity": {"evidence": "Stated.", "point_awarded": 1.0},
            "value_at_zero": {"evidence": "Stated.", "point_awarded": 1.0},
            "curve_shape": {"evidence": "Described.", "point_awarded": 1.0},
            "label_critical_point_on_graph": {"evidence": "Labelled.", "point_awarded": 1.0},
        },
    }
    _install_fake(monkeypatch, FakeOpenAIFactory({"critical point": reply}))

    path = _single_case_file(
        tmp_path,
        """
  <case id="graphing" qtag="Exponential graphing">
    <description>Text answer to the graphing question.</description>
    <solution><![CDATA[(a) The critical point is (1, 1/e). (b) Rises then decays to 0.]]></solution>
    <expected_points>
      <part label="a" min="3" max="5"/>
    </expected_points>
  </case>
""",
    )
    report = run_test_files([str(path)], _options())

    assert report.calls == 1
    # The reference solution for this question carries a /pkg_assets/ image;
    # it must have resolved through the synthesized package.
    assert report.attempts[0].reference_image_count == 1


# ---------------------------------------------------------------------------
# The console script
# ---------------------------------------------------------------------------


def test_cli_run_dry_run_makes_no_calls(monkeypatch, tmp_path: Path, capsys) -> None:
    from llmgrader.scripts.llmgrader_test import main as llmgrader_test_main

    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory({})
    _install_fake(monkeypatch, factory)

    exit_code = llmgrader_test_main(["run", str(EXAMPLE_TESTS), "--dry-run"])

    assert exit_code == 0
    assert factory.prompts == []
    out = capsys.readouterr().out
    assert "8 calls across 8 cases" in out
    assert "no API calls were made" in out


def test_cli_run_without_a_key_exits_two(monkeypatch, tmp_path: Path, capsys) -> None:
    from llmgrader.scripts.llmgrader_test import main as llmgrader_test_main

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = llmgrader_test_main(["run", str(EXAMPLE_TESTS)])

    assert exit_code == 2
    assert "no API key" in capsys.readouterr().err


def test_cli_run_reports_a_failure_with_its_evidence(monkeypatch, tmp_path: Path, capsys) -> None:
    from llmgrader.scripts.llmgrader_test import main as llmgrader_test_main

    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)

    reply = json.loads(json.dumps(BINARY_PASS))
    reply["rubric_eval"]["taking_logarithm"] = {
        "evidence": "The student never takes a logarithm.",
        "result": "n/a",
    }
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": reply}))
    path = _single_case_file(tmp_path, LOG_METHOD_CASE)

    exit_code = llmgrader_test_main(["run", str(path), "--jobs", "1", "--cost"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "taking_logarithm" in out
    assert 'evidence: "The student never takes a logarithm."' in out
    assert "estimated cost $" in out
    assert "LOWER BOUND" in out
    assert "0 passed, 1 failed" in out


def test_cli_run_passing_case_exits_zero(monkeypatch, tmp_path: Path, capsys) -> None:
    from llmgrader.scripts.llmgrader_test import main as llmgrader_test_main

    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))
    path = _single_case_file(tmp_path, LOG_METHOD_CASE)

    exit_code = llmgrader_test_main(["run", str(path), "--jobs", "1"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "1 passed, 0 failed" in out
    assert "report: " in out


def test_cli_run_max_calls_exits_two(monkeypatch, tmp_path: Path, capsys) -> None:
    from llmgrader.scripts.llmgrader_test import main as llmgrader_test_main

    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)
    factory = FakeOpenAIFactory({})
    _install_fake(monkeypatch, factory)

    exit_code = llmgrader_test_main(["run", str(EXAMPLE_TESTS), "--max-calls", "2"])

    assert exit_code == 2
    assert "would make 8 calls" in capsys.readouterr().err
    assert factory.prompts == []


# ---------------------------------------------------------------------------
# Margin -- only edges a score could actually cross
# ---------------------------------------------------------------------------


def _by_parts_case(band_min: str, band_max: str) -> str:
    return f"""
  <case id="by_parts" qtag="Integration by parts">
    <description>Full-credit control.</description>
    <solution><![CDATA[Let u = x, dv = e^{{2x}} dx. The antiderivative is (1/4)(2x-1)e^{{2x}} + C,
    and evaluating from 0 to 1 gives (e^2 + 1)/4.]]></solution>
    <expected_points>
      <part label="all" min="{band_min}" max="{band_max}"/>
    </expected_points>
  </case>
"""


def _run_by_parts(tmp_path, monkeypatch, band_min, band_max, awards, points):
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"antiderivative": _partial_reply(points, awards)}))
    path = _single_case_file(tmp_path, _by_parts_case(band_min, band_max))
    return run_test_files([str(path)], _options())


FULL_AWARDS = {
    "correct_u_dv": 3.0,
    "correct_du_v": 3.0,
    "correct_integration_by_parts": 2.0,
    "apply_limits": 2.0,
}


def test_a_score_at_the_part_total_is_not_on_a_band_edge(tmp_path: Path, monkeypatch) -> None:
    """A full-credit control banded [9,10] scoring 10 is right, not fragile.

    Nothing can score above the part's own total, so the upper edge is not an
    edge the score could cross next run.
    """
    report = _run_by_parts(tmp_path, monkeypatch, "9", "10", FULL_AWARDS, 10.0)

    assert report.verdicts == {"PASS": 1}
    assert report.attempts[0].margin == 1.0  # only the lower edge counts


def test_a_score_on_a_crossable_edge_warns(tmp_path: Path, monkeypatch) -> None:
    awards = dict(FULL_AWARDS, apply_limits=0.0)
    report = _run_by_parts(tmp_path, monkeypatch, "4", "8", awards, 8.0)

    assert report.verdicts == {"WARN": 1}
    assert report.attempts[0].margin == 0.0
    assert report.failed == 0  # a warning does not fail the run


def test_a_band_starting_at_zero_has_no_lower_edge(tmp_path: Path, monkeypatch) -> None:
    awards = {key: 0.0 for key in FULL_AWARDS}
    report = _run_by_parts(tmp_path, monkeypatch, "0", "4", awards, 0.0)

    assert report.verdicts == {"PASS": 1}
    assert report.attempts[0].margin == 4.0


# ---------------------------------------------------------------------------
# --repeat: a verdict that depends on the run is a broken case
# ---------------------------------------------------------------------------


class FakeOpenAISequence:
    """A fake that returns a different canned reply on each successive call."""

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.index = 0

    def __call__(self, *args, **kwargs):
        factory = self

        class _FakeResponses:
            def create(self, **request):
                payload = factory.payloads[min(factory.index, len(factory.payloads) - 1)]
                factory.index += 1
                return _FakeResponse(json.dumps(payload))

        class _FakeClient:
            def __init__(self) -> None:
                self.responses = _FakeResponses()

        return _FakeClient()


def test_repeat_grades_each_case_n_times(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files([str(path)], _options(repeat=3))

    assert report.calls == 3
    assert report.verdicts == {"PASS": 1}
    (case,) = report.cases
    assert [attempt.repeat_index for attempt in case.attempts] == [1, 2, 3]
    assert [attempt.session_id for attempt in case.attempts] == [
        "gradetest:log_method_correct#1",
        "gradetest:log_method_correct#2",
        "gradetest:log_method_correct#3",
    ]


def test_a_case_that_passes_sometimes_is_flaky_and_fails_the_run(tmp_path: Path, monkeypatch) -> None:
    """FLAKY is a failure: a case whose verdict depends on the run is broken."""
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    wrong = json.loads(json.dumps(BINARY_PASS))
    wrong["rubric_eval"]["taking_logarithm"]["result"] = "n/a"
    monkeypatch.setattr(
        "llmgrader.services.grader.OpenAI",
        FakeOpenAISequence([BINARY_PASS, wrong, BINARY_PASS]),
    )

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files([str(path)], _options(repeat=3, jobs=1))

    (case,) = report.cases
    assert case.verdict == "FLAKY"
    assert case.pass_count == 2
    assert report.failed == 1


def test_cli_repeat_shows_the_distribution(tmp_path: Path, monkeypatch, capsys) -> None:
    from llmgrader.scripts.llmgrader_test import main as llmgrader_test_main

    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        "llmgrader.services.grader.OpenAI",
        FakeOpenAISequence(
            [
                _partial_reply(6.0, {"correct_u_dv": 3.0, "correct_du_v": 3.0,
                                     "correct_integration_by_parts": 0.0, "apply_limits": 0.0}),
                _partial_reply(8.0, {"correct_u_dv": 3.0, "correct_du_v": 3.0,
                                     "correct_integration_by_parts": 2.0, "apply_limits": 0.0}),
                _partial_reply(6.0, {"correct_u_dv": 3.0, "correct_du_v": 3.0,
                                     "correct_integration_by_parts": 0.0, "apply_limits": 0.0}),
            ]
        ),
    )
    path = _single_case_file(tmp_path, PARTIAL_CASE)

    exit_code = llmgrader_test_main(["run", str(path), "--repeat", "3", "--jobs", "1"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "6 8 6" in out  # the observed spread, not just the last score


# ---------------------------------------------------------------------------
# The HTML report
# ---------------------------------------------------------------------------


def test_html_report_is_self_contained_and_readable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    reply = json.loads(json.dumps(BINARY_PASS))
    reply["rubric_eval"]["taking_logarithm"] = {
        "evidence": "The student never takes a logarithm.",
        "result": "n/a",
    }
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": reply}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    html_path = tmp_path / "report.html"
    report = run_test_files([str(path)], _options(html=str(html_path)))

    assert report.html_path == str(html_path)
    page = html_path.read_text(encoding="utf-8")

    # No external assets: nothing to fetch when it opens from a file:// URL.
    assert "http://" not in page and "https://" not in page
    assert "<script" not in page

    assert "log_method_correct" in page
    assert "Compute the derivative" in page  # the question text
    assert "Take logs" in page  # the submitted solution
    assert "Correct: taking logs of both sides is a valid route." in page  # the feedback
    assert "The student never takes a logarithm." in page  # the evidence
    assert 'class="badge FAIL"' in page
    assert 'class="bad"' in page  # the failing expectation is highlighted
    # The markdown table the grader appends renders as a table.
    assert "<th>Part</th>" in page


def test_html_report_shows_every_repeat(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FakeOpenAIFactory({"Take logs": BINARY_PASS}))

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    html_path = tmp_path / "report.html"
    run_test_files([str(path)], _options(repeat=2, jobs=1, html=str(html_path)))

    page = html_path.read_text(encoding="utf-8")
    assert "Attempt 1" in page
    assert "Attempt 2" in page
    assert "2/2 attempts passed" in page


# ---------------------------------------------------------------------------
# Provider failures -- an ungraded attempt is an ERROR, not a rubric failure
# ---------------------------------------------------------------------------


class FailingOpenAIFactory:
    """A client whose every call raises, the way an expired key behaves.

    Grader catches the exception and *returns* result="error" rather than
    propagating it, which is the whole reason the runner needs to notice.
    """

    def __init__(self, message: str = "Error code: 401 - invalid_api_key") -> None:
        self.message = message
        self.calls = 0

    def __call__(self, *args, **kwargs):
        factory = self

        class _FakeResponses:
            def create(self, **request):
                factory.calls += 1
                raise RuntimeError(factory.message)

        class _FakeClient:
            def __init__(self) -> None:
                self.responses = _FakeResponses()

        return _FakeClient()


def test_provider_failure_is_an_error_verdict_not_a_rubric_failure(tmp_path: Path, monkeypatch) -> None:
    """A 401 must not read as "every part failed its expectation"."""
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    factory = FailingOpenAIFactory()
    _install_fake(monkeypatch, factory)

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files([str(path)], _options())

    assert factory.calls == 1
    case = report.files[0].cases[0]
    assert case.verdict == VERDICT_ERROR
    # No band or rubric noise invented for an attempt that never happened.
    assert case.failures == []
    attempt = case.attempts[0]
    assert attempt.error is not None
    assert "401" in attempt.error


def test_error_verdict_survives_repeats(tmp_path: Path, monkeypatch) -> None:
    """Every attempt erroring is ERROR, not FLAKY."""
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FailingOpenAIFactory())

    path = _single_case_file(tmp_path, LOG_METHOD_CASE)
    report = run_test_files([str(path)], _options(repeat=3))

    case = report.files[0].cases[0]
    assert len(case.attempts) == 3
    assert case.verdict == VERDICT_ERROR
    assert report.verdicts.get(VERDICT_ERROR) == 1


def test_a_case_may_assert_the_grader_errors(tmp_path: Path, monkeypatch) -> None:
    """<expected_result>error</expected_result> is an expectation, not a bug."""
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    _install_fake(monkeypatch, FailingOpenAIFactory())

    path = _single_case_file(
        tmp_path,
        """
  <case id="expects_error" qtag="Exponential derivative">
    <description>Asserts that grading itself fails.</description>
    <solution><![CDATA[Take logs: ln y = x ln a.]]></solution>
    <expected_result>error</expected_result>
  </case>
""",
    )
    report = run_test_files([str(path)], _options())

    case = report.files[0].cases[0]
    assert case.attempts[0].error is None, "an asserted error must not short-circuit evaluation"
    assert case.verdict == VERDICT_PASS


def test_unparseable_grade_with_rubric_evidence_is_still_evaluated(tmp_path: Path, monkeypatch) -> None:
    """result="error" is not always "never graded".

    The Grader also returns it when the model answered but its score would not
    parse.  The rubric_eval it did return is real evidence, so the case must
    still be judged on it rather than written off as an ERROR.  This is the
    boundary the `ungraded` test in _grade_one turns on.
    """
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    unit = tmp_path / "unit.xml"
    unit.write_text(
        """\
<unit id="u" title="U" version="1.0">
  <question qtag="Q" preferred_model="simple">
    <question_text><![CDATA[Integrate.]]></question_text>
    <solution><![CDATA[The answer is 4.]]></solution>
    <partial_credit>true</partial_credit>
    <parts>
      <part><part_label>all</part_label><points>10</points></part>
    </parts>
    <rubrics>
      <item id="setup" point_adjustment="+10">
        <display_text>Correct setup</display_text>
        <condition>Student sets the integral up correctly.</condition>
      </item>
    </rubrics>
    <rubric_total>flexible</rubric_total>
  </question>
</unit>
""",
        encoding="utf-8",
    )
    path = tmp_path / "cases.xml"
    path.write_text(
        f"""\
<unit_test unit="{unit.as_posix()}">
  <case id="c1" qtag="Q">
    <description>Asserts the rubric item is awarded in full.</description>
    <solution><![CDATA[Some working.]]></solution>
    <expected_rubrics>
      <item id="setup" min="10" max="10"/>
    </expected_rubrics>
  </case>
</unit_test>
""",
        encoding="utf-8",
    )

    # point_parts omitted entirely -- the score will not parse, but the rubric did.
    reply = {
        "full_explanation": "Judged the rubric but produced no parsable score.",
        "feedback": "See rubric.",
        "rubric_eval": {"setup": {"evidence": "Sets it up correctly.", "point_awarded": 10.0}},
    }
    _install_fake(monkeypatch, FakeOpenAIFactory({"Some working": reply}))
    report = run_test_files([str(path)], _options())

    attempt = report.attempts[0]
    assert attempt.result == "error", "precondition: the grader could not parse a score"
    assert attempt.rubric_eval, "precondition: but it did return rubric evidence"
    assert attempt.error is None, "so it must not be written off as ungraded"
    assert report.files[0].cases[0].verdict != VERDICT_ERROR
