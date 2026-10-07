"""The course MCP's content tier: the token, and the question/rubric/solution tools.

``plans/course_mcp.md`` decisions 3 and 4.  Properties that would fail
silently if they regressed:

* without a token the content tools do not exist at all -- an answer key on
  the open web is the failure the token exists to prevent;
* a wrong or missing token is a 403 with a readable message, never a 401,
  which would send claude.ai into a sign-in flow this server does not offer;
* get_question and list_questions never carry the solution or the grading
  notes -- a leak there still looks like a working tool;
* figures arrive as images, numbered to match the text, and a figure path
  cannot climb out of the course package.
"""

import base64
import json
from pathlib import Path

import pytest

from llmgrader.app import create_app

TOKEN = "test-course-token-0123456789"
PNG = b"\x89PNG\r\n\x1a\n" + b"question-figure"
SOLN_PNG = b"\x89PNG\r\n\x1a\n" + b"solution-figure"
UNIT = "Unit 1:  Basics"  # double space, as real unit names have

SOLUTION_SENTINEL = "SOLUTION-SENTINEL-reflect-the-position"
NOTES_SENTINEL = "NOTES-SENTINEL-common-mistake"

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

UNIT_XML = f"""<unit id="u1" title="Basics" version="1.0">
  <question qtag="Bouncing ball">
    <question_text><![CDATA[<p>A ball moves between two walls at 0 and 100.</p>
<img src="/pkg_assets/alpha_images/ball.png">
<p>Write the next-state logic.</p>]]></question_text>
    <solution><![CDATA[<p>{SOLUTION_SENTINEL}</p><img src="/pkg_assets/alpha_images/ball_soln.png">]]></solution>
    <grading_notes><![CDATA[{NOTES_SENTINEL}: clamping instead of reflecting.]]></grading_notes>
    <partial_credit>true</partial_credit>
    <rubric_total>sum_positive</rubric_total>
    <variation_guidance>Vary the wall positions; keep the reflection rule.</variation_guidance>
    <parts>
      <part><part_label>a</part_label><points>2</points></part>
      <part><part_label>b</part_label><points>3</points></part>
    </parts>
    <rubrics>
      <item id="ball_move" part="a" point_adjustment="2">
        <display_text>Free motion</display_text>
        <condition>Position advances by <code>v</code>.</condition>
        <notes>Award from the numbers alone.</notes>
      </item>
      <item id="ball_wall" part="b" point_adjustment="3">
        <display_text>Reflection at the wall</display_text>
        <condition>Position is reflected, not clamped.</condition>
      </item>
    </rubrics>
  </question>
  <question qtag="Plain question">
    <question_text><![CDATA[<p>{"A long question. " * 20}</p>]]></question_text>
    <solution><![CDATA[<p>Answer.</p>]]></solution>
    <grading_notes><![CDATA[Accept it.]]></grading_notes>
    <parts><part><part_label>all</part_label><points>1</points></part></parts>
  </question>
  <question qtag="Escaping figure">
    <question_text><![CDATA[<p>Look:</p><img src="/pkg_assets/../../secret.png">]]></question_text>
    <solution><![CDATA[<p>None.</p>]]></solution>
    <grading_notes><![CDATA[None.]]></grading_notes>
    <parts><part><part_label>all</part_label><points>1</points></part></parts>
  </question>
</unit>
"""

HEADERS = {"Accept": "application/json, text/event-stream"}


