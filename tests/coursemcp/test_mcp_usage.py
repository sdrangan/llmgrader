"""Recording course MCP usage: ``plans/mcp_usage.md``, phase 2.

Requests go through the portal's WSGI stack as in ``test_course_mcp.py``,
because the recorder lives in that stack: what is tested is the row a real
request leaves in ``mcp_usage.db``.

The tests that matter most are the privacy ones: a student's search words
never reach the file, and every argument a tool takes is either an identifier
or redacted.
"""

import json
import sqlite3

import pytest
from flask.testing import FlaskClient

from llmgrader.coursemcp.usage import (
    IDENTIFIER_ARGUMENTS,
    REDACTED,
    REDACTED_ARGUMENTS,
    build_rows,
    client_from_session,
    coarse_client,
    mint_session_id,
)
from llmgrader.services.mcp_usage import McpUsageStore, usage_db_path
from test_course_mcp import HEADERS, MODERN_META, build_app, rpc

CLIENT_INFO = "io.modelcontextprotocol/clientInfo"


class ServerLikeClient(FlaskClient):
    """Closes each response before returning it, as gunicorn does once it is sent.

    The row is written from the response's ``close()``, so the answer is never
    delayed by the write.  Flask's test client leaves an unbuffered response
    open, which would make every row look missing.
    """

    def open(self, *args, **kwargs):
        kwargs["buffered"] = True
        return super().open(*args, **kwargs)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    app = build_app(tmp_path, monkeypatch, enabled=True)
    app.test_client_class = ServerLikeClient
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def rows(app) -> list[dict]:
    path = app.course_mcp.usage.db_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM mcp_calls ORDER BY id")]
    finally:
        conn.close()


def tool_rows(app) -> list[dict]:
    return [r for r in rows(app) if r["method"] == "tools/call"]


def call(client, name, arguments, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}
    return client.post("/mcp", json=body, headers={**HEADERS, **(headers or {})})


# ---------------------------------------------------------------------------
# One row per call
# ---------------------------------------------------------------------------


def test_a_tool_call_writes_one_row_with_resolved_names(app, client) -> None:
    response = call(client, "get_question", {"course_id": "alpha", "unit": "alpha unit",
                                             "qtag": "q1"})
    assert response.status_code == 200
    assert response.get_json()["result"].get("isError") is not True

    [row] = tool_rows(app)
    assert row["tool"] == "get_question"
    assert row["course_id"] == "alpha"
    # The typed column holds what the tool resolved the loose name to ...
    assert row["unit"] == "Alpha Unit"
    assert row["qtag"] == "q1"
    # ... and args_json what was actually sent.
    assert json.loads(row["args_json"])["unit"] == "alpha unit"
    assert row["status"] == "ok"
    assert row["error"] is None
    assert row["result_images"] == 0
    assert row["result_bytes"] == len(response.data)
    assert row["duration_ms"] >= 0
    assert row["ts"]


def test_the_row_carries_the_package_version(app, client) -> None:
    call(client, "list_units", {"course_id": "beta"})
    [row] = tool_rows(app)
    expected = app.course_mcp.registry.grader_for("beta").package_version
    assert expected and row["package_version"] == expected


def test_a_list_result_counts_its_items(app, client) -> None:
    call(client, "list_questions", {"course_id": "alpha"})
    [row] = tool_rows(app)
    assert row["result_items"] == 2


def test_a_failing_tool_is_recorded_as_tool_error(app, client) -> None:
    response = call(client, "list_units", {"course_id": "nope"})
    assert response.get_json()["result"]["isError"] is True

    [row] = tool_rows(app)
    assert row["status"] == "tool_error"
    assert "Unknown course" in row["error"]
    assert row["package_version"] is None


def test_an_unknown_method_is_recorded_as_error(app, client) -> None:
    rpc(client, "no/such/method")
    [row] = rows(app)
    assert row["method"] == "no/such/method"
    assert row["status"] == "error"


def test_a_refused_request_is_recorded_as_refused(app, client) -> None:
    app.course_mcp.token = "a-long-course-token-value"
    response = call(client, "list_courses", {})
    assert response.status_code == 403

    [row] = rows(app)
    assert row["status"] == "refused"
    assert row["tool"] == "list_courses"


def test_get_writes_nothing(app, client) -> None:
    assert client.get("/mcp").status_code == 405
    assert rows(app) == []


def test_a_failed_write_still_answers(app, client, tmp_path) -> None:
    """A usage row is not worth an error: the student's call already succeeded."""
    blocked = tmp_path / "is_a_directory"
    blocked.mkdir()
    app.course_mcp.usage = McpUsageStore(str(blocked))

    response = call(client, "list_courses", {})
    assert response.status_code == 200
    courses = response.get_json()["result"]["structuredContent"]["result"]
    assert {c["course_id"] for c in courses} == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# What is never recorded
# ---------------------------------------------------------------------------


def test_a_search_query_is_never_written(app, client) -> None:
    secret = "my homework answer is 42 volts"
    call(client, "search_slides", {"course_id": "alpha", "query": secret})

    [row] = tool_rows(app)
    assert json.loads(row["args_json"])["query"] == REDACTED
    assert secret not in json.dumps(row)
    # Nowhere in the file at all, not just not in this row's columns.
    with open(app.course_mcp.usage.db_path, "rb") as handle:
        assert secret.encode() not in handle.read()


