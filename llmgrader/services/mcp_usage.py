"""The course MCP usage database: one row per MCP request.

``plans/mcp_usage.md``, decisions 1 and 2.  A file of its own beside the
grading database rather than a table in it, so a burst of tool calls never
contends with grade submissions for SQLite's single writer lock, and so the
log -- high-volume telemetry -- can be trimmed or wiped without touching a
grade.

Like :class:`PortalStorage`, the store knows nothing about courses beyond the
``course_id`` a row is handed.  It never raises out of :meth:`record`: the
student's call has already been answered, and usage data is not worth an
error.
"""

from __future__ import annotations

import os
import sqlite3

DB_FILENAME = "mcp_usage.db"

# Typed for what is grouped on; everything else is in args_json.  The order
# here is the table's column order.
SCHEMA = {
    "ts": "TEXT NOT NULL",
    "session_id": "TEXT",
    "client": "TEXT",
    "protocol": "TEXT",
    "method": "TEXT NOT NULL",
    "course_id": "TEXT",
    "tool": "TEXT",
    "unit": "TEXT",
    "qtag": "TEXT",
    "deck": "TEXT",
    "slide": "INTEGER",
    "args_json": "TEXT",
    "status": "TEXT NOT NULL",
    "error": "TEXT",
    "duration_ms": "INTEGER",
    "result_items": "INTEGER",
    "result_images": "INTEGER",
    "result_bytes": "INTEGER",
    "package_version": "TEXT",
}

INDEXES = {
    "idx_mcp_usage_ts": "ts",
    "idx_mcp_usage_course_tool": "course_id, tool",
    "idx_mcp_usage_session": "session_id",
}

# A locked database waits this long, then the row is dropped.
WRITE_TIMEOUT_S = 2.0


def usage_db_path(storage_root: str) -> str:
    """``<storage>/db/mcp_usage.db``, beside the grading database."""
    return os.path.join(storage_root, "db", DB_FILENAME)


class McpUsageStore:
    """Owns ``mcp_usage.db``: its schema, its writes and its one delete."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        try:
            self.init_db()
        except (OSError, sqlite3.Error) as exc:
            # Not fatal: the portal serves on, and record() drops each row.
            print(f"[McpUsage] Could not open {db_path}: {exc!r}")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=WRITE_TIMEOUT_S)

    def init_db(self) -> None:
        """Create the table and its indexes.  Idempotent, like PortalStorage's."""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        columns = ",\n".join(f"{name} {kind}" for name, kind in SCHEMA.items())
        conn = self._connect()
        try:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS mcp_calls (\n"
                f"id INTEGER PRIMARY KEY AUTOINCREMENT,\n{columns}\n)"
            )
            existing = {row[1] for row in conn.execute("PRAGMA table_info(mcp_calls)")}
            for name, kind in SCHEMA.items():
                if name not in existing:
                    kind = kind.replace(" NOT NULL", "")
                    conn.execute(f"ALTER TABLE mcp_calls ADD COLUMN {name} {kind} DEFAULT NULL")
            for index, cols in INDEXES.items():
                conn.execute(f"CREATE INDEX IF NOT EXISTS {index} ON mcp_calls({cols})")
            conn.commit()
        finally:
            conn.close()

    def record(self, row: dict) -> bool:
        """Insert one row; keys outside SCHEMA are ignored.  False if dropped."""
        record = {name: row.get(name) for name in SCHEMA}
        names = ", ".join(SCHEMA)
        placeholders = ", ".join(f":{name}" for name in SCHEMA)
        try:
            conn = self._connect()
            try:
                conn.execute(f"INSERT INTO mcp_calls ({names}) VALUES ({placeholders})", record)
                conn.commit()
            finally:
                conn.close()
            return True
        except Exception as exc:  # never fail the call being recorded
            print(f"[McpUsage] Dropped a usage row: {exc!r}")
            return False

    def delete_before(self, ts: str) -> int:
        """Delete rows recorded before *ts* (ISO-8601); return how many."""
        conn = self._connect()
        try:
            deleted = conn.execute("DELETE FROM mcp_calls WHERE ts < ?", (ts,)).rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()