def build_app(tmp_path: Path, monkeypatch, *, token: str | None):
    storage = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    monkeypatch.setenv("LLMGRADER_MCP_ENABLED", "1")
    if token:
        monkeypatch.setenv("LLMGRADER_MCP_TOKEN", token)
    else:
        monkeypatch.delenv("LLMGRADER_MCP_TOKEN", raising=False)

    courses_root = storage / "courses"
    pkg = courses_root / "alpha" / "soln_pkg"
    (pkg / "alpha_images").mkdir(parents=True)
    (pkg / "llmgrader_config.xml").write_text(CONFIG_XML, encoding="utf-8")
    (pkg / "unit.xml").write_text(UNIT_XML, encoding="utf-8")
    (pkg / "alpha_images" / "ball.png").write_bytes(PNG)
    (pkg / "alpha_images" / "ball_soln.png").write_bytes(SOLN_PNG)
    # Outside the package: must never be served.
    (courses_root / "alpha" / "secret.png").write_bytes(b"\x89PNG\r\n\x1a\nSECRET")

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
def client(tmp_path, monkeypatch):
    return build_app(tmp_path, monkeypatch, token=TOKEN).test_client()


def rpc(client, method, params=None, *, path="/mcp", auth=TOKEN):
    headers = dict(HEADERS)
    if auth:
        headers["Authorization"] = f"Bearer {auth}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post(path, json=body, headers=headers)


def call(client, name, arguments=None, **kwargs) -> dict:
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments or {}}, **kwargs)
    assert response.status_code == 200, response.data
    return response.get_json()["result"]


def payload(result: dict):
    """The JSON payload: the first text block."""
    return json.loads(result["content"][0]["text"])


def tool_names(client, **kwargs) -> set[str]:
    response = rpc(client, "tools/list", **kwargs)
    assert response.status_code == 200, response.data
    return {tool["name"] for tool in response.get_json()["result"]["tools"]}


CONTENT_TOOLS = {"list_questions", "get_question", "get_rubric", "get_solution",
                 "list_materials", "get_outline", "search_slides", "get_slide"}


# ---------------------------------------------------------------------------
# The token
# ---------------------------------------------------------------------------


def test_without_a_token_only_titles_are_served(tmp_path, monkeypatch) -> None:
    client = build_app(tmp_path, monkeypatch, token=None).test_client()
    names = tool_names(client, auth=None)
    assert names == {"list_courses", "list_units"}
    assert not names & CONTENT_TOOLS


def test_with_a_token_content_tools_are_served(client) -> None:
    assert tool_names(client) == {"list_courses", "list_units"} | CONTENT_TOOLS


@pytest.mark.parametrize("auth", [None, "wrong-token-wrong-token"])
def test_missing_or_wrong_token_is_403_with_a_message(client, auth) -> None:
    response = rpc(client, "tools/list", auth=auth)
    assert response.status_code == 403  # not 401: that starts an OAuth sign-in
    assert "course access token" in response.get_json()["error"]["message"]


def test_token_in_the_path_is_accepted(client) -> None:
    assert tool_names(client, path=f"/mcp/{TOKEN}", auth=None) >= CONTENT_TOOLS


def test_wrong_token_in_the_path_is_refused(client) -> None:
    assert rpc(client, "tools/list", path="/mcp/not-the-token", auth=None).status_code == 403


def test_non_ascii_bearer_is_refused_not_crashed(client) -> None:
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                           headers={**HEADERS, "Authorization": "Bearer töken"})
    assert response.status_code == 403


def test_browser_check_needs_no_token(client) -> None:
    response = client.get("/mcp")
    assert response.status_code == 405
    assert b"course MCP server, and it is running" in response.data


# ---------------------------------------------------------------------------
# list_questions
# ---------------------------------------------------------------------------


def test_list_questions_indexes_the_whole_course(client) -> None:
    index = payload_list(call(client, "list_questions", {"course_id": "alpha"}))
    assert [q["qtag"] for q in index] == ["Bouncing ball", "Plain question", "Escaping figure"]
    ball = index[0]
    assert ball["unit"] == UNIT
    assert ball["points"] == 5
    assert ball["parts"] == [{"part": "a", "points": 2.0}, {"part": "b", "points": 3.0}]
    assert ball["label"].startswith("A ball moves between two walls")


def test_list_questions_labels_are_short(client) -> None:
    index = payload_list(call(client, "list_questions", {"course_id": "alpha"}))
    assert all(len(q["label"]) <= 100 for q in index)


