"""The course MCP at /mcp: mounted only when enabled, and course-scoped.

``plans/course_mcp.md``.  Requests go through the portal's own WSGI stack, as
gunicorn would send them, rather than calling the tool functions directly --
the mount is the part most likely to break, and it breaks silently: a portal
whose /mcp 404s or 421s still serves every page.

The server is stateless with JSON responses, so a ``tools/call`` needs no
``initialize`` first and every exchange is one POST and one JSON body.
"""

import json
from pathlib import Path

import pytest

from llmgrader.app import create_app

CONFIG_XML = """<llmgrader>
  <course>
    <course_id>{course_id}</course_id>
    <name>{name}</name>
    <semester>Fall 2026</semester>
  </course>
  <units>
    <section>Lectures</section>
    <unit>
      <name>{unit_title}</name>
      <source>unit.xml</source>
      <destination>unit.xml</destination>
    </unit>
  </units>
</llmgrader>
"""

UNIT_XML = """<unit id="u1" title="{unit_title}" version="1.0">
  <question qtag="q1">
    <question_text><![CDATA[<p>Question one</p>]]></question_text>
    <solution><![CDATA[<p>Answer one</p>]]></solution>
    <grading_notes><![CDATA[Accept it.]]></grading_notes>
    <parts><part><part_label>all</part_label><points>1</points></part></parts>
  </question>
  <question qtag="q2">
    <question_text><![CDATA[<p>Question two</p>]]></question_text>
    <solution><![CDATA[<p>Answer two</p>]]></solution>
    <grading_notes><![CDATA[Accept it.]]></grading_notes>
    <parts><part><part_label>all</part_label><points>1</points></part></parts>
  </question>
</unit>
"""

COURSES = {
    "alpha": {"name": "Alpha Course", "unit_title": "Alpha Unit"},
    "beta": {"name": "Beta Course", "unit_title": "Beta Unit"},
}

# Every MCP POST must accept both; the server refuses a request that does not.
HEADERS = {"Accept": "application/json, text/event-stream"}


def build_app(tmp_path: Path, monkeypatch, *, enabled: bool, archived=()):
    storage = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    if enabled:
        monkeypatch.setenv("LLMGRADER_MCP_ENABLED", "1")
    else:
        monkeypatch.delenv("LLMGRADER_MCP_ENABLED", raising=False)
    # A token set in the shell must not leak in and refuse these requests.
    monkeypatch.delenv("LLMGRADER_MCP_TOKEN", raising=False)

    courses_root = storage / "courses"
    for course_id, spec in COURSES.items():
        pkg = courses_root / course_id / "soln_pkg"
        pkg.mkdir(parents=True)
        (pkg / "llmgrader_config.xml").write_text(
            CONFIG_XML.format(course_id=course_id, **spec), encoding="utf-8")
        (pkg / "unit.xml").write_text(UNIT_XML.format(**spec), encoding="utf-8")

    courses_root.joinpath("courses.json").write_text(json.dumps({
        "courses": [
            {"id": cid, "name": spec["name"], "semester": "Fall 2026",
             "created_at": "2026-01-01T00:00:00+00:00", "id_source": "authored",
             "deleted_at": "2026-02-01T00:00:00+00:00" if cid in archived else None}
            for cid, spec in COURSES.items()
        ],
        "default": "alpha",
    }), encoding="utf-8")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    app = create_app(scratch_dir=str(scratch), soln_pkg=None)
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    return build_app(tmp_path, monkeypatch, enabled=True).test_client()


def rpc(client, method: str, params: dict | None = None, **kwargs):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers=HEADERS, **kwargs)


def call_tool(client, name: str, arguments: dict | None = None) -> dict:
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments or {}})
    assert response.status_code == 200, response.data
    return response.get_json()["result"]


def tool_items(result: dict) -> list:
    """A list result arrives as one text content block per item."""
    return [json.loads(block["text"]) for block in result["content"]]


# ---------------------------------------------------------------------------
# Mounting
# ---------------------------------------------------------------------------


def test_mcp_is_not_served_unless_enabled(tmp_path, monkeypatch) -> None:
    client = build_app(tmp_path, monkeypatch, enabled=False).test_client()
    assert rpc(client, "tools/list").status_code == 404


def test_failed_mount_leaves_the_portal_serving(tmp_path, monkeypatch) -> None:
    """Main deploys straight to the live portal; /mcp must not be able to stop it booting."""
    import llmgrader.coursemcp.mount as mount

    def broken_mount(app, registry):
        raise RuntimeError("simulated mount failure")

    monkeypatch.setattr(mount, "mount_course_mcp", broken_mount)
    client = build_app(tmp_path, monkeypatch, enabled=True).test_client()
    assert client.get("/c/alpha/units").status_code == 200
    assert rpc(client, "tools/list").status_code == 404


