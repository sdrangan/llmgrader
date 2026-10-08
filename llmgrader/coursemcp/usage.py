"""What one course MCP request is recorded as: ``plans/mcp_usage.md``.

``CourseMCPRunner`` (``mount.py``) sees every MCP request and its response as
bytes.  This module turns that pair into one ``mcp_calls`` row and decides
what is kept:

* **The ids asked about, resolved.**  Students pass loose names ("unit 2"),
  the tools resolve them and echo the result, and the typed columns hold what
  the tool resolved to.  ``args_json`` keeps what was sent.
* **Never student text.**  A free-text argument is replaced by
  ``"<redacted>"``.  Every argument a tool takes must be named in either
  IDENTIFIER_ARGUMENTS or REDACTED_ARGUMENTS -- a test fails otherwise -- and
  any argument named in neither is redacted anyway.
* **A summary of the response, not the response**: status, size, item and
  image counts.  A slide image or a worked solution would grow the file by
  megabytes an hour, and the arguments plus the package version already
  determine it.
* **No identity.**  No IP address, no user agent; only a coarse client name.

Sessions (decision 5): 2025 clients open a connection with ``initialize`` and
must echo the ``Mcp-Session-Id`` the server sets on its response, so the
runner mints one there.  The server keeps no state, so the coarse client name
is carried in the id itself -- 2025 clients name themselves only in
``initialize``, and this is how a later call knows which client made it.
2026-07-28 clients have no handshake and name themselves in every request's
``_meta`` instead.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone

# Arguments that name course content.  Kept, and the resolved forms of
# unit/qtag/deck/slide/demo/path go in their own columns.  kind and the line
# numbers are a demo tool's choice of view, not student text.
IDENTIFIER_ARGUMENTS = frozenset({"course_id", "unit", "unit_type", "qtag", "deck", "slide",
                                  "demo", "path", "kind", "start_line", "end_line"})

# Arguments that carry the student's own words.  Never recorded.
REDACTED_ARGUMENTS = frozenset({"query"})

REDACTED = "<redacted>"

# An identifier argument is still typed by an AI from what a student said;
# it is capped rather than trusted to be short.
MAX_ARG_CHARS = 200
MAX_ERROR_CHARS = 300

CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"

CLIENTS = ("claude.ai", "vscode", "claude-code", "other")
_SESSION_RE = re.compile(r"^(claude\.ai|vscode|claude-code|other)\.[0-9a-f]{32}$")


def coarse_client(name: str | None) -> str | None:
    """A client's self-reported name, reduced to one of CLIENTS.

    The raw name can carry a version or a machine-specific string; only the
    family is worth grouping on.  None when the client gave no name.
    """
    if not name:
        return None
    lowered = name.lower()
    if "claude-code" in lowered or "claude code" in lowered:
        return "claude-code"
    if "visual studio code" in lowered or "vscode" in lowered or "vs code" in lowered:
        return "vscode"
    if "claude" in lowered or "anthropic" in lowered:
        return "claude.ai"
    return "other"


def mint_session_id(client: str | None) -> str:
    """A random id for one connection, with its coarse client in front."""
    return f"{client or 'other'}.{secrets.token_hex(16)}"


def client_from_session(session_id: str | None) -> str | None:
    match = _SESSION_RE.match(session_id or "")
    return match.group(1) if match else None


def parse_json(body: bytes):
    try:
        return json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, ValueError):
        return None


def redact_arguments(arguments) -> dict:
    """*arguments* with student text replaced and long values capped."""
    if not isinstance(arguments, dict):
        return {}
    kept = {}
    for name, value in arguments.items():
        if name not in IDENTIFIER_ARGUMENTS:
            # REDACTED_ARGUMENTS, and anything unknown: safe by default.
            kept[name] = REDACTED
        elif isinstance(value, str):
            kept[name] = value[:MAX_ARG_CHARS]
        elif value is None or isinstance(value, (int, float, bool)):
            kept[name] = value
        else:
            kept[name] = REDACTED
    return kept


def _request_fields(message: dict, environ) -> dict:
    """The row's columns that come from the request alone."""
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    method = message.get("method") if isinstance(message.get("method"), str) else "unknown"

    session_id = (environ.get("HTTP_MCP_SESSION_ID") or "").strip() or None
    client_info = meta.get(CLIENT_INFO_META_KEY)
    if method == "initialize":
        client_info = params.get("clientInfo")
    name = client_info.get("name") if isinstance(client_info, dict) else None
    client = coarse_client(name) or client_from_session(session_id)

    protocol = (meta.get(PROTOCOL_VERSION_META_KEY)
                or environ.get("HTTP_MCP_PROTOCOL_VERSION")
                or (params.get("protocolVersion") if method == "initialize" else None))

    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "session_id": session_id[:100] if session_id else None,
        "client": client,
        "protocol": str(protocol)[:40] if protocol else None,
        "method": method[:100],
    }
    if method == "tools/call":
        arguments = params.get("arguments")
        args = redact_arguments(arguments)
        row["tool"] = str(params.get("name") or "")[:100] or None
        row["args_json"] = json.dumps(args, ensure_ascii=False, sort_keys=True)
        row["course_id"] = args.get("course_id") if isinstance(args.get("course_id"), str) else None
        for key in ("unit", "qtag", "deck", "demo", "path"):
            if isinstance(args.get(key), str):
                row[key] = args[key]
        if isinstance(args.get("slide"), int) and not isinstance(args.get("slide"), bool):
            row["slide"] = args["slide"]
    return row


