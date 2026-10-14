"""Practice grading through the course MCP: get_grading_prompt and score_grade.

``plans/mcp_grading.md``.  Properties that would fail silently if they
regressed:

* the prompt is the one ``Grader.grade`` sends -- a reworded copy would still
  grade, just not the way the portal does;
* get_grading_prompt takes no answer, so a student's words never reach the
  server for it;
* score_grade scores exactly as ``grade_post_process`` does, and turns a reply
  the portal would mark "error" into a ToolError the AI can act on;
* neither tool calls a model: on the one sync worker a model call would
  freeze every student's grading.
"""

import json
import time
from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.coursemcp import content as cc
from llmgrader.services.grader import _build_message_content

UNIT = "Unit 1:  Basics"
SOLN_PNG = b"\x89PNG\r\n\x1a\n" + b"solution-figure"
HEADERS = {"Accept": "application/json, text/event-stream"}

CONFIG_XML = f"""<llmgrader>
  <course>
    <course_id>alpha</course_id>
    <name>Alpha Course</name>
    <semester>Fall 2026</semester>
  </course>
  <units>
    <unit>
      <name>{UNIT}</name>
      <source>unit.xml</source>
      <destination>unit.xml</destination>
    </unit>
  </units>
</llmgrader>
"""

UNIT_XML = """<unit id="u1" title="Basics" version="1.0">
  <question qtag="Two parts">
    <question_text><![CDATA[<p>Find tau, then v_C(t).</p>]]></question_text>
    <solution><![CDATA[<p>tau = 1 s; v_C(t) = 5 - 3 exp(-t).</p>
<img src="/pkg_assets/alpha_images/soln.png">]]></solution>
    <grading_notes><![CDATA[Accept equivalent forms.]]></grading_notes>
    <partial_credit>true</partial_credit>
    <rubric_total>sum_positive</rubric_total>
    <parts>
      <part><part_label>a</part_label><points>2</points></part>
      <part><part_label>b</part_label><points>3</points></part>
    </parts>
    <rubrics>
      <item id="tau" part="a" point_adjustment="+2">
        <display_text>Time constant</display_text>
        <condition>tau = RC = 1 s.</condition>
      </item>
      <item id="form" part="b" point_adjustment="+3">
        <display_text>Step response</display_text>
        <condition>v_C(t) = 5 - 3 exp(-t/tau).</condition>
      </item>
      <item id="limits" scored="false">
        <display_text>Check at the limits</display_text>
        <condition>Evaluate the expression at t = 0 and as t goes to infinity.</condition>
      </item>
    </rubrics>
  </question>
  <question qtag="Deductions">
    <question_text><![CDATA[<p>Write the counter.</p>]]></question_text>
    <solution><![CDATA[<p>count <= count + 1;</p>]]></solution>
    <grading_notes><![CDATA[None.]]></grading_notes>
    <partial_credit>true</partial_credit>
    <rubric_total>sum_negative</rubric_total>
    <parts><part><part_label>all</part_label><points>4</points></part></parts>
    <rubrics>
      <item id="reset" point_adjustment="-2">
        <display_text>Missing reset</display_text>
        <condition>The counter has no reset.</condition>
      </item>
      <item id="width" point_adjustment="-1">
        <display_text>Wrong width</display_text>
        <condition>The counter is not 8 bits wide.</condition>
      </item>
    </rubrics>
  </question>
  <question qtag="Binary">
    <question_text><![CDATA[<p>Is 7 prime?</p>]]></question_text>
    <solution><![CDATA[<p>Yes.</p>]]></solution>
    <grading_notes><![CDATA[Accept yes.]]></grading_notes>
    <parts><part><part_label>all</part_label><points>1</points></part></parts>
  </question>
  <question qtag="Binary parts">
    <question_text><![CDATA[<p>(a) Is 7 prime? (b) Is 9 prime?</p>]]></question_text>
    <solution><![CDATA[<p>(a) Yes. (b) No.</p>]]></solution>
    <grading_notes><![CDATA[None.]]></grading_notes>
    <parts>
      <part><part_label>a</part_label><points>1</points></part>
      <part><part_label>b</part_label><points>1</points></part>
    </parts>
  </question>
</unit>
"""