def test_nothing_starts_until_the_first_mcp_request(tmp_path, monkeypatch) -> None:
    """gunicorn may build the app in its master and fork workers from it.

    A thread started at app creation would not survive the fork, leaving each
    worker a loop nothing runs -- every MCP request then hangs, holding the
    portal's only worker.  So creating the app must start no thread at all.
    """
    app = build_app(tmp_path, monkeypatch, enabled=True)
    runner = app.course_mcp
    assert runner._loop is None
    assert rpc(app.test_client(), "tools/list").status_code == 200
    assert runner._loop is not None and runner._loop.is_running()


def test_a_forked_process_starts_its_own_mcp(client, monkeypatch) -> None:
    """After a fork the pid differs, and the inherited server must not be used."""
    import os

    assert rpc(client, "tools/list").status_code == 200
    runner = client.application.course_mcp
    first_wsgi = runner._wsgi

    real_pid = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: real_pid + 1)
    assert rpc(client, "tools/list").status_code == 200
    assert runner._wsgi is not first_wsgi
    assert runner._pid == real_pid + 1


def within(seconds: float, fn):
    """Run *fn* in a thread and fail if it has not returned in *seconds*.

    The failures guarded below are hangs, and a hang must fail the suite
    rather than stall it.
    """
    import threading

    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("result", fn()), daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"request still open after {seconds}s"
    return box["result"]


MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


def modern_rpc(client, method: str, params: dict, extra_headers: dict | None = None):
    """A request in the 2026-07-28 protocol, which clients are moving to."""
    headers = {**HEADERS, "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method,
               **(extra_headers or {})}
    body = {"jsonrpc": "2.0", "id": 1, "method": method,
            "params": {**params, "_meta": MODERN_META}}
    return client.post("/mcp", json=body, headers=headers)


@pytest.mark.parametrize("accept", ["text/html,*/*;q=0.8", "text/event-stream"])
def test_get_is_refused_at_once_with_a_readable_message(client, accept) -> None:
    """A GET asks for a standing event stream, which mcp 2 never closes.

    A browser or crawler visiting /mcp would hold gunicorn's only sync worker,
    and the portal with it.  It must get a 405 instead -- which is also what a
    person checking the address in a browser reads.
    """
    response = within(5, lambda: client.get("/mcp", headers={"Accept": accept}))
    assert response.status_code == 405
    assert response.headers["Allow"] == "POST"
    assert b"course MCP server, and it is running" in response.data


def test_subscriptions_listen_is_refused_at_once(client) -> None:
    """subscriptions/listen is a POST held open for notifications: same hazard."""
    response = within(5, lambda: modern_rpc(
        client, "subscriptions/listen", {"notifications": {"toolsListChanged": True}}))
    assert response.get_json()["error"]["code"] == -32601  # method not found


def test_modern_protocol_tool_call(client) -> None:
    response = within(5, lambda: modern_rpc(
        client, "tools/call", {"name": "list_courses", "arguments": {}},
        {"Mcp-Name": "list_courses"}))
    assert response.status_code == 200
    courses = response.get_json()["result"]["structuredContent"]["result"]
    assert {c["course_id"] for c in courses} == {"alpha", "beta"}


def test_portal_routes_still_served_beside_mcp(client) -> None:
    assert client.get("/c/alpha/units").status_code == 200


def test_tools_are_listed(client) -> None:
    response = rpc(client, "tools/list")
    assert response.status_code == 200
    names = {tool["name"] for tool in response.get_json()["result"]["tools"]}
    assert names == {"list_courses", "list_units", "list_questions", "get_question",
                     "get_rubric", "get_solution", "list_materials", "get_outline",
                     "search_slides", "get_slide"}


def test_public_host_header_is_accepted(client) -> None:
    """On Render the Host is the service's own domain, not localhost.

    The MCP library's default DNS-rebinding protection answers that with a 421, which
    would leave the endpoint unreachable from every AI client while every
    local test passed.
    """
    response = rpc(client, "tools/list", base_url="https://llmgrader.onrender.com")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def test_list_courses_returns_every_live_course(client) -> None:
    courses = tool_items(call_tool(client, "list_courses"))
    assert {c["course_id"] for c in courses} == {"alpha", "beta"}
    assert {c["name"] for c in courses} == {"Alpha Course", "Beta Course"}


def test_archived_course_is_neither_listed_nor_served(tmp_path, monkeypatch) -> None:
    client = build_app(tmp_path, monkeypatch, enabled=True, archived=("beta",)).test_client()
    assert [c["course_id"] for c in tool_items(call_tool(client, "list_courses"))] == ["alpha"]
    assert call_tool(client, "list_units", {"course_id": "beta"})["isError"] is True


@pytest.mark.parametrize("course_id", ["alpha", "beta"])
def test_list_units_reads_the_named_course(client, course_id) -> None:
    items = tool_items(call_tool(client, "list_units", {"course_id": course_id}))
    assert items == [
        {"type": "section", "name": "Lectures"},
        {"type": "unit", "name": COURSES[course_id]["unit_title"], "questions": 2},
    ]


def test_unknown_course_is_an_error_not_the_default(client) -> None:
    result = call_tool(client, "list_units", {"course_id": "gamma"})
    assert result["isError"] is True
    assert "list_courses" in result["content"][0]["text"]