def test_every_tool_argument_is_an_identifier_or_redacted(client) -> None:
    """A new tool with a free-text argument must be added to a list, deliberately.

    The recorder redacts an unlisted argument anyway; this test is what makes
    the choice visible in review rather than silent.
    """
    response = rpc(client, "tools/list")
    known = IDENTIFIER_ARGUMENTS | REDACTED_ARGUMENTS
    unlisted = {
        (tool["name"], arg)
        for tool in response.get_json()["result"]["tools"]
        for arg in tool["inputSchema"].get("properties", {})
        if arg not in known
    }
    assert unlisted == set(), f"name these in IDENTIFIER_ or REDACTED_ARGUMENTS: {unlisted}"


def test_an_unlisted_argument_is_redacted() -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "ask", "arguments": {"course_id": "alpha",
                                                               "message": "student words"}}})
    [row] = build_rows(body.encode(), {}, 200, b"", 1)
    assert json.loads(row["args_json"]) == {"course_id": "alpha", "message": REDACTED}


def test_no_identity_is_recorded(app, client) -> None:
    call(client, "list_courses", {}, headers={"User-Agent": "Mozilla/5.0 secret-agent",
                                              "X-Forwarded-For": "203.0.113.9"})
    [row] = rows(app)
    flat = json.dumps(row)
    assert "secret-agent" not in flat and "203.0.113.9" not in flat


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def initialize(client, name="claude-ai"):
    body = {"jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": name, "version": "1.0"}}}
    return client.post("/mcp", json=body, headers=HEADERS)


def test_initialize_mints_a_session_id_carrying_the_client(app, client) -> None:
    response = initialize(client, "Visual Studio Code")
    assert response.status_code == 200
    session_id = response.headers["Mcp-Session-Id"]
    assert client_from_session(session_id) == "vscode"

    [row] = rows(app)
    assert row["method"] == "initialize"
    assert row["session_id"] == session_id
    assert row["client"] == "vscode"
    assert row["protocol"] == "2025-06-18"


def test_later_requests_are_recorded_under_the_session(app, client) -> None:
    session_id = initialize(client).headers["Mcp-Session-Id"]
    response = call(client, "list_courses", {}, headers={
        "Mcp-Session-Id": session_id, "MCP-Protocol-Version": "2025-06-18"})
    # The stateless server accepts an id it never issued itself.
    assert response.status_code == 200

    tool_row = tool_rows(app)[0]
    assert tool_row["session_id"] == session_id
    assert tool_row["client"] == "claude.ai"
    assert tool_row["protocol"] == "2025-06-18"


def test_modern_requests_have_no_session_but_name_their_client(app, client) -> None:
    meta = {**MODERN_META, CLIENT_INFO: {"name": "claude-code", "version": "2"}}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "list_courses", "arguments": {}, "_meta": meta}}
    response = client.post("/mcp", json=body, headers={
        **HEADERS, "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call",
        "Mcp-Name": "list_courses"})
    assert response.status_code == 200
    assert "Mcp-Session-Id" not in response.headers

    [row] = tool_rows(app)
    assert row["session_id"] is None
    assert row["client"] == "claude-code"
    assert row["protocol"] == "2026-07-28"


def test_modern_client_info_in_meta_is_read() -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {
        "_meta": {CLIENT_INFO: {"name": "claude-code"},
                  "io.modelcontextprotocol/protocolVersion": "2026-07-28"}}})
    [row] = build_rows(body.encode(), {}, 200, b"", 1)
    assert row["client"] == "claude-code"
    assert row["protocol"] == "2026-07-28"
    assert row["session_id"] is None


@pytest.mark.parametrize("name, expected", [
    ("claude-ai", "claude.ai"),
    ("Anthropic/ClaudeAI", "claude.ai"),
    ("claude-code", "claude-code"),
    ("Visual Studio Code", "vscode"),
    ("Visual Studio Code - Insiders", "vscode"),
    ("cursor", "other"),
    (None, None),
])
def test_coarse_client(name, expected) -> None:
    assert coarse_client(name) == expected


def test_a_session_id_from_elsewhere_names_no_client() -> None:
    assert client_from_session("not-ours") is None
    assert client_from_session(mint_session_id(None)) == "other"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


def test_the_store_lives_beside_the_grading_database(app) -> None:
    storage = app.course_mcp.registry.storage
    assert app.course_mcp.usage.db_path == usage_db_path(storage.get_storage_path())


def test_init_is_idempotent_and_delete_before_trims(tmp_path) -> None:
    store = McpUsageStore(str(tmp_path / "db" / "mcp_usage.db"))
    McpUsageStore(store.db_path)  # a second boot changes nothing
    for ts in ("2026-09-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"):
        assert store.record({"ts": ts, "method": "tools/list", "status": "ok"})
    assert store.delete_before("2026-09-15") == 1
    conn = sqlite3.connect(store.db_path)
    try:
        assert conn.execute("SELECT ts FROM mcp_calls").fetchall() == \
            [("2026-10-01T00:00:00+00:00",)]
    finally:
        conn.close()
