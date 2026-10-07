---
title: Deploying the Course MCP
parent: Course MCP
nav_order: 3
has_children: false
---

# Deploying the Course MCP

The course MCP runs inside the portal you have already
[deployed on Render](../deploy/render.md). There is no second service, disk or
start command: it is switched on with environment variables.

---

## Step 1: Decide whether to require a token

The MCP serves your questions, rubrics, **worked solutions** and slides. Turning
it on publishes them to anyone with the address.

- **No token (the default).** Students need nothing but the address, so you can
  put it on the course web page. Choose this when the problems are study
  material and you do not mind their solutions being readable by anyone, now
  and in later semesters.
- **Token** (`LLMGRADER_MCP_TOKEN`). Every request must carry a secret you give
  students. Choose this when you reuse problems and want to change the key
  each semester. The cost is that every student has to find and paste it.

For a token, generate a long random value:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep it somewhere safe; you will post it for students in step 5.

---

## Step 2: Set the environment variables

In the Render dashboard, open your portal's web service, go to
**Environment**, and add:

| Variable | Value | Remarks |
| --- | --- | --- |
| `LLMGRADER_MCP_ENABLED` | `1` | Serves the course MCP at `/mcp`. Off when unset. |
| `LLMGRADER_MCP_TOKEN` | the token from step 1 | **Optional.** When set, required on every MCP request. Unset, the MCP is open. |

Save. Render redeploys the service. When it starts, the deploy log shows one of:

```text
[CourseMCP] Serving the course MCP at /mcp
```

or, if the MCP could not start:

```text
[CourseMCP] Not mounted, portal continues without /mcp: <the error>
```

In the second case **the portal is unaffected** -- students can still answer and
grade questions -- and only `/mcp` is missing. Report the error.

**To switch later**, add or delete `LLMGRADER_MCP_TOKEN`. Adding one means every
student has to update their connector, so announce it.

**To turn the MCP off**, delete `LLMGRADER_MCP_ENABLED`. Without it, the portal
does not load the MCP code at all.

---

## Step 3: Load the course material

Nothing separate: the MCP serves the course packages the portal already has.
[Upload the course package](../buildcourse/upload.md) as usual -- built with
slides if you followed [Packaging](./package.md) -- and the MCP serves it as
soon as the upload finishes.

---

## Step 4: Check that it works

### In a browser

Open `https://<portal>/mcp`. A browser cannot speak the protocol, so the MCP
answers every browser visit with a short plain-text page (HTTP 405, *Method Not
Allowed* -- the MCP only accepts POST). It needs no token. What the page says
tells you whether the MCP is up:

| You see | Meaning |
| --- | --- |
| *"This is the course MCP server, and it is running."* | **Working.** The MCP answered. |
| An HTML page saying **Not Found** | **Not mounted.** The portal answered instead: `LLMGRADER_MCP_ENABLED` is not set, the redeploy after setting it has not finished, or the mount failed. Check the deploy log for a `[CourseMCP]` line. |

### From the command line

The MCP answers a single HTTP request, so `curl` is enough. Replace
`<portal>` and `<token>`:

```bash
curl -s -X POST https://<portal>/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer <token>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

A working server replies with JSON listing its tools: `list_courses`,
`list_units`, `list_questions`, `get_question`, `get_rubric`, `get_solution`,
`list_materials`, `get_outline`, `search_slides` and `get_slide`.

| Reply | Meaning |
| --- | --- |
| HTTP 403, *"This course MCP needs the course access token"* | The token is missing or does not match `LLMGRADER_MCP_TOKEN`. |
| HTTP 404 | `LLMGRADER_MCP_ENABLED` is not set, or the mount failed; check the deploy log. |

### With an assistant

Connect it as a student would, following
[Studying with Your Own AI](../../student/mcp.md), and try the questions on
that page -- "List the problems in unit 2", "Where is this described in the
class slides?". Do this from claude.ai at least once: it is the path most
students will use, and it reaches your portal from Anthropic's servers rather
than from your own machine.

### With the MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a
browser page for calling an MCP server's tools by hand. With Node.js installed:

```bash
npx @modelcontextprotocol/inspector
```

Set **Transport** to *Streamable HTTP* and **URL** to `https://<portal>/mcp`;
under **Authentication**, set the header `Authorization` to `Bearer <token>`.
Click **Connect**, then run tools from the **Tools** tab.

