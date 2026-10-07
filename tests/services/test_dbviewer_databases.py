"""The Analytics viewer over two databases: grading and MCP usage.

``plans/mcp_usage.md`` decision 8.  `/admin/dbviewer`, `/schema` and
`/download` take `db=grade` (the default, so every caller from before is
unchanged) or `db=mcp`; any other value is refused rather than mapped to a
default, and neither database can be written through the viewer.
"""

import sqlite3
from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.routes.api import APIController
from llmgrader.services.mcp_usage import McpUsageStore, usage_db_path


@pytest.fixture()
def storage(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "storage"
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(root))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")
    return root


@pytest.fixture()
def client(storage: Path, tmp_path: Path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    app = create_app(scratch_dir=str(scratch), soln_pkg=None)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def usage(storage: Path) -> McpUsageStore:
    store = McpUsageStore(usage_db_path(str(storage)))
    for ts, tool, status in [
        ("2026-09-01T10:00:00+00:00", "get_question", "ok"),
        ("2026-10-01T10:00:00+00:00", "get_rubric", "ok"),
        ("2026-10-02T10:00:00+00:00", "get_solution", "tool_error"),
    ]:
        store.record({"ts": ts, "method": "tools/call", "tool": tool, "status": status,
                      "course_id": "alpha", "unit": "Unit 1", "qtag": "q1"})
    return store


def query(client, sql, db=None):
    body = {"sql_query": sql}
    if db is not None:
        body["db"] = db
    return client.post("/admin/dbviewer", json=body)


def test_no_db_means_the_grading_database(client) -> None:
    payload = query(client, "SELECT COUNT(*) FROM submissions").get_json()
    assert payload["error"] is None


def test_the_mcp_database_is_queried_by_name(client, usage) -> None:
    payload = query(client, "SELECT tool FROM mcp_calls ORDER BY ts", db="mcp").get_json()
    assert payload["error"] is None
    assert [row[0] for row in payload["rows"]] == ["get_question", "get_rubric", "get_solution"]


def test_the_grading_database_has_no_usage_table(client, usage) -> None:
    payload = query(client, "SELECT * FROM mcp_calls", db="grade").get_json()
    assert "no such table" in payload["error"]


def test_the_mcp_database_exists_before_any_call(client, storage) -> None:
    """A portal whose MCP has never been called still shows an empty table."""
    payload = query(client, "SELECT COUNT(*) FROM mcp_calls", db="mcp").get_json()
    assert payload["error"] is None
    assert payload["rows"] == [[0]]


def test_schema_follows_the_database(client, usage) -> None:
    grade = client.get("/admin/dbviewer/schema").get_json()
    mcp = client.get("/admin/dbviewer/schema?db=mcp").get_json()
    assert "submissions" in {t["name"] for t in grade["tables"]}
    tables = {t["name"]: t["columns"] for t in mcp["tables"]}
    assert "submissions" not in tables
    for column in ("ts", "session_id", "client", "tool", "status", "package_version"):
        assert column in tables["mcp_calls"]


@pytest.mark.parametrize("bad", ["users", "../llmgrader", "GRADE", "mcp_usage"])
def test_an_unknown_db_is_refused_everywhere(client, bad) -> None:
    response = query(client, "SELECT 1", db=bad)
    assert response.status_code == 400
    assert "Unknown database" in response.get_json()["error"]
    assert client.get(f"/admin/dbviewer/schema?db={bad}").status_code == 400
    assert client.get(f"/admin/dbviewer/download?db={bad}").status_code == 400


@pytest.mark.parametrize("db", ["grade", "mcp"])
def test_writes_are_refused_on_both(client, usage, db) -> None:
    table = "submissions" if db == "grade" else "mcp_calls"
    payload = query(client, f"DELETE FROM {table}", db=db).get_json()
    assert payload["error"] == "Only read-only SELECT queries are allowed"


def test_the_connection_itself_is_read_only(usage) -> None:
    """The second guard, for a statement that slips past the keyword check."""
    conn = APIController.connect_analytics_db(usage.db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO mcp_calls (ts, method, status) VALUES ('t', 'm', 's')")
    finally:
        conn.close()


def test_download_comes_from_the_database_queried(client, usage) -> None:
    query(client, "SELECT tool FROM mcp_calls ORDER BY ts", db="mcp")

    response = client.get("/admin/dbviewer/download?db=mcp")
    assert response.status_code == 200
    assert "mcp_usage.csv" in response.headers["Content-Disposition"]
    assert response.data.decode().splitlines() == [
        "tool", "get_question", "get_rubric", "get_solution"]

    # Nothing was run against the grading database, so there is nothing to
    # download from it -- not the MCP query run against the wrong file.
    assert client.get("/admin/dbviewer/download").status_code == 400


def test_delete_before_trims_usage_only(client, usage) -> None:
    response = client.post("/admin/dbviewer/mcp/delete_before", json={"before": "2026-10-01"})
    assert response.status_code == 200
    assert response.get_json()["deleted"] == 1

    payload = query(client, "SELECT ts FROM mcp_calls ORDER BY ts", db="mcp").get_json()
    assert [row[0][:10] for row in payload["rows"]] == ["2026-10-01", "2026-10-02"]


@pytest.mark.parametrize("before", ["", "yesterday", "2026-13-01", "2026-10-01; DROP"])
def test_delete_before_needs_a_date(client, usage, before) -> None:
    response = client.post("/admin/dbviewer/mcp/delete_before", json={"before": before})
    assert response.status_code == 400
    payload = query(client, "SELECT COUNT(*) FROM mcp_calls", db="mcp").get_json()
    assert payload["rows"] == [[3]]