def _payload_of(result: dict):
    """The tool's own return value, as the client received it.

    A dict return comes back as ``structuredContent``; a list return as
    ``structuredContent.result``; a list of content blocks (a result with
    figures) has no structured form, and its first text block is the JSON
    payload.
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        if set(structured) == {"result"}:
            return structured["result"]
        return structured
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parsed = parse_json(block.get("text", "").encode("utf-8"))
            if isinstance(parsed, (dict, list)):
                return parsed
            break
    return None


def _apply_response(row: dict, response, status_code: int) -> None:
    """Fill status, error and the result summary from the JSON-RPC response."""
    if status_code >= 400 and not isinstance(response, dict):
        row["status"] = "error"
        row["error"] = f"HTTP {status_code}"
        return
    if not isinstance(response, dict):
        row["status"] = "ok" if status_code < 400 else "error"
        return
    if isinstance(response.get("error"), dict):
        row["status"] = "error"
        row["error"] = str(response["error"].get("message") or "")[:MAX_ERROR_CHARS]
        return

    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    content = [b for b in (result.get("content") or []) if isinstance(b, dict)]
    if row.get("method") == "tools/call":
        row["result_images"] = sum(1 for b in content if b.get("type") == "image")
    if result.get("isError"):
        row["status"] = "tool_error"
        text = next((b.get("text", "") for b in content if b.get("type") == "text"), "")
        row["error"] = str(text)[:MAX_ERROR_CHARS]
        return
    row["status"] = "ok"
    if row.get("method") != "tools/call":
        return

    payload = _payload_of(result)
    if isinstance(payload, list):
        row["result_items"] = len(payload)
        # A list asked for one unit (or deck, or demo) resolved it: every item
        # names it.
        for key in ("unit", "deck", "demo"):
            values = {item.get(key) for item in payload if isinstance(item, dict)}
            if row.get(key) and len(values) == 1 and None not in values:
                row[key] = str(values.pop())[:MAX_ARG_CHARS]
    elif isinstance(payload, dict):
        for key in ("unit", "qtag", "deck", "path"):
            if isinstance(payload.get(key), str):
                row[key] = payload[key][:MAX_ARG_CHARS]
        # A demo file names the demos it belongs to; a search, its hits.
        demos = payload.get("demos")
        if not row.get("demo") and isinstance(demos, list) and demos and isinstance(demos[0], str):
            row["demo"] = demos[0][:MAX_ARG_CHARS]
        if isinstance(payload.get("hits"), list):
            row["result_items"] = len(payload["hits"])
        if isinstance(payload.get("slide"), int):
            row["slide"] = payload["slide"]


def build_rows(request_body: bytes, environ, status_code: int, response_body: bytes,
               duration_ms: int, *, refused: bool = False) -> list[dict]:
    """The rows to record for one HTTP exchange: one per JSON-RPC message.

    A notification (no id) gets a row like any request; its response is an
    empty 202.  A batch -- gone from the protocol since 2025-06, but cheap to
    handle -- gets one row per message, sharing the response summary only
    where the ids match.
    """
    request = parse_json(request_body)
    messages = request if isinstance(request, list) else [request]
    response = parse_json(response_body)
    responses = response if isinstance(response, list) else [response]
    by_id = {r.get("id"): r for r in responses if isinstance(r, dict) and "id" in r}

    rows = []
    for message in messages:
        if not isinstance(message, dict):
            message = {}
        row = _request_fields(message, environ)
        row["duration_ms"] = duration_ms
        row["result_bytes"] = len(response_body)
        if refused:
            row["status"] = "refused"
            row["error"] = f"HTTP {status_code}"
        else:
            matched = by_id.get(message.get("id")) if len(messages) > 1 else response
            _apply_response(row, matched, status_code)
        rows.append(row)
    return rows
