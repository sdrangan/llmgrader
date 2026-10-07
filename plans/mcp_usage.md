# Plan: recording course MCP usage

Record every course MCP tool call in its own database, version every course
package so a recorded call can be reproduced, and show both on the Analytics
page beside the grading data.

```
<storage>/db/
  llmgrader.db      # grading -- unchanged, except one new column
  mcp_usage.db      # new: one row per course MCP call
```

## Motivation

The course MCP (`plans/course_mcp.md`) is live, and the only record of its use
is a `[CourseMCP] get_rubric course=... unit=... qtag=...` line in Render's
logs, which are short-lived and cannot be queried. The questions an instructor
will ask -- how much it is used, which problems and slides students look at,
how often they open the solution rather than the rubric, which searches find
nothing, which assistants they use, and whether calls fail -- need the calls in
a table.

## What already exists

| Need | Already in the tree |
| --- | --- |
| A WSGI layer that sees every MCP request and response | `CourseMCPRunner.__call__` (`coursemcp/mount.py`) |
| Per-call log line with the ids asked about, never student text | `log_call` (`coursemcp/server.py`) |
| SQLite storage, idempotent schema, run-once migrations | `PortalStorage` (`services/portal_storage.py`): `DB_SCHEMA`, `init_db`, `temp_modify_db`, `portal_migrations` |
| A read-only SQL viewer with schema browser and CSV download | `/admin/dbviewer`, `/admin/dbviewer/schema`, `/admin/dbviewer/download` (`routes/api.py`), `static/js/analytics.js` |
| The package build step | `create_soln_pkg` (`scripts/create_soln_pkg.py`) |

## Design decisions

### 1. A separate database file

`mcp_usage.db`, not a table in `llmgrader.db`, for two reasons beyond the rows
being different:

- **Grading never waits on usage logging.** SQLite allows one writer per file.
  In one file, a burst of tool calls would contend for the same lock as grade
  submissions.
- **The usage log is disposable.** It is high-volume telemetry that will be
  trimmed, wiped between semesters or downloaded, without touching grade
  records.

The usual reason to share a database -- joining across it -- does not apply:
MCP calls carry no identity, so there is nothing to join grades on.

A small `McpUsageStore` class owns the file, its schema and its writes, on the
pattern of `PortalStorage`, and like it knows nothing about courses beyond the
`course_id` it is handed.

### 2. Columns: typed for what is grouped on, JSON for the rest

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | |
| `ts` | TEXT NOT NULL | UTC ISO-8601 |
| `session_id` | TEXT | see decision 5; NULL when the client has none |
| `client` | TEXT | `claude.ai`, `vscode`, `claude-code`, `other` |
| `protocol` | TEXT | MCP protocol version of the request |
| `method` | TEXT NOT NULL | `tools/call`, `tools/list`, `initialize`, ... |
| `course_id` | TEXT | |
| `tool` | TEXT | for `tools/call` |
| `unit`, `qtag`, `deck` | TEXT | the ids asked about |
| `slide` | INTEGER | |
| `args_json` | TEXT | every argument, except student text (decision 6) |
| `status` | TEXT NOT NULL | `ok`, `tool_error`, `error`, `refused` |
| `error` | TEXT | message, first 300 characters |
| `duration_ms` | INTEGER | |
| `result_items` | INTEGER | list length: questions, hits, slides |
| `result_images` | INTEGER | image blocks returned |
| `result_bytes` | INTEGER | response size |
| `package_version` | TEXT | decision 4 |

Indexes on `ts`, on `(course_id, tool)` and on `session_id`.

The arguments students pass are often loose ("unit 2", "bouncing BALL"); the
tools resolve them. **The typed columns hold the resolved names**, read from the
tool's result, which echoes them; `args_json` keeps what was sent.

### 3. The response is summarized, not stored

A `get_slide` response carries a ~100 KB image and `get_solution` a worked
solution: storing responses would grow the file by megabytes an hour of use,
and would duplicate what the arguments and the package version already
determine. The row keeps what answers the questions above: status, error, size,
item and image counts.

### 4. Every course package carries a version

`create_soln_pkg` writes `package_info.json` into the package:

```json
{
  "version": "2026-10-07.3f9c2a1",
  "built_at": "2026-10-07T21:40:12Z",
  "content_sha256": "3f9c2a1e...",
  "sources": {
    "hwdesign-soln": "54cc4a3 (clean)",
    "hwdesign": "089706c (2 uncommitted changes)"
  }
}
```

- **`version`** is the build date and the head of a hash over the package's
  files, sorted by path, `package_info.json` excluded. It is never typed by
  hand: a hand-set version is forgotten, and two packages under one version are
  worse than none. Identical contents give the same version.
- **`sources`** is each repository's commit at build time -- the config's
  directory and each `<root>` of `llmgrader_mcp_config.xml` -- flagged when it
  had uncommitted changes, in which case the commit alone does not reproduce
  the package.
- **A package without the file** (built before this, or by hand) gets a version
  computed from its contents when the `Grader` loads it, so every row has one.

The version is recorded in `mcp_usage.package_version`, in a new
`submissions.package_version` column in the grading database (added by
`temp_modify_db`, guarded like every column there) so a grade can be traced to
the rubric that produced it, returned by `list_courses`, and shown beside the
course on the Admin page after an upload. It is not added to the other tools'
results, where an assistant would read it on every call to no purpose.

### 5. Sessions: minted where the protocol allows, inferred where it does not

The server is stateless: nothing links one call to the next.

- **2025 protocol clients** open a connection with `initialize`, and the
  Streamable HTTP transport requires a client to echo an `Mcp-Session-Id` the
  server sets on that response. `CourseMCPRunner` adds a random id to every
  `initialize` response and logs the id each later request carries. No state is
  kept, so any worker serves any request; verified that the stateless server
  accepts a request carrying an id it never issued. The id lasts one
  connection, roughly one chat, and is linked to nothing else.
- **2026-07-28 clients** have no handshake and no session id (SEP-2567, removed
  so servers scale without session affinity), but name the client in each
  request's `_meta`. For them, and for any client that does not echo the id,
  sessions are inferred at query time: same client, split on a gap of more than
  10 minutes. This merges two students using the same client at the same time,
  since claude.ai's requests all come from Anthropic's servers.

The "sessions" preset query uses `session_id` where present and the time-gap
rule otherwise.

### 6. What is never recorded

- **Student text.** `search_slides`'s `query` is replaced by `"<redacted>"` in
  `args_json`, as `log_call` already leaves it out of the log line. It is the
  only free-text argument today; any future one is redacted the same way, by a
  list in the recorder, with a test that fails if a tool gains a free-text
  argument the list does not name.
- **Identity.** No IP address, no user agent string beyond the coarse `client`.
  With no token there is no identity to record; with one, it is the class's
  shared token and is not recorded either.

### 7. Recording happens in the WSGI layer, and never fails a call

`CourseMCPRunner.__call__` already sees every request. It reads the JSON-RPC
method and arguments from the request body, times the downstream call, reads
status, sizes and the resolved names from the response body -- the server
answers in JSON, not an event stream -- and writes one row. This covers both
protocol versions, refused requests (403) and errors, with no change to the
tools.

A failed write is logged and dropped: the student's call has already
succeeded, and usage data is not worth an error. The write runs after the
response body has been collected, so it adds its few milliseconds to the
request rather than delaying the answer's first byte; if that shows up in
practice, it moves to a queue and a writer thread.

`GET /mcp` (the 405 page) is not recorded: it is a browser check, not use.

### 8. Analytics: choosing the database from the Analytics menu

The view is reached as today, **File ▸ Switch View ▸ Analytics**. Its
**Analytics** menu (`#analytics-menu-group` in `index.html`), which already has
Run Query and Download CSV, gains the database choice at the top:

```
Analytics
  ✓ Grade DB        switch the view to the grading database
    MCP DB          switch the view to the MCP usage database
  ─────────────
    Run Query       runs against the active database
    Download CSV    downloads the last result, from the active database
```

- **Switching database** reloads the schema panel for that database, restores
  the last query run against it (its default query the first time), and clears
  the results, so a result is never shown under the wrong database. A check mark in the menu, and the database's
  name in the view's header, show which one is active.
- **The active database** is a parameter on `/admin/dbviewer`, `/schema` and
  `/download` (`db=grade` or `db=mcp`, default `grade`, so nothing that calls
  them today changes); the server maps it to a file and refuses any other
  value. The read-only SQL check applies to both.