@pytest.fixture()
def app(tmp_path: Path, monkeypatch):
    storage = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    monkeypatch.setenv("LLMGRADER_MCP_ENABLED", "1")
    monkeypatch.delenv("LLMGRADER_MCP_TOKEN", raising=False)

    courses_root = storage / "courses"
    pkg = courses_root / "alpha" / "soln_pkg"
    (pkg / "alpha_images").mkdir(parents=True)
    (pkg / "llmgrader_config.xml").write_text(CONFIG_XML, encoding="utf-8")
    (pkg / "unit.xml").write_text(UNIT_XML, encoding="utf-8")
    (pkg / "alpha_images" / "soln.png").write_bytes(SOLN_PNG)
    courses_root.joinpath("courses.json").write_text(json.dumps({
        "courses": [{"id": "alpha", "name": "Alpha Course", "semester": "Fall 2026",
                     "created_at": "2026-01-01T00:00:00+00:00", "id_source": "authored"}],
        "default": "alpha",
    }), encoding="utf-8")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    app = create_app(scratch_dir=str(scratch), soln_pkg=None)
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def grader(app):
    return app.registry.grader_for("alpha")


def question(grader, qtag: str) -> dict:
    return cc.resolve_question(grader, UNIT, qtag)[2]


def call(client, name, arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}
    response = client.post("/mcp", json=body, headers=HEADERS)
    assert response.status_code == 200, response.data
    return response.get_json()["result"]


def payload(result: dict) -> dict:
    """The JSON payload: the last text block, after any figures."""
    assert result.get("isError") is not True, result
    return json.loads([b for b in result["content"] if b["type"] == "text"][-1]["text"])


def error_text(result: dict) -> str:
    assert result.get("isError") is True, result
    return result["content"][0]["text"]


def args(qtag: str, **extra) -> dict:
    return {"course_id": "alpha", "unit": UNIT, "qtag": qtag, **extra}


# ---------------------------------------------------------------------------
# get_grading_prompt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("qtag, part, mode", [
    ("Two parts", "all", "partial_multi_all"),
    ("Two parts", "b", "partial_multi_single"),
    ("Deductions", "all", "partial_single"),
    ("Binary", "all", "binary_single"),
    ("Binary parts", "all", "binary_multi_all"),
    ("Binary parts", "a", "binary_multi_single"),
])
def test_the_prompt_is_the_portals(client, grader, qtag, part, mode) -> None:
    """Byte for byte what Grader.grade sends, with the placeholder for the answer."""
    q = question(grader, qtag)
    task, _ = grader.build_task_prompt(q, cc.STUDENT_ANSWER_PLACEHOLDER, part_label=part)
    expected, _ = _build_message_content(task, q.get("solution_images") or [], [])

    body = payload(call(client, "get_grading_prompt", args(qtag, part=part)))
    assert body["prompt"] == expected
    assert body["grading_mode"] == mode
    assert body["prompt"].rstrip().endswith(cc.STUDENT_ANSWER_PLACEHOLDER) \
        or "--- REFERENCE SOLUTION IMAGES ---" in body["prompt"]


def test_the_prompt_carries_the_solution_figures(client) -> None:
    result = call(client, "get_grading_prompt", args("Two parts"))
    images = [b for b in result["content"] if b["type"] == "image"]
    assert len(images) == 1
    body = payload(result)
    assert "--- REFERENCE SOLUTION IMAGES ---" in body["prompt"]
    assert body["figures_attached"] == 1
    assert body["max_points"] == [2, 3]


def test_the_result_says_what_to_do_with_it(client) -> None:
    body = payload(call(client, "get_grading_prompt", args("Binary")))
    assert body["instruction"] == cc.GRADING_INSTRUCTION
    assert "only if they ask to see it" in body["instruction"]
    assert "score_grade" in body["instruction"]
    assert set(body["response_schema"]["properties"]) >= {"feedback", "full_explanation"}


def test_get_grading_prompt_takes_no_answer(client) -> None:
    """The student's answer stays in the conversation (decision 2)."""
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                           headers=HEADERS)
    [tool] = [t for t in response.get_json()["result"]["tools"]
              if t["name"] == "get_grading_prompt"]
    assert set(tool["inputSchema"]["properties"]) == {"course_id", "unit", "qtag", "part"}


def test_an_unknown_part_lists_the_valid_ones(client) -> None:
    text = error_text(call(client, "get_grading_prompt", args("Two parts", part="c")))
    assert "'a'" in text and "'b'" in text and "'all'" in text


def test_a_part_label_is_matched_loosely(client) -> None:
    assert payload(call(client, "get_grading_prompt", args("Two parts", part=" B ")))["part"] == "b"


# ---------------------------------------------------------------------------
# score_grade
# ---------------------------------------------------------------------------


