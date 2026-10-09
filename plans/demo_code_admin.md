# Plan: see and update a course's demo code from Manage Courses

**Status: built on `feature/demo-code-admin` (2026-10-09), not merged.**
Builds on `plans/demo_code_mcp.md`.

Where the build departs from the text below:

- **`load_materials` was already cached** per package directory, keyed on
  the manifest's mtime, so the course list costs one `stat` per course. No
  change was needed.
- **The endpoint tests are in `tests/coursemcp/test_code_admin.py`**, not
  `tests/services/test_manage_courses.py`: they need the local git repo and
  the `<code>` materials that `test_course_code.py` builds, and pytest's
  imports do not reach across test directories.
- **`GET .../code` returns `{"code": <object>}`**, not the bare object, so a
  course without `<code>` is still a JSON object (`{"code": null}`).
- **`progress.json` also carries `updated_at`**, and staleness counts from
  the last stage written, not the start: a stage is a few git commands at
  most, while a whole sync with a fallback clone can be seven. A fallback
  clone rewrites the stage to restart that clock. A progress file written by
  this process while no sync is running here is reported stale at once.
- **`run_git` decodes UTF-8 explicitly.** A commit subject need not be
  ASCII, and Windows would decode it as cp1252.
- **Six statuses, six words.** `never_synced` shows as "Not synced yet";
  the plan's list of words left it out.
- **Check and update answer 409 when demo code is off** and 404 when the
  course has no `<code>`; the plan did not say. A package whose `<code>`
  cannot be read gives `{"enabled": true, "status": "error", "last_error":
  ...}` rather than breaking the course list.
- **Update now is done when `last_attempt` moves and no live progress
  remains**, not when `synced_at` passes the click. The browser's clock is
  not the server's, and a failed sync moves `last_attempt` but not
  `synced_at`. The dialog also shows the stages of any sync that is running,
  including a lazy refresh it did not start.
- **Manage Courses is wider** (`.modal-dialog-wide`), to fit the column.
  Disabled modal buttons are now faded everywhere: a disabled Update now
  looked the same as an enabled one.

Add a **Demo code** column to the Manage Courses dialog. For each course
that publishes demo code, the column shows which commit the course MCP is
serving and whether GitHub has a newer one. Clicking it opens a small
dialog that compares the served commit with the remote branch head. When
they differ, the dialog offers **Update now** and shows the sync's stage as
it runs.

```
Manage Courses
  Hardware Design (Fall 2026)   2026-10-08.3f9c1a2   a1b2c3d4e5f6  Update available   412 graded  [Archive]

Demo code: Hardware Design (Fall 2026)
  sdrangan/hwdesign @ main
                Commit         Date                Message
  Serving       a1b2c3d4e5f6   2026-10-08 21:14    Rebuild the streaming demos as build DAGs
  On GitHub     9e8d7c6b5a43   checked 12 s ago
  Last synced   2026-10-09 08:02   (no errors)
                                                           [Update now]  [Close]

  after clicking:   checking remote  ✓   fetching  ✓   building snapshot ...   validating   serving
```

## Motivation

The portal refreshes its copy of the demo repo lazily. An MCP request
notices that the copy is older than the time limit (`DEFAULT_TTL_S`,
10 minutes) and starts a background sync. The request that triggered it is
answered from the old copy. Nobody waits, but after a push to `hwdesign`:

- the instructor cannot tell which commit the MCP is serving without
  calling `list_courses` from a chat;
- the first student question after the push gets the old content;
- a sync that fails keeps serving the last good copy and logs the error,
  so the failure is invisible unless someone reads the Render log.

This feature makes the served commit visible and lets an admin pull a push
in immediately.

## What already exists

All of this is in `llmgrader/coursemcp/code.py` unless noted.

- `CodeLibrary`: one per process, on `app.course_mcp.code`
  (`coursemcp/mount.py`). It is `None` when `LLMGRADER_MCP_CODE` is unset.
  `sync_for(course_id)` returns the course's `CodeSync`, or `None` when the
  package has no `<code>`.
- `CodeSync.state()` reads `<storage>/courses/<id>/code/state.json`:
  `commit`, `synced_at`, `last_attempt`, `last_error`, `remote`, `patterns`.
  It is written atomically (temp file, then replace) at the end of each
  `_sync`, under the exclusive `.lock` file lock.
- `CodeSync.refresh_in_background()` starts a sync on a thread, or returns
  False if one is already running in this process. It does **not** check
  the time limit; only `ensure` does. So "Update now" can call it directly.
- `_fetch` already runs `git ls-remote` and skips the fetch when the remote
  head equals the mirror's head. A sync with nothing new is cheap.
- `ensure` reloads the snapshot from disk when `state.json`'s commit
  differs from the one in memory. A sync done by one worker reaches the
  others on their next MCP request.