---

## Step 5: Tell students

**No token:** post the address, `https://<portal>/mcp`, anywhere -- the course
web page, the syllabus, the LMS.

**Token:** post the address and the token where only your students can see
them -- the LMS, not a public page. Posting the single address
`https://<portal>/mcp/<token>` saves them a step: it carries the token and
needs no header.

and point them to [Studying with Your Own AI](../../student/mcp.md), which walks
through connecting Claude, VS Code or Claude Code.

**Changing the token** -- if it leaks, or each semester -- is a new value in
`LLMGRADER_MCP_TOKEN`. Every student then has to update their connector, so
announce it.

---

## What is recorded

Every MCP request is recorded as one row in its own database,
`<storage>/db/mcp_usage.db`, beside the grading database and separate from it.
Read it in **Analytics ▸ MCP DB** ([MCP usage](../../analytics/mcp_usage.md)).

**Recorded:**

- when, which tool, and whether it succeeded, failed or was refused;
- the course, unit, question, deck and slide asked about -- as the tool
  resolved them, so *"unit 2"* is recorded as the unit's real name;
- how big the answer was: its size in bytes, how many items a list held, how
  many images it carried;
- which kind of assistant made the call -- `claude.ai`, `vscode`,
  `claude-code` or `other` -- and the MCP protocol version;
- an anonymous session id, so calls from one chat can be grouped (below);
- the version of the course package that answered (see
  [package versions](./package.md#package-versions)).

**Never recorded:**

- **the student's words.** A slide search is recorded with its query replaced
  by `<redacted>`; it is the only tool that takes free text.
- **who the student is.** No name, email, IP address or browser string. The
  MCP has no sign-in, so there is no identity to record; with a course token
  set, every student sends the same token, and it is not recorded either.
- **the answer itself.** Only its size: a slide image or a worked solution
  would grow the file by megabytes, and the package version already says what
  it was.

**Sessions.** Assistants on the 2025 protocol open a connection with a
handshake, and the server gives that connection a random id, which the
assistant sends back with each call. The id lasts one connection -- roughly
one chat -- and is linked to nothing else. Assistants on the 2026 protocol
have no handshake; their calls are grouped into sessions when you query, by
assistant kind and a gap of more than 10 minutes. That can merge two students
using the same assistant at the same time.

Recording never fails a student's call: if the row cannot be written, the
student still gets the answer and the server logs `[McpUsage] Dropped a usage
row`. Rows are kept until you delete them, with **Analytics ▸ Delete Usage
Before…** (MCP DB only). Grades are never touched by it.

---

## Notes for operators

- **What is logged.** Besides the usage database, one log line per tool call:
  the tool, the course, and the unit, question, deck or slide asked about --
  never the student's words. A slide search logs its course and unit, not its
  query.
- **`/mcp` is not behind Google sign-in.** MCP requests go to the MCP directly,
  not through the portal's login; the token is what protects it.
- **A bad token gets 403, not 401.** A 401 would make claude.ai start an OAuth
  sign-in this server does not offer, and the student would see a broken
  sign-in page instead of the message.
- **The MCP starts on its first request, not at boot.** It runs on a
  background thread, and a thread does not survive gunicorn forking a worker,
  so it is started inside whichever worker serves the first `/mcp` request.
  The deploy log then shows `[CourseMCP] Started in process <pid>`, once per
  worker. This is why `--preload` and gunicorn's own app loading are both
  safe.
- **Only POST reaches the MCP.** Anything else gets the plain-text *"course MCP
  server ... is running"* page. A long-lived stream -- an MCP GET stream, or a
  `subscriptions/listen` request -- would hold one of gunicorn's sync workers
  for as long as it stayed open, so the MCP offers neither.
- **Capacity.** MCP calls are fast lookups, but they share the portal's
  gunicorn workers with grading. Render's default start command,
  `gunicorn run:app`, runs one worker. TBD: whether to recommend
  `gunicorn run:app --workers 2 --threads 4` once the MCP has real traffic.