def test_unit_name_tolerates_spacing_and_case(client) -> None:
    index = payload_list(call(client, "list_questions",
                              {"course_id": "alpha", "unit": "unit 1: basics"}))
    assert len(index) == 3


def test_unknown_unit_lists_the_valid_ones(client) -> None:
    result = call(client, "list_questions", {"course_id": "alpha", "unit": "Unit 9"})
    assert result["isError"] is True
    assert UNIT in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# get_question / get_rubric / get_solution
# ---------------------------------------------------------------------------


def images(result: dict) -> list[bytes]:
    return [base64.b64decode(b["data"]) for b in result["content"] if b["type"] == "image"]


def test_get_question_returns_text_figure_and_guidance(client) -> None:
    result = call(client, "get_question",
                  {"course_id": "alpha", "unit": UNIT, "qtag": "Bouncing ball"})
    body = payload(result)
    assert "[Figure 1]" in body["question"]
    assert "<img" not in body["question"]
    assert body["variation_guidance"].startswith("Vary the wall positions")
    assert images(result) == [PNG]
    assert result["content"][1] == {"type": "text", "text": "Figure 1:"}


def test_qtag_tolerates_case(client) -> None:
    body = payload(call(client, "get_question",
                        {"course_id": "alpha", "unit": UNIT, "qtag": "bouncing BALL"}))
    assert body["qtag"] == "Bouncing ball"


def test_unknown_qtag_lists_the_valid_ones(client) -> None:
    result = call(client, "get_question", {"course_id": "alpha", "unit": UNIT, "qtag": "Nope"})
    assert result["isError"] is True
    assert "Bouncing ball" in result["content"][0]["text"]


def test_get_rubric_returns_items_and_grading_notes(client) -> None:
    body = payload(call(client, "get_rubric",
                        {"course_id": "alpha", "unit": UNIT, "qtag": "Bouncing ball"}))
    assert [item["id"] for item in body["rubric"]] == ["ball_move", "ball_wall"]
    assert body["rubric"][0] == {
        "id": "ball_move", "part": "a", "display_text": "Free motion",
        "condition": "Position advances by v .", "points": 2.0,
        "notes": "Award from the numbers alone.",
    }
    assert NOTES_SENTINEL in body["grading_notes"]
    assert SOLUTION_SENTINEL not in json.dumps(body)


def test_get_solution_returns_solution_and_its_figure(client) -> None:
    result = call(client, "get_solution",
                  {"course_id": "alpha", "unit": UNIT, "qtag": "Bouncing ball"})
    assert SOLUTION_SENTINEL in payload(result)["solution"]
    assert images(result) == [SOLN_PNG]


@pytest.mark.parametrize("tool, args", [
    ("list_questions", {"course_id": "alpha"}),
    ("get_question", {"course_id": "alpha", "unit": UNIT, "qtag": "Bouncing ball"}),
])
def test_question_tools_never_carry_the_answer_key(client, tool, args) -> None:
    text = json.dumps(call(client, tool, args))
    assert SOLUTION_SENTINEL not in text
    assert NOTES_SENTINEL not in text


def test_figure_path_cannot_leave_the_package(client) -> None:
    result = call(client, "get_question",
                  {"course_id": "alpha", "unit": UNIT, "qtag": "Escaping figure"})
    assert images(result) == []
    assert payload(result)["figure_notes"] == [
        "Figure 1 could not be loaded from the course package."]


def test_portal_page_payload_is_unchanged_by_variation_guidance(client) -> None:
    unit = client.get(f"/c/alpha/unit/{UNIT}").get_json()
    question = unit["items"]["Bouncing ball"] if "items" in unit else unit["Bouncing ball"]
    assert "variation_guidance" not in question


def payload_list(result: dict) -> list:
    """A list tool's items: one JSON text block per item."""
    assert result.get("isError") is not True, result
    return [json.loads(block["text"]) for block in result["content"]]