- **The choice is remembered** in the browser, beside the per-database
  queries, by the same `saveAnalyticsState` that saves the query today, and
  starts at Grade DB.
- **Each database has its own default query and presets.** For MCP usage:

- calls per day, by tool;
- most-viewed questions (`get_question`), with rubric and solution views beside;
- solution views compared with rubric views, per question;
- most-viewed slides, and searches that found nothing (`result_items = 0`);
- errors and refusals;
- calls by client;
- sessions: count, calls per session, tools per session.

### 9. Retention

Keep everything for now. The Analytics page gets "delete usage before date",
admin only, for the MCP database only.

## Phases

1. **Package version.** `package_info.json` from `create_soln_pkg`; computed
   fallback; `submissions.package_version`; shown on the Admin page and in
   `list_courses`. Lands on its own and is useful for grading alone.
2. **Usage recording.** `McpUsageStore`, the recorder in `CourseMCPRunner`, the
   minted session id, redaction.
3. **Analytics.** Grade DB / MCP DB in the Analytics menu, presets,
   delete-before-date.
4. **Docs.** `docs/admin/mcp/deploy.md` (what is recorded and what is not) and
   `docs/analytics/` (the selector and presets); a sentence on the student page
   saying usage is counted anonymously.

## Tests

- A tool call writes exactly one row, with resolved names, status, sizes and
  `package_version`; a failing tool writes `tool_error`; a refused request
  writes `refused`.
- `search_slides` never writes its query anywhere in the row; a tool whose
  arguments include an unlisted free-text field fails the redaction test.
- A failed write -- unwritable file -- still returns the tool's result.
- `initialize` returns an `Mcp-Session-Id`, and later requests carrying it are
  recorded under it; 2026-07-28 requests are recorded with no session.
- `package_info.json` is reproducible: same files, same version; any changed
  file, a different one. A package without it gets a computed version.
- `submissions.package_version` is added once and filled by grading.
- The viewer runs against either database, and refuses writes on both; an
  unknown `db=` value is refused, never mapped to a default.
- UI (Playwright, `tests/ui/`): the Analytics menu lists both databases with
  the active one checked; switching changes the schema panel, restores that
  database's query and clears the results; Run Query and Download CSV use the
  active database. CI does not run this suite, so it is run by hand before
  merging.
- `GET /mcp` writes nothing.

## Open questions

- **Top search hit.** Keep only the hit count, or also the top hit's deck and
  slide? The latter shows what a search found, still without the student's
  words.
- **Per-student usage.** Not possible without identity; it is phase 3 of
  `plans/course_mcp.md` (a per-student token), a much larger step.
- **`rubric_eval`.** Grading still drops the per-item rubric results
  (`course_mcp.md` decision 8). It is the natural companion to
  `submissions.package_version`, but a separate change.

## Status

All four phases are implemented (2026-10-07), not yet merged.

Departures from the text above, and the open questions settled on the way:

- **`sources` counts only the package's inputs.** `create_soln_pkg` collects
  every file and directory it copies or builds from (config, units and their
  `images/`, assets, the MCP config, the descriptions cache, each deck's pptx
  and pdf) and runs `git status` restricted to those paths. A stray file
  elsewhere in a repository is not counted; an untracked or ignored input is,
  as "files not in git".
- **A computed version** is `computed.<hash head>`: there is no build date to
  put in front of it.
- **The client is carried in the minted session id** (`claude.ai.<hex>`).
  2025 clients name themselves only in `initialize`, and the server is
  stateless, so this is how a later call knows its client.
- **Rows are written from the response's `close()`**, after the answer has
  been sent, rather than before it.
- **Unlisted arguments are redacted**, in addition to the test that fails on
  one: safe by default, and visible in review.
- **The viewer opens both databases read-only** (`mode=ro`), a second guard
  behind the keyword check.
- **The grading database got presets too**: latest submissions, per day by
  unit, by package version, and timeouts/errors.
- **Top search hit** (open question): not recorded; only the hit count.
- **The database choice** is remembered in `localStorage`; the per-database
  queries are remembered for the page's lifetime, as the query was before.