def portal_score(grader, qtag: str, part: str, raw: dict) -> dict:
    """What Grader.grade does with the same reply, called directly."""
    from llmgrader.services.grader import GraderRawResult

    q = question(grader, qtag)
    _, max_points = grader.build_task_prompt(q, "", part_label=part)
    # Flask's test client sends JSON with its keys sorted, so the tool sees
    # rubric_eval in that order; the rubric table follows it.
    raw = json.loads(json.dumps(raw, sort_keys=True))
    return grader.grade_post_process(
        GraderRawResult.model_validate(raw).model_dump(),
        partial_credit=q.get("partial_credit", False) is True,
        max_points_part=max_points,
        part_labels=[p.get("part_label", "all") for p in q.get("parts", [])],
        part_label=part,
        rubrics=q.get("rubrics", {}),
        rubric_total=q.get("rubric_total"),
        tools=q.get("tools", []),
    ).model_dump()


MULTI_PART = {
    "point_parts": [2, 1],
    "full_explanation": "tau right; form off.",
    "feedback": "Check the exponent.",
    "rubric_eval": {
        "tau": {"evidence": "tau = 1 s", "point_awarded": 2},
        "form": {"evidence": "exponent sign", "point_awarded": 0},
        # A feedback-only item the AI scored anyway: the score must not count.
        "limits": {"evidence": "v(0) = 2 V", "point_awarded": 1},
    },
}


@pytest.mark.parametrize("qtag, part, raw", [
    ("Two parts", "all", MULTI_PART),
    ("Deductions", "all", {
        "points": 2, "full_explanation": "No reset.", "feedback": "Add a reset.",
        "rubric_eval": {"reset": {"evidence": "no rst", "point_awarded": -2},
                        "width": {"evidence": "8 bits", "point_awarded": 0}}}),
    ("Binary", "all", {"result": "pass", "full_explanation": "Yes.", "feedback": "Right."}),
    ("Binary parts", "all", {"result_parts": ["pass", "fail"], "full_explanation": "x",
                             "feedback": "(b) is wrong."}),
])
def test_scoring_matches_the_portal(client, grader, qtag, part, raw) -> None:
    body = payload(call(client, "score_grade", args(qtag, part=part, grade=raw)))
    expected = portal_score(grader, qtag, part, raw)
    assert {k: body[k] for k in expected} == expected
    assert body["estimate"] is True
    assert body["disclaimer"] == cc.ESTIMATE_DISCLAIMER


def test_the_portal_totals_from_the_rubric(client) -> None:
    """The AI's point_parts lose to its own rubric awards, as on the portal."""
    raw = {**MULTI_PART, "point_parts": [0, 0]}
    body = payload(call(client, "score_grade", args("Two parts", grade=raw)))
    assert body["point_parts"] == [2.0, 0.0]
    assert body["points"] == 2.0
    assert body["max_points"] == 5.0
    assert "Rubric evaluation:" in body["feedback"]


def test_a_grade_sent_as_json_text_is_accepted(client) -> None:
    body = payload(call(client, "score_grade", args("Two parts", grade=json.dumps(MULTI_PART))))
    assert body["points"] == 2.0


def test_a_grade_missing_a_field_names_it(client) -> None:
    raw = {"result": "pass", "full_explanation": "Yes."}
    text = error_text(call(client, "score_grade", args("Binary", grade=raw)))
    assert "feedback" in text


def test_a_grade_with_the_wrong_type_names_it(client) -> None:
    raw = {"points": "lots", "full_explanation": "x", "feedback": "y"}
    text = error_text(call(client, "score_grade", args("Deductions", grade=raw)))
    assert "points" in text


def test_a_grade_the_portal_would_mark_error_is_refused(client) -> None:
    """No rubric awards and no point_parts: the portal would show "error"."""
    raw = {"full_explanation": "x", "feedback": "y"}
    text = error_text(call(client, "score_grade", args("Two parts", grade=raw)))
    assert "point_parts" in text and "score_grade again" in text


def test_score_grade_writes_no_submission(client, grader) -> None:
    call(client, "score_grade", args("Binary", grade={
        "result": "pass", "full_explanation": "Yes.", "feedback": "Right."}))
    assert grader.storage.count_submissions_for_course("alpha") == 0


# ---------------------------------------------------------------------------
# No model, no wait
# ---------------------------------------------------------------------------


def test_neither_tool_calls_a_model(client, monkeypatch) -> None:
    import llmgrader.services.grader as grader_module

    def refuse(*_args, **_kwargs):
        raise AssertionError("a practice-grading tool tried to call a model")

    monkeypatch.setattr(grader_module, "OpenAI", refuse)
    monkeypatch.setattr(grader_module, "_make_openai_caller", refuse)

    t0 = time.monotonic()
    payload(call(client, "get_grading_prompt", args("Two parts")))
    payload(call(client, "score_grade", args("Two parts", grade=MULTI_PART)))
    assert time.monotonic() - t0 < 1.0