- `run_git` times out every git call after `GIT_TIMEOUT_S` (60 s).
- `/api/admin/courses` builds one payload per course in
  `_admin_course_payload` (`routes/api.py`), and `renderManageCourses`
  (`static/js/menu.js`) draws one table row per course. The package
  version column is the precedent for the new one.
- `<code>` occurs at most once per course (`llmgrader_mcp_config.xsd`), so
  the dialog has one row per course, not one per repo.

## The constraint that shapes the design

**No admin request may wait on GitHub.** Render runs one sync gunicorn
worker, so a request that waits freezes grading for every student. This is
the same lesson as the 2026-10-06 note in `code.py`'s docstring. Every new
endpoint answers from memory or `state.json` and returns at once. Every git
call runs on a background thread, and the dialog polls.

## Design

### What a sync records

Today `state.json` is written once, at the end of a sync. Add two things.

1. **The served commit's date and subject.** At the end of a successful
   `_sync`, run `git log -1 --format=%cI%x00%s` in the mirror. It is a
   depth-1 clone, but commit objects are present; `--filter=blob:none` only
   leaves out file contents. Store the result as `committed_at` and
   `subject`. Doing this inside the sync means a request never runs git to
   draw the dialog.
2. **The stage the sync is in.** Write `progress.json` beside `state.json`,
   holding `{"stage": ..., "started_at": ..., "pid": ...}`. Write it at
   each stage boundary and delete it when the sync ends. The stages are
   `checking` (ls-remote), `fetching` (fetch, or a clone), `building`
   (`build_snapshot`) and `validating` (`validate_snapshot`). The sync's
   outcome stays in `state.json` (`last_error` and `synced_at`).

   It is a file, not memory, so a poll that reaches a different worker
   still sees the stage. It is a separate file because `state.json` is
   rewritten whole: two writers would lose each other's fields. A
   `progress.json` older than the sync's worst case (about four git
   timeouts) is reported as `stale`, since its sync died without cleaning
   up. Report it; don't delete it from a request.

### Checking the remote

Add `CodeSync.check_remote_in_background()`. It runs
`git ls-remote <remote> refs/heads/<branch>` on a thread and writes
`remote.json`: `{"head", "checked_at", "error"}`. One check at a time per
course: use a non-blocking lock, as `refresh_in_background` does. A failure
is recorded in `error`; it never raises into a request. It writes its own
file for the same reason as `progress.json`.

A successful `_sync` also writes `remote.json` with the head it just
fetched, so the dialog shows "up to date" without a second round trip.

### Endpoints

Three are new, and all require admin. Each returns within milliseconds
whatever git is doing.

| Route | Does | Returns |
|---|---|---|
| `GET /api/admin/courses` (existing) | adds a `code` object to each live course | see below |
| `GET /api/admin/courses/<id>/code` | the same `code` object, for polling | `200`, or `404` for an unknown or archived course |
| `POST /api/admin/courses/<id>/code/check` | `check_remote_in_background()` | `202 {"started": bool}` |
| `POST /api/admin/courses/<id>/code/update` | `refresh_in_background()` | `202 {"started": bool}`; `started: false` means a sync was already running |

The `code` object is built only from `state.json`, `remote.json` and
`progress.json`, plus `config.repo` and `config.branch`:

```json
{
  "enabled": true,
  "repo": "https://github.com/sdrangan/hwdesign",
  "branch": "main",
  "served": {"commit": "a1b2...", "committed_at": "2026-10-08T21:14:03-04:00",
             "subject": "Rebuild the streaming demos as build DAGs"},
  "synced_at": 1760011320.4,
  "last_attempt": 1760011320.4,
  "last_error": null,
  "remote": {"head": "9e8d...", "checked_at": 1760011500.1, "error": null},
  "progress": {"stage": "fetching", "started_at": 1760011510.0, "stale": false},
  "status": "update_available"
}
```

`status` is computed on the server, so the column and the dialog agree:

- `syncing`: there is a `progress` that is not stale;
- `error`: the last attempt failed (`last_error`), or the remote check did;
- `never_synced`: there is no served commit yet;
- `update_available`: the remote head is known and differs from the
  served commit;
- `up_to_date`: the remote head is known and equal to it;
- `unknown`: the remote has not been checked.

Two cases give a smaller object:

- **Code disabled** (`LLMGRADER_MCP_CODE` unset, `app.course_mcp.code is
  None`): `{"enabled": false}`.
- **No `<code>` in the course's package**: `null`.

`sync_for` constructs a `CodeSync` but starts nothing, so calling it from
the course list is safe. It does parse the package's
`llmgrader_mcp_config.xml` through `load_materials`. Check that this is
cached per package. If it is not, cache it, since Manage Courses would
otherwise re-parse it on every open.

### The UI (`static/js/menu.js`, `templates/index.html`)

**The column.** In `renderManageCourses`, add a cell after the package
version:

- the short served commit, in monospace like the version cell;
- a status word next to it: Up to date, Update available, Syncing…, Error,
  or Not checked;
