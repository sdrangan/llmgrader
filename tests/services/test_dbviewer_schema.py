"""Tests for the Analytics column reference endpoint.

`/admin/dbviewer/schema` feeds the clickable column list beside the SQL box.
It reads the live database rather than Grader.DB_SCHEMA, because older files
are patched column-by-column by temp_modify_db and can hold columns the class
attribute no longer declares.
"""

import sqlite3
from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.routes.api import APIController


@pytest.fixture()
def client_and_db(tmp_path: Path, monkeypatch):
    storage_path = tmp_path / "storage"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "dev-open")

    app = create_app(scratch_dir=str(scratch), soln_pkg=None)
    app.config["TESTING"] = True
    return app.test_client(), storage_path / "db" / "llmgrader.db"


def _tables(client) -> dict:
    payload = client.get("/admin/dbviewer/schema").get_json()
    assert payload["error"] is None
    return {t["name"]: t["columns"] for t in payload["tables"]}


def test_schema_lists_submissions_columns(client_and_db):
    """The submissions table and its real columns are offered to the UI."""
    client, db_path = client_and_db
    tables = _tables(client)

    assert "submissions" in tables
    for column in ("id", "timestamp", "qtag", "unit_name", "points", "model"):
        assert column in tables["submissions"]


def test_schema_matches_the_live_database(client_and_db):
    """Columns come from the file on disk, not from a hard-coded list."""
    client, db_path = client_and_db

    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE submissions ADD COLUMN a_late_addition TEXT")
    conn.commit()
    conn.close()

    assert "a_late_addition" in _tables(client)["submissions"]


def test_schema_hides_user_email(client_and_db):
    """submissions.user_email is never offered, even when the column exists.

    It is a dead column from an older schema, scrubbed to NULL by
    Grader.temp_modify_db.  Listing it would imply we still hold student
    emails, so it is filtered server-side rather than merely hidden in the UI.
    """
    client, db_path = client_and_db

    conn = sqlite3.connect(db_path)
    columns = [row[1] for row in conn.execute("PRAGMA table_info('submissions')")]
    if "user_email" not in columns:
        conn.execute("ALTER TABLE submissions ADD COLUMN user_email TEXT")
        conn.commit()
    conn.close()

    # Present in the database itself...
    conn = sqlite3.connect(db_path)
    real_columns = [row[1] for row in conn.execute("PRAGMA table_info('submissions')")]
    conn.close()
    assert "user_email" in real_columns

    # ...but absent from what the endpoint serves, and nothing else was dropped.
    served = _tables(client)["submissions"]
    assert "user_email" not in served
    assert set(real_columns) - set(served) == {"user_email"}


def test_hidden_columns_are_scoped_to_their_table():
    """The filter is keyed on (table, column), not on the column name alone."""
    assert ("submissions", "user_email") in APIController.SCHEMA_HIDDEN_COLUMNS
    assert all(
        isinstance(entry, tuple) and len(entry) == 2
        for entry in APIController.SCHEMA_HIDDEN_COLUMNS
    )
