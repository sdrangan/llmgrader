---
title: MCP usage
parent: Analytics
nav_order: 2
has_children: false
---

# MCP Usage

If your portal serves the [course MCP](../admin/mcp/overview.md), every call
students' assistants make to it is recorded, one row per request, in a
database of its own. This page is about reading it. What is recorded, and what
never is, is described in [Deploying the course MCP](../admin/mcp/deploy.md#what-is-recorded).

## Choosing the database

Open **File ▸ Switch View ▸ Analytics**, then use the **Analytics** menu:

```
Analytics
  ✓ Grade DB        the grading database (submissions)
    MCP DB          the MCP usage database (mcp_calls)
  ─────────────
    Run Query       runs against the active database
    Download CSV    downloads the last result, from the active database
  ─────────────
    Delete Usage Before…   MCP DB only
```

The active database is ticked in the menu and named in the view's heading.
Switching loads that database's columns, puts back the last query you ran
against it (its default query the first time) and clears the results, so a
result is never shown under the wrong database. Your browser remembers which
one you last used.

The two databases cannot be joined: an MCP call carries no identity, so there
is nothing to match a grade on.

## The `mcp_calls` table

| Column | Meaning |
| --- | --- |
| `ts` | When, UTC, ISO-8601 with milliseconds. |
| `session_id` | An anonymous id for one connection, roughly one chat. Empty for assistants on the 2026 protocol. |
| `client` | `claude.ai`, `vscode`, `claude-code` or `other`. |
| `protocol` | The MCP protocol version the assistant spoke. |
| `method` | `tools/call` for a tool; also `initialize`, `tools/list`, and so on. |
| `course_id` | The course asked about. |
| `tool` | The tool called, for `tools/call`. |
| `unit`, `qtag`, `deck`, `slide` | What was asked about, as the tool resolved it. |
| `args_json` | Every argument as sent, with free text replaced by `<redacted>`. |
| `status` | `ok`, `tool_error` (the tool answered with an error, such as an unknown unit), `error` (the request failed) or `refused` (missing or wrong course token). |
| `error` | The error message, first 300 characters. |
| `duration_ms` | How long the server took. |
| `result_items` | How many items a list answer held: questions, search hits, slides. `0` for a search that found nothing. |
| `result_images` | How many images the answer carried. |
| `result_bytes` | The size of the answer. |
| `package_version` | The [course package version](../admin/mcp/package.md#package-versions) that answered. |

## Presets

The **Preset** list above the query box fills in and runs a ready-made query.
Each one is ordinary SQL in the box afterwards, so edit it to narrow it down.
Where a preset is course-scoped, it is scoped to the course you are viewing.

| Preset | What it answers |
| --- | --- |
| Latest calls | The 20 most recent requests. The default query. |
| Calls per day, by tool | How much the MCP is used, and for what. |
| Most-viewed questions | Which problems students open, with their rubric and solution views beside. |
| Solution views compared with rubric views | Per question: how often the worked solution is pulled, against the rubric. A high ratio is worth a look. |
| Most-viewed slides | Which slides assistants open. |
| Searches that found nothing | Per day, slide searches with no hit -- a sign the slides use different words from the students. The words themselves are never recorded. |
| Errors and refusals | Every request that did not succeed. |
| Calls by client | Which assistants students use, and which protocol versions. |
| Sessions per day | Sessions, and the average calls and distinct tools per session. |
| Sessions, one row each | Each session with its assistant, start, end and the tools it used. |

The two session presets use `session_id` where there is one. Otherwise they
group a client's calls into one session until there is a gap of more than 10
minutes. That rule can merge two students on the same kind of assistant at the
same time -- every claude.ai request comes from Anthropic's servers -- so read
session counts as a lower bound.

## Deleting old usage

Usage rows are kept until you delete them. With **MCP DB** active, choose
**Analytics ▸ Delete Usage Before…** and give a date as `YYYY-MM-DD`: every
row recorded before that day (UTC) is deleted, after a confirmation. It cannot
be undone. Download a CSV first if you want to keep the rows.

Only the usage database can be trimmed this way. Nothing in the Analytics view
deletes a grade.