- "—" when `code` is `null`, and "off" when `enabled` is false;
- nothing for an archived course.

Clicking the cell opens the dialog. Opening Manage Courses also fires
`/code/check` for every course that has code, then polls each course's
`/code` every second until `remote.checked_at` changes, for at most 15 s.
So the column fills in by itself.

**The dialog** (`#demo-code-modal`, styled like the other modals):

- the repo and branch, with the repo linked to GitHub;
- a **Serving** row (commit, date, subject) and an **On GitHub** row (head,
  "checked N s ago"). The commits link to `<repo>/commit/<sha>`. When they
  differ, add a compare link, `<repo>/compare/<served>...<head>`, which is
  the useful thing to click before updating;
- the last sync time and `last_error`, if any. When there is an error, add
  the note "still serving <commit>", since that is what the sync does;
- a **Check again** button (`/code/check`);
- an **Update now** button (`/code/update`), enabled only when `status` is
  `update_available` or `error`.

**Progress.** After Update now, poll `/code` every second. Show the four
stages as a row of labels, with the current one marked and the finished
ones checked, under an indeterminate progress bar. Not a percentage: a
shallow, sparse fetch of this repo takes a few seconds, and git reports
nothing that maps to a real fraction. Stop polling when `progress` is
absent:

- if `synced_at` moved past the click and `last_error` is empty, show
  "Now serving <commit>" and refresh the row;
- if `last_error` is set, show the error and "still serving <old commit>".

Give up after 3 minutes with "the sync is taking longer than expected",
and re-enable Check again.

### Several workers

A sync runs in the worker that received the click. The file locks already
keep a second worker's sync from running on top of it. The other workers
pick up the new commit on their next MCP request, through `ensure`'s
commit comparison. So the dialog's "Now serving" is true of the files on
disk at once, and of every worker after its next MCP call. Render runs one
worker, so in practice the two are the same. Say this in the docs, not in
the UI.

## Tests

**`tests/coursemcp/test_course_code.py`**, using the existing local-repo
fixture and the `run_git` / `remote_url` patches:

- a sync records `committed_at` and `subject` for the served commit;
- `progress.json` shows each stage while a patched, gated `run_git` holds
  the sync at that stage, and is gone when the sync ends, whether it
  succeeded or failed;
- `check_remote_in_background` writes `remote.json`. A second call while
  one is running starts nothing. A failing `ls-remote` is recorded, not
  raised;
- a successful sync writes `remote.json` with the head it fetched;
- an old `progress.json` with no running sync is reported as stale.

**`tests/services/test_manage_courses.py`:**

- the `code` object for a course with code, for one without (`null`), and
  with code disabled (`{"enabled": false}`); none for an archived course;
- each `status` value, from hand-written `state.json`, `remote.json` and
  `progress.json` files;
- **all four endpoints answer within a time limit while `run_git` hangs**:
  patch it to block on an event, call each endpoint, and assert it returns
  in under a second. This is the Render constraint, so it gets a test;
- `/code/update` while a sync is running returns `started: false`;
- each endpoint refuses a non-admin, and 404s an unknown course id.

**`tests/ui/test_manage_courses.py`**, following the file's existing
fixtures:

- the column shows the short commit and status word;
- clicking it opens the dialog with both rows and a compare link when they
  differ;
- Update now shows the stages, then "Now serving". Stub `/code` responses
  through Playwright route interception, so the test needs no git.

## Docs

- `docs/admin/mcp/code.md`: a section, "Checking and updating the served
  commit", covering the column, the dialog, what Update now does, and the
  several-workers note.
- `CLAUDE.md`, "Demo code in the MCP": one paragraph on the new files
  (`progress.json` and `remote.json`, and why they are separate from
  `state.json`), and the rule that admin code endpoints never wait on git.

## Out of scope

- **More than one `<code>` per course.** That needs a schema change, sync
  state keyed by course and repo, and a repo argument on the demo tools.
  The dialog's per-course rows would extend to it.
- **A GitHub push webhook** that syncs on every push. It would make Update
  now unnecessary, but it adds a public unauthenticated endpoint and a
  shared secret to manage. Revisit only if the button turns out to be
  pressed after every push.
- **Changing the 10-minute time limit**, or the lazy refresh itself.
- **Showing which files changed.** The compare link to GitHub does that
  better.

## Order of work

1. `code.py`: commit metadata, `progress.json`, `remote.json`,
   `check_remote_in_background`, and their tests.
2. `routes/api.py`: the `code` object and the three endpoints, with the
   time-limit tests.
3. `menu.js` and `index.html`: the column, then the dialog, then progress,
   with UI tests.
4. Docs and `CLAUDE.md`.
5. Run the fast suite and the UI suite. Then run the demo-code tests
   against GitHub (`LLMGRADER_RUN_NETWORK_TESTS=1`), since this touches
   the sync.
