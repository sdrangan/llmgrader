# Plan: demo code and demo docs in the course MCP

**Status: phases 1 and 2 built on `feature/demo-code-mcp` (2026-10-08).
Phase 3 (content and rollout) is the instructor's; phase 4 is not started.**

Where the build departs from the text below:

- **The clone fills the tree with `reset --hard HEAD`**, not `checkout`:
  after a `--no-checkout` clone, `git checkout <branch>` is a no-op when the
  branch is already current, and leaves the sparse tree empty.
- **The kill switch is read in `mount.py`** (`code_enabled()`), beside the
  token, rather than passed from `app.py`. Without it the demo tools are not
  registered at all, and nothing is cloned.
- **The GitHub clone test is in `tests/coursemcp/test_demo_links.py`**, gated
  by `LLMGRADER_RUN_NETWORK_TESTS=1`, not in `tests/live`: that suite's
  `live` marker and conftest are for paid OpenAI calls.
- **The overrides file cannot rename a demo**, only retitle it; an id is what
  `--links` shows. A docs page's cited code is returned as `cites`.
- **`docs/demos/setup/` becomes a demo** with no code, since it is a docs topic
  folder. `<hide id="setup"/>` removes it.
- **`create_soln_pkg` runs the link report only when `<code root=...>`**
  names a local checkout.

Revision 2 makes three changes:

- The docs walkthroughs (`docs/demos/`) are served alongside the code.
- What a demo is, and which slides, units and docs go with it, is now
  **derived from the links that already exist** in slides and docs, instead
  of a hand-written index.
- `<code>` takes include/exclude patterns.

Let a student's assistant find and read the in-class demos -- SystemVerilog,
Vitis HLS C++ and Tcl, Python build scripts, notebooks -- and the docs pages
that walk through them, the same way it already reads slides and questions.
Four read-only tools on the existing course MCP, served from a copy of the
public `sdrangan/hwdesign` repo that the portal keeps in sync with GitHub.

```
"How do I give an HLS kernel AXI4-Lite registers?"
  search_demos(course_id, "s_axilite")
    -> code  demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp  lines 12-16
             source_url  https://github.com/sdrangan/hwdesign/blob/<sha>/demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp#L12-L16
    -> doc   docs/demos/procif/vitis_ip.md  "Building the Vitis IP"
             view_url    https://sdrangan.github.io/hwdesign/docs/demos/procif/vitis_ip#...
  list_demos -> procif: "Bus Basics and Memory-Mapped Interfaces"
                docs: docs/demos/procif/ (11 pages)   code: demos/scalar_fun/...
                slides: procif 50 (cites demos/scalar_fun/scalar_fun_vitis)  unit: Unit 4
```

## Motivation

A lot of what the course teaches is only in the demos and their docs. The
slides never show how to put AXI4-Lite registers on an HLS kernel;
`scalar_fun.cpp` lines 12-16 do, and `docs/demos/procif/vitis_ip.md` explains
them. When a student asks "where is X covered?" or "how do I do X", the
assistant cannot answer from slides alone. It cannot read GitHub itself either:
a claude.ai chat has no shell, and GitHub blocks its web fetch.

## What already exists

**In llmgrader:**

| Need | Already in the tree |
| --- | --- |
| Per-course MCP config, validated, carried in the package | `llmgrader_mcp_config.xml` + `llmgrader_mcp_config.xsd`; parsed in `materials.py` and written to `mcp_materials/manifest.json` |
| A root pointing at the public repo | `<root id="pub" path="../hwdesign"/>` in hwdesign-soln's config, used by the build |
| Every slide's text, notes and figure description | `mcp_materials/slides/<deck>/deck.json`; a slide's deck gives its unit (`unit=` on `<deck>`) |
| Course id check, ToolError wording | `require_course` in `coursemcp/server.py` |
| Slide links | `slide_url()` in `server.py` (`/c/<course>/slides/<deck>/<n>`) |
| Starting threads lazily per process, safe across fork | `CourseMCPRunner` in `mount.py` (pid check) |
| Usage rows, arguments either kept or redacted | `coursemcp/usage.py`, `services/mcp_usage.py` (`ALTER TABLE ... ADD COLUMN` is already idempotent) |
| Persistent disk on Render | `/var/data` = `LLMGRADER_STORAGE_PATH`, already mounted |
| Per-course storage directory | `<storage>/courses/<course_id>/` (registry layout) |

**In hwdesign:**

- `demos/`: 108 tracked files, about 40 MB. 38.5 MB of that is two bitstreams
  and their `.hwh` files.
- `docs/demos/`: 44 Markdown pages in 9 topic folders (`procif`, `stream`,
  `fifoif`, `fixp`, `datatypes`, `simp_fun`, `loopopt`, `setup`, plus the
  index). Each has just-the-docs front matter (`title`, `parent`,
  `nav_order`, `has_children`).
- The docs are published by GitHub Pages under `url` + `baseurl` from
  `_config.yml`. Checked: `docs/demos/procif/vitis_ip.md` is served at
  `https://sdrangan.github.io/hwdesign/docs/demos/procif/vitis_ip` (with or
  without `.html`), and `index.md` at its folder, `.../procif/`.

The servable text, code plus docs with notebook outputs stripped, is well
under 1 MB. That size decides most of the design below.

## Design decisions

### 1. File tools, held in memory. No embeddings, no ripgrep

Questions about code depend on exact identifiers, which embeddings blur. Each
course gets one immutable in-memory snapshot of its servable files, and a
case-insensitive scan of every line takes a few milliseconds in Python.
ripgrep buys nothing at this size. It would also cost something: Render's
native Python runtime has no `apt-get`, so we'd have to download a binary in
the build.

### 2. Repo, subtrees and filters are named in `llmgrader_mcp_config.xml`

Not `llmgrader_config.xml`, which is the grading config. The MCP config
already holds the slides, the exam units and the `pub` root, and the build
turns it into the package's MCP material. The registry serves several courses,
each possibly with its own repo, so this can't be a portal-wide env var.

```xml
<code repo="https://github.com/sdrangan/hwdesign" branch="main">
  <include path="demos"/>
  <include path="docs/demos" kind="doc"/>
  <exclude>*.wcfg</exclude>
  <exclude>demos/project/**</exclude>
</code>
```

- `repo` must match `https://github.com/<owner>/<repo>` (an XSD pattern).
  Source links are built from it, and the pattern stops a package from
  pointing the server at an arbitrary host.
- `<include>` lists the only subtrees that are fetched or served. `kind`
  is `code` (the default) or `doc`. Nothing else in the repo is reachable,
  including `units/`, `labs/` and `gradescope/`.
- `<exclude>` takes globs relative to the repo root. These are *added* to
  the built-in rules (decision 5), never instead of them.
- `site` is optional, and gives the docs' published address. When it's
  absent it's read from `url` + `baseurl` in the repo's `_config.yml`, which
  gives `https://sdrangan.github.io/hwdesign` here, so hwdesign needs no
  attribute.
- `links` is optional, and names the overrides file (decision 3). The default
  is `demos/demos.xml`, used only if that file exists.

The build copies the element into `manifest.json` (additive, so
`FORMAT_VERSION` stays 1). Turning this on takes one rebuild and upload, which
the midterm already needs. **After that, edits to demos or docs need no
rebuild:** the copy follows GitHub. Only the pointer is packaged, never the
content.

### 3. Demos and their links are derived, not written by hand

**Two layers.** The server stores the repo in its GitHub layout, unchanged:
nothing is copied, renamed or reorganized, and every tool takes and returns
original repo paths. On top of that sits an **index**, held in memory and
rebuilt at each sync, that records which docs pages, code directories,
slides and units go with each demo, which code each docs page cites, and the
reverse links. The index is never written back into the tree, so fixing a
link in a slide or a docs page is all it takes to change it.

**Decided: a demo is a docs topic folder** (`procif`, not `scalar_fun`), with
the code it cites attached. It matches how the course teaches the demos, and
it carries a real title and description. Code that no docs page cites becomes
a code-only demo named after its directory. Both docs and code are served
either way; this only decides what one `list_demos` entry is.

Revision 1 had a hand-written `demos/demos.xml` index. It isn't needed,
because the slides and docs already say what goes with what. Every sync builds
a **link graph** from three sources.

**References found in text.** In every slide (title, text, notes, figure
description, and, new, hyperlink targets: see below) and every docs page, the
server looks for:

- `demos/<path>` and `hwdesign/demos/<path>`, which is how the docs write
  "the files are in `hwdesign/demos/stream/avgfilt`";
- `github.com/sdrangan/hwdesign/(blob|tree)/<ref>/<path>`;
- `<site>/<docs path>`, a link to a published docs page, e.g.
  `sdrangan.github.io/hwdesign/docs/demos/procif/`;
- relative Markdown links between docs pages, e.g. `[scalar function
  example](../procif/)`.

Each reference is resolved against the snapshot. A reference to a file brings
in the directory that holds it, since citing `demos/pipeline/pipeline_demo.ipynb`
means the pipeline demo. A reference that resolves to nothing, or only to
excluded build output, is recorded as **broken**.

**What a demo is:**

- **A documented demo** is a docs topic folder, `docs/demos/<topic>/`. Its
  id is `<topic>`, and its title and description come from the front matter
  `title` and the first paragraph of `index.md`. Its code is every code
  directory its pages cite. A code directory under `demos/` with the same name
  as the topic is included too, because the repo is organised that way.
- **A code-only demo** is a top-level `demos/<dir>` that no documented demo
  includes. Its id is `<dir>`. Its description comes from a README in it if
  there is one, and otherwise is empty until the overrides file supplies one.
- **Units and slides** come from slides that cite the demo, directly or
  through one of its docs pages. Each such slide links the demo to that slide,
  and through the slide's deck, to the deck's unit. A deck whose id equals the
  demo's id or code directory name (`fixp`, `procif`, `loopopt`, `sharedmem`)
  also links its unit, with no particular slide. Every link records how it was
  found (`"via": "slide fifo:28 cites demos/stream/avgfilt"`), so a wrong
  automatic link can be traced and overridden.
- **Related demos** come from docs pages linking to other topics
  (`stream` → `procif`).

**This is what the rules give on today's repo** (prototyped against the
local checkout and the locally built slides):

| Demo | Docs | Code | Slides citing it | Unit from |
| --- | --- | --- | --- | --- |
| `procif` | 11 pages | `demos/scalar_fun/**` | procif 50 | slide; deck name |
| `stream` | 8 pages | `demos/stream/avgfilt` | fifo 28 | slide |
| `fifoif` | 10 pages | `demos/stream/poly`, `demos/fifoif` (name) | fifo 55 | slide |
| `fixp` | 3 pages | `demos/fixp` | -- | deck name |
| `loopopt` | 2 pages | `demos/pipeline` (via the notebook) | -- | deck name |
| `datatypes` | 5 pages | `demos/datatypes` | -- | **none** |
| `simp_fun` | 4 pages | `demos/simp_fun` | -- | **none** |
| `fsm` | -- | `demos/fsm` | fsm 35 | slide |
| `sharedmem` | -- | `demos/sharedmem` | -- | deck name |
| `conv2d`, `histogram`, `vector_mult`, `project` | -- | their directory | -- | **none** |

Broken references it finds:

- `docs/demos/simp_fun/poly.md` cites `demos/basic_logic/poly_fun.sv` and
  `demos/basic_logic/timing_diag.ipynb`, and `simp_fun/simulation.md` cites the
  notebook again. `demos/basic_logic/` no longer exists; these look like
  `demos/simp_fun/`.
- `docs/demos/procif/add_ip.md` cites `.../hls_component/simp_fun/hls/impl/ip`.
  That's build output, which is correct in the docs (it's where Vitis writes
  the IP) but isn't served. Recorded as "build output", not broken.

The slide links are sparse: only 4 slides cite code, and several only show
the bare `sdrangan.github.io/hwdesign`, which links to nothing in particular.
So automatic linking places 7 of the 13 demos in a unit, and the rest need
the overrides file. Adding a deep link to a slide fixes the gap at the source,
and is better than an override.

**Overrides file: `demos/demos.xml` in hwdesign, optional and sparse.** It
only says what the links can't. It lives in hwdesign, not hwdesign-soln, so
changing it needs no rebuild.

```xml
<demos>
  <!-- Fill in what no slide or docs page says. -->
  <demo id="datatypes"><slides deck="basic-logic" first="20" last="31"/></demo>
  <demo id="simp_fun"><unit>Unit 1:  Data Types and Combinational Logic</unit></demo>
  <demo id="vector_mult" title="Vector multiply with loop unrolling">
    <description>...</description>
    <slides deck="unroll"/>
  </demo>
  <!-- Correct a wrong automatic link. -->
  <demo id="sharedmem"><not_slides deck="sharedmem"/></demo>
  <!-- Leave a directory out of the demo list (still searchable as code). -->
  <hide id="project"/>
</demos>
```

What it can do: add slides or units, remove an automatic link, set title and
description, rename a code-only demo, and hide one. The schema is
`llmgrader/schemas/llmgrader_demos.xsd`, so errors come with line numbers.
Override ids are checked against the derived demos, so a typo is reported
rather than ignored.

**A link report, at build time and on the server.** `llmgrader_mcp_build
links` (also run by `create_soln_pkg`) builds the same graph from the local
`pub` checkout and the slides it has just extracted, and prints:

- the table above;
- every broken reference, with file and line;
- demos with no unit;
- code-only demos with no description;
- override ids that match no demo.

This doubles as a link checker for the course materials. The server builds
the same graph at each sync and logs the same warnings.

**Slide hyperlinks.** The slide build reads only visible text today, so a
"see the demo" whose URL is a PowerPoint hyperlink is invisible to all of
this. `materials.py` will also collect each run's `hyperlink.address` and the
slide's click actions into a `links` list in `deck.json`. That's a few lines
of python-pptx, and the link extractor reads the list. It also helps
`search_slides`. Old packages without `links` still work.

**Where the graph is computed.** On the server, at sync time, from the
snapshot (code + docs) and the course's loaded slide material. A package
upload also rebuilds it, since the slides may have changed. Both inputs are
local, so this is milliseconds and never touches the network.

### 4. Sync: a git mirror on disk, an immutable snapshot in memory

```
<storage>/courses/<course_id>/code/
  mirror/        # shallow, sparse, partial git clone of the <include> paths only
  state.json     # {"commit", "synced_at", "last_error", "last_attempt"}
```

**First clone** (all commands use `GIT_TERMINAL_PROMPT=0` and a 60 s
subprocess timeout, so a renamed or now-private repo fails fast instead of
waiting for a password):

```
git clone --depth 1 --filter=blob:none --no-checkout --branch main <repo> mirror.new
git -C mirror.new sparse-checkout set --no-cone '/demos/' '/docs/demos/' '/_config.yml' '!*.bit' '!*.hwh' '!*.xsa'
git -C mirror.new checkout
mv mirror.new mirror
```

The sparse patterns come from `<include>` (plus `_config.yml` when `site` is
not given). With `--filter=blob:none`, git only downloads blobs it checks
out, so the 38 MB of bitstreams are never fetched. Docs images are skipped in
v1, so the patterns also exclude `*.png *.jpg *.gif *.svg` under docs.

**Refresh:**

```
git -C mirror ls-remote origin refs/heads/main      # one round trip, no API rate limit
  same sha as state.json -> touch synced_at, done
git -C mirror fetch --depth 1 --filter=blob:none origin main
git -C mirror reset --hard FETCH_HEAD
```

Fetch and `reset --hard`, never `pull`, so there can't be a merge conflict.
`ls-remote` first means that when nothing changed, the check costs one small
request. I chose it over the GitHub REST API because unauthenticated API calls
are limited to 60 an hour per IP, and Render's egress IPs are shared.

**Snapshot.** After a successful reset, the syncer walks the include paths
and builds a `CodeSnapshot`, then swaps `self.snapshot = new` in a single
assignment. The snapshot holds:

- the commit;
- a dict of `repo path -> (kind, language, tuple of lines, title)`, with
  every exclusion rule applied;
- the link graph (decision 3).

**Locking.** Tools never read the mirror. They read only `self.snapshot`, which
is never changed after it's built. So a reader can't see a half-updated tree,
and readers take no lock at all. There is one `threading.Lock` per course,
taken with `acquire(blocking=False)` by the syncer, so a second request to
sync while one is running is dropped. With more than one gunicorn worker, an
`fcntl.flock` on `code/.lock` also guards the mirror (skipped on Windows,
where the dev server is one process).

**Nothing a student waits on touches GitHub.** This is the rule from the
2026-10-06 outages: one sync worker means a request that waits freezes the
whole portal.

- `create_app` and `run.py` do nothing over the network. A sync at import
  time would run in gunicorn's master before the fork, which is the trap
  `mount.py` documents, and it would hold up boot whenever GitHub is slow.
- The first code tool call in a process loads the snapshot **from the
  mirror on disk**. That's local and takes milliseconds. If `synced_at` is
  older than the TTL (default 600 s, `LLMGRADER_CODE_SYNC_TTL_S`), the call
  also starts a background refresh thread and returns at once using the copy
  it has. Same lazy, per-pid start as `mount.py`.
- Any `/mcp` request does the same staleness check, `list_courses` included,
  so a session starting up warms the copy.
- **First deploy, no mirror at all:** the call starts the clone, waits at
  most 5 s for it, and then returns a ToolError: *"The demos are being
  fetched for the first time; try again in a minute."* This is the only case
  where a tool call waits, and the wait is bounded.

**Failures. The rule is to serve the last good copy:**

| Failure | Behaviour |
| --- | --- |
| GitHub unreachable, timeout, 5xx | Keep the current snapshot; log `[CourseCode] sync failed: ...`; record `last_error`; try again after the next TTL, not on every call |
| Repo renamed / made private | Same. `GIT_TERMINAL_PROMPT=0` makes it fail fast, not hang |
| Mirror corrupt (reset or fetch fails with a git error) | Re-clone into `mirror.new` and rename it into place. The old snapshot is served while that runs |
| New commit breaks `demos/demos.xml`, or leaves zero servable files | Refuse the snapshot and keep the old one, so a bad push can't empty the tools; log the error with its line |
| Broken references in slides or docs | Not a failure: logged in the link report, and the snapshot is used |
| Process restart while GitHub is down | Snapshot is rebuilt from the mirror on disk; no network needed |
| git missing on the host | Demo tools return a ToolError; the rest of the MCP is unaffected (see Render) |

**Freshness is visible.** `list_courses` gains `code_version` (the short
commit) next to `package_version`. As now, the version appears there and in
no other tool's result.

**Webhook: optional, later.** A 10-minute delay is fine for teaching. If it
turns out to be annoying, add `POST /api/code_hooks/github/<course_id>`. It
would check `X-Hub-Signature-256` against `LLMGRADER_CODE_WEBHOOK_SECRET`,
ignore anything other than a push to the configured branch, start a
background sync, and return **202 immediately**. GitHub gives up after 10 s,
and the single worker must not wait on a fetch. Lowering the TTL to 2 minutes
is the cheaper alternative.

### 5. What is served: an allowlist, not a denylist

**Code** (`kind="code"` includes). A file is served only if all of these
hold:

- Its extension is on the list: `.sv .svh .v .vh .vhd .cpp .cc .c .h .hpp .py
  .tcl .ipynb .md .txt .xdc .mk .template`, or the name is `Makefile`.
- No path component is build output: `hls_component`, `.Xil`, `__pycache__`,
  `logs`, `results`, `*_proj`, `*.runs`, `*.gen`, `*.sim`, `*.cache`,
  `_build*`, `.ipynb_checkpoints`.
- It isn't Vivado-generated Tcl. That means the first 10 lines contain
  `Generated by Vivado` or start `namespace eval ::optrace`. Three tracked
  files match today: the two `overlay/*.tcl` and `project_recreate.tcl`.
- It's at most 256 KB after notebook stripping, decodes as UTF-8, and has no
  NUL byte.
- It isn't a symlink. The repo is public and anyone with push access could
  commit a link to `/etc/passwd`, so symlinks are skipped while the snapshot is
  built.
- It doesn't match an `<exclude>`.

**Notebooks** are flattened to text, with outputs removed:

```
# ---- cell 3 [markdown] ----
...
# ---- cell 4 [code] ----
ol = Overlay("scalar_fun.bit")
```

Line numbers refer to this flattened text. GitHub has no line anchors in a
rendered notebook, so a notebook's `source_url` points to the file, not to
lines.

**Docs** (`kind="doc"` includes): `.md` files only, with the same size,
UTF-8 and symlink rules.

- **Front matter** is parsed (`title`, `parent`, `nav_order`) and removed
  from the served text. The line numbers still refer to the file on GitHub,
  so they start after the front matter, not at 1.
- **Images** aren't served in v1. Their alt text and file name stay in the
  text, so the assistant knows a figure is there and the student can open
  `view_url` to see it. Serving them as image blocks, like `get_slide`, is
  question 6.
- **kramdown attribute lines** (`{: .note }`) and Liquid tags are left as
  they are. They're rare and harmless.

### 6. Two links per result: where to read it, and the exact source

- **Code:** `source_url` =
  `https://github.com/sdrangan/hwdesign/blob/<sha>/<path>#L12-L16`. It's
  pinned to the snapshot's commit, because our line numbers come from that
  commit. Once `main` moves on, a `blob/main` link points at different lines.
  On GitHub's file view, one click goes to the latest version.
- **Docs:** `view_url` = the published page,
  `https://sdrangan.github.io/hwdesign/docs/demos/procif/vitis_ip`. For a
  search hit, the URL adds `#<heading id>` for the nearest heading above the
  hit, using kramdown's id rules. That anchor is best effort; if it doesn't
  match, the browser just opens the page. `source_url` is also given, with
  `?plain=1#L..`, for the exact lines. Pages follows `main`, so `view_url` can
  run a few minutes ahead of the snapshot. That's fine for reading prose.
- **Slides** in demo results carry the existing portal `view_url`
  (`/c/<course>/slides/<deck>/<n>`).

### 7. Search is literal; no regex in v1

Python's `re` has no timeout, so a pattern like `(a+)+$` from a model can
backtrack for minutes and take the single sync worker with it. So search is
a case-insensitive substring match, with runs of whitespace collapsed so
`pragma HLS  interface` still matches. That's enough for `s_axilite`,
`ap_ctrl_none` and `always_ff`, and for phrases in the docs. When a search
misses, the assistant tries again with other words.

Results come in a fixed order, nothing is ranked:

1. docs pages first, since they explain;
2. then source files (`.sv .cpp .h .tcl`), then scripts, then notebooks;
3. within each, by demo, path and line.

Matching lines within 3 lines of each other in the same file merge into
**one hit with a line range**, so the five pragma lines come back as one hit,
`lines 12-16`.

### 8. Path safety by construction

`get_demo_file` never opens a file. It looks the path up in the snapshot's
dict. Paths are **repo-relative** (`demos/...`, `docs/demos/...`), because a
documented demo spans both trees. The requested path is normalized first:
backslashes become `/`, `.` segments are dropped, and the result is rejected
if it is absolute, has a drive letter, or still has a `..` segment. A path
that isn't a key doesn't exist as far as the tool is concerned. That covers
`../` escapes, absolute paths, symlinks, bitstreams, build output and
anything outside the `<include>` paths alike, and the same check works on
Linux and on Windows.

## Tool signatures and results

All four tools take `course_id` from `list_courses`. Errors are ToolErrors
that list the valid choices, in the same wording as `require_deck`. Each call
logs one `[CourseMCP]` line with ids only, never the query. A course with no
`<code>` answers *"This course has not published demos."*

The names follow `list_materials` / `get_slide` / `search_slides`. A bare
`read_file` would get mixed up with a filesystem MCP or Claude Code's own
`Read` in the same client.

### `list_demos(course_id, unit=None) -> list[dict]`

```json
[{
  "demo": "procif",
  "title": "Bus Basics and Memory-Mapped Interfaces",
  "description": "Design a Vitis HLS IP with an AXI4-Lite memory-mapped interface ...",
  "units": [{"unit": "Unit 4:  Memory and Processor Interfaces",
             "via": "slide procif:50 cites demos/scalar_fun/scalar_fun_vitis"}],
  "slides": [{"deck": "procif", "slide": 50,
              "view_url": "https://<portal>/c/hwdesign/slides/procif/50"}],
  "docs": [{"path": "docs/demos/procif/index.md", "title": "Bus Basics and Memory-Mapped Interfaces",
            "view_url": "https://sdrangan.github.io/hwdesign/docs/demos/procif/"},
           {"path": "docs/demos/procif/vitis_ip.md", "title": "Building the Vitis IP", "view_url": "..."}],
  "code": ["demos/scalar_fun/scalar_fun_vitis", "demos/scalar_fun/scalar_fun_pynqz2",
           "demos/scalar_fun/notebooks"],
  "related": ["stream"],
  "files": 20
}]
```

- `unit` is resolved with `resolve_unit` and filters to the demos linked to
  that unit.
- `docs` follow `nav_order`.
- Hidden demos are left out.
- The docstring says to use it to point a student to a demo, or to find the
  demo that goes with a slide or unit.

### `list_demo_files(course_id, demo) -> list[dict]`

```json
[{"path": "docs/demos/procif/vitis_ip.md", "kind": "doc", "title": "Building the Vitis IP",
  "lines": 142, "view_url": "https://sdrangan.github.io/hwdesign/docs/demos/procif/vitis_ip"},
 {"path": "demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp", "kind": "code",
  "language": "hls-cpp", "lines": 23, "bytes": 812,
  "source_url": "https://github.com/sdrangan/hwdesign/blob/<sha>/demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp"}]
```

- Docs pages come first, in `nav_order`, then code by path.
- `language` is one of `systemverilog`, `verilog`, `vhdl`, `hls-cpp` (a
  `.cpp/.h` containing `#pragma HLS`), `cpp`, `tcl`, `python`, `notebook`,
  `markdown`, `text`.
- The docstring says build output, bitstreams and generated Tcl are not
  served.

### `get_demo_file(course_id, path, start_line=None, end_line=None) -> dict`

```json
{
  "path": "demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp", "kind": "code",
  "language": "hls-cpp", "demos": ["procif"],
  "lines": 23, "start_line": 1, "end_line": 23, "truncated": false,
  "text": "   1  #include \"scalar_fun.h\"\n ... \n  12      #pragma HLS INTERFACE s_axilite port=x      bundle=CTRL\n ...",
  "source_url": "https://github.com/sdrangan/hwdesign/blob/<sha>/demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp#L1-L23"
}
```

- `demo` isn't an argument, because a repo path is unique. `demos` in the
  result says which demos the file belongs to (a file can belong to several).
- A docs page also has `title` and `view_url`, and its `related` lists the
  code it cites, resolved, so the assistant can go from a walkthrough straight
  to the file.
- At most **400 lines per call**. When the file is cut off, `truncated` is
  true and the docstring says to call again with `start_line = end_line + 1`.
- Out-of-range lines are clamped. `start_line > lines` is a ToolError giving
  the length.
- A leading `hwdesign/` is stripped, because that's how the docs write
  paths.

### `search_demos(course_id, query, demo=None, kind=None) -> dict`

```json
{
  "matched_lines": 9, "hits_shown": 3, "more": 0,
  "hits": [
    {"path": "docs/demos/procif/vitis_ip.md", "kind": "doc", "demos": ["procif"],
     "title": "Building the Vitis IP", "heading": "Interface pragmas",
     "start_line": 41, "end_line": 41, "context": "...",
     "view_url": "https://sdrangan.github.io/hwdesign/docs/demos/procif/vitis_ip#interface-pragmas",
     "source_url": "https://github.com/.../blob/<sha>/docs/demos/procif/vitis_ip.md?plain=1#L41"},
    {"path": "demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp", "kind": "code",
     "demos": ["procif"], "language": "hls-cpp", "start_line": 12, "end_line": 16,
     "context": "  10  void simp_fun(int x, int w, int b, int& y) {\n  11  \n> 12      #pragma HLS INTERFACE s_axilite port=x      bundle=CTRL\n ...\n> 16      #pragma HLS INTERFACE s_axilite port=return bundle=CTRL\n  17  \n  18      int act_in = w * x + b;",
     "source_url": "https://github.com/.../blob/<sha>/demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp#L12-L16"}
  ]
}
```

- `demo` scopes the search to one demo's docs and code. `kind` is `"code"`
  or `"doc"`.
- At most 25 hits, at most 4 hits per file, 2 lines of context, and each
  context line cut to 200 chars. `more` counts the hits that were dropped, and
  the docstring says to narrow with `demo=` or `kind=`. The result is a dict,
  not a list, so that `more` can be reported. `usage.py` counts `hits` as
  `result_items`.
- Links cover the matched lines, not the context.

### Slide results gain their demos

`get_slide` and `search_slides` hits gain
`"demos": [{"demo": "procif", "title": "..."}]` whenever the link graph ties
a demo to that slide. It's free once the graph exists, and it's the reverse
path: from "the slide that mentions the demo" to the demo itself.

### Server instructions

Add after the slides sentence of `CONTENT_INSTRUCTIONS`:

> Demos: the instructor's in-class demos -- SystemVerilog, Vitis HLS C++ and
> Tcl, Python build scripts and notebooks -- and the docs pages that walk
> through them often show what the slides only describe. When a student asks
> where something is shown or how to do it (a pragma, an interface, a
> testbench, a build step), search_demos for its exact identifiers or a
> phrase, then get_demo_file to read the docs page or the code; list_demos
> says which unit and slides each demo goes with, so you can point the student
> to a demo to study. Give the student view_url for a docs page and source_url
> for exact lines of code, and cite code as path:line.

The last sentence of the current text becomes *"...which tools are called
and on which questions, slides and demo files..."*.

## Usage counting

- `IDENTIFIER_ARGUMENTS` gains `demo`, `path`, `kind`, `start_line` and
  `end_line`. `query` stays in `REDACTED_ARGUMENTS`: like a slide search,
  it's an assistant's paraphrase of what the student asked. The existing test
  that every tool argument is listed (`test_mcp_usage.py:184`) will catch
  anything missed.
- `mcp_calls` gains `demo TEXT`, `path TEXT` and `code_version TEXT` in
  `COLUMNS`. The existing `ALTER TABLE` loop adds them on boot, and no data
  migration is needed.
- `_request_fields` / `_apply_response` add `demo` and `path` to the key
  loops. A `get_demo_file` row records the path it resolved to, with any
  `hwdesign/` prefix stripped, and its first demo.
- `CourseMCPRunner._record` sets `code_version` from the current snapshot for
  the four demo tools.
- `static/js/analytics.js` gets one preset, *Demos: calls by demo and file*.
  The UI suite runs every preset, so it's covered.
- `docs/admin/mcp/deploy.md` › *What is recorded*: add demo and file, and
  note that the search query is redacted.

## Where each piece goes

| File | Change |
| --- | --- |
| `llmgrader/coursemcp/code.py` (**new**) | `CodeConfig`; `CodeSnapshot` (build, exclusions, notebook flattening, front matter, path normalisation, search, read); `CodeSync` (mirror, git commands, lock, TTL, `state.json`); `CodeLibrary` (one `CodeSync` per course, pid-checked) |
| `llmgrader/coursemcp/demo_links.py` (**new**) | reference extraction, resolution, demo derivation, overrides, the link report. Pure functions over a snapshot and slide data, so build and server share them |
| `llmgrader/schemas/llmgrader_mcp_config.xsd` | optional `<code repo branch site links>` with `<include path kind>` and `<exclude>`; github.com pattern on `repo` |
| `llmgrader/schemas/llmgrader_demos.xsd` (**new**) | the overrides file |
| `llmgrader/coursemcp/materials.py` | parse `<code>` into `manifest.json`; slide hyperlink extraction (`links` in `deck.json`); `Materials.code` |
| `llmgrader/scripts/llmgrader_mcp_build.py` | `links` subcommand: the link report from the local `pub` checkout; also run by `create_soln_pkg` |
| `llmgrader/coursemcp/server.py` | the four tools; `demos` on slide results; instructions; `code_version` in `list_courses` |
| `llmgrader/coursemcp/mount.py` | `CourseMCPRunner` owns a `CodeLibrary`, runs the staleness check per request, and adds `code_version` to usage rows |
| `llmgrader/coursemcp/usage.py`, `llmgrader/services/mcp_usage.py` | arguments, key loops, three columns |
| `llmgrader/static/js/analytics.js` | one preset |
| `llmgrader/app.py` | kill switch `LLMGRADER_MCP_CODE` passed through `mount_course_mcp`; nothing touches the network |
| `run.py` | **no change** |
| `tests/coursemcp/test_course_code.py`, `test_demo_links.py` (**new**), `test_mcp_usage.py`, `tests/live/test_code_sync_live.py` (**new**) | see Test plan |
| `docs/admin/mcp/code.md` (**new**), `package.md`, `deploy.md`, `docs/student/mcp.md`, `CLAUDE.md` | instructor setup (how links are found, the overrides file, the link report); recorded fields; a student example; one architecture paragraph |

### What you add outside llmgrader

**hwdesign** (public). Nothing is required; the following improves the
links:

1. Fix the three broken references in `docs/demos/simp_fun/poly.md` and
   `simulation.md`: `demos/basic_logic/` is now `demos/simp_fun/`.
2. Wherever a slide says only `sdrangan.github.io/hwdesign`, make it name the
   demo, either as visible text (`demos/stream/avgfilt`) or as a hyperlink to
   the docs page. Each one ties a demo to a slide and a unit automatically.
3. Optional `demos/demos.xml` for what's left: units for `datatypes`,
   `simp_fun`, `conv2d`, `histogram`, `vector_mult`, descriptions for the
   code-only demos, and `hide` for `project` if it isn't a demo. I can draft it
   from the link report for you to correct.

**hwdesign-soln** (private):

1. The `<code>` element in `llmgrader_mcp_config.xml`.
2. Rebuild and upload the package, the same step the midterm is already
   waiting on. The rebuild also picks up slide hyperlinks.

## Render configuration

| Item | Change |
| --- | --- |
| Persistent disk | **None.** `/var/data` is already mounted; the mirror goes under `courses/<id>/code/` and is a few MB. Nothing runs at build time, so it doesn't matter that the disk is mounted only at runtime. |
| git | **Present:** the Render Shell reports `git version 2.39.5` (checked 2026-10-08). Partial clone (2.27+), `sparse-checkout --no-cone` (2.25+; documented as deprecated since 2.37 but still supported) and `ls-remote` all work on it. No tarball fallback. If non-cone mode is ever removed, use cone mode on the include folders; the only cost is fetching the bitstreams' ~38 MB once per change to them. The sync logs `git --version` once per process, so a future runtime image without git shows up in the log. |
| ripgrep | None. |
| `LLMGRADER_MCP_CODE` | **New kill switch**, `1` to enable, default off at first; unsetting it is the rollback. |
| `LLMGRADER_CODE_SYNC_TTL_S` | Optional, default `600`. |
| `LLMGRADER_CODE_WEBHOOK_SECRET` | Only if the webhook is built. |
| Build / start command | Unchanged. |

## Test plan

All of these run offline. The fixture is a real git repo created in
`tmp_path` with `git init`, used as the remote through a `file://` URL.
`CodeSync` takes the remote separately from the github.com base used for
links, so the real git path is exercised without the network. The fixture
holds:

- a verbatim copy of `scalar_fun.cpp` (pragmas at lines 12-16);
- a `docs/demos/procif/` with front matter, a page citing
  `hwdesign/demos/scalar_fun/scalar_fun_vitis`, a page with a broken
  reference, and a relative link to another topic;
- a `.bit`, an `hls_component/` file, a Vivado-generated `.tcl`, a notebook
  with an output-only token, and a symlink pointing outside the repo (skipped
  where the OS won't create one);
- a `_config.yml` with `url` and `baseurl`;
- a small slide fixture: a `deck.json` with one slide citing
  `demos/fsm` and one with a hyperlink to a docs page.

**Tools** (through the WSGI mount, like `test_course_mcp.py`):

1. `search_demos("s_axilite")` returns one code hit at
   `demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp`, `start_line` 12,
   `end_line` 16, with `source_url` ending `blob/<sha>/demos/scalar_fun/scalar_fun_vitis/src/scalar_fun.cpp#L12-L16`.
   A docs hit comes first, with `view_url` on the site and a heading anchor.
2. `S_AXILITE` gives the same result; `pragma HLS  interface` matches;
   `kind="doc"` and `demo="fsm"` scope correctly.
3. **Path traversal is refused:** `../../../etc/passwd`, `..\..\x`,
   `/etc/passwd`, `C:/Windows/win.ini`, `demos/../units/x.pptx` (outside the
   includes), `_config.yml` (fetched but not an include), and the symlink.
   Every one is a ToolError, and none is listed.
4. Exclusions: no `.bit`/`.hwh`, no `hls_component/`, no generated Tcl, no
   docs images; `get_demo_file` on them is a ToolError; search never hits
   them.
5. Notebooks: an output-only token isn't found, a source token is, and there
   are no line anchors. Docs: front matter is stripped, line numbers match
   GitHub's, and the title comes from front matter.
6. `get_demo_file` windowing: the 400-line cap, `truncated`, clamping, and the
   `hwdesign/` prefix accepted.
7. Search caps: 25 hits / 4 per file, `more` counted, adjacent lines merged,
   docs first.
8. Unknown course, unknown demo, and a course without `<code>` each give the
   expected ToolError text.

**Links** (`test_demo_links.py`, pure functions, no git):

9. Each reference form resolves: `demos/x`, `hwdesign/demos/x`, a
   github.com blob/tree URL, a site URL to a docs page, a relative docs
   link, and a slide hyperlink. A cited file brings in its directory.
10. Demo derivation: a docs topic plus its cited code; the same-name code
    directory is included; uncited top-level directories become code-only
    demos; a deck with the demo's name links its unit; `via` is recorded.
11. Broken and build-output references are reported, not fatal.
12. Overrides add, remove, rename and hide; an unknown override id is
    reported; a malformed overrides file keeps the previous snapshot.
13. `get_slide` on a citing slide carries `demos`.

**Sync:**

14. First clone in the background, and the bounded 5 s wait.
15. A new commit pushed to the fixture remote, plus a clock past the TTL: the
    old snapshot is served while the refresh runs, and then the new sha shows
    up in `code_version`.
16. **Time limit:** the git runner blocks on an `Event`; every demo tool
    still returns in under 1 s. This is the regression test for "nothing a
    student waits on touches GitHub".
17. Remote deleted: the last good copy is served and `last_error` is set. A
    new `CodeLibrary` (a restart) loads from the mirror without the network.
18. Corrupt mirror: it re-clones and keeps serving meanwhile.
19. Two threads asking for a refresh produce one git run.

**Usage:** the "every argument is listed" test passes; a search row has
`query: "<redacted>"`; a `get_demo_file` row has the resolved `path` and
`code_version`.

**Schema and build:** the XSD accepts `<code>` with includes and rejects a
non-github `repo`; `llmgrader_demos.xsd` validates the fixture overrides;
`llmgrader_mcp_build links` prints the report; slide hyperlinks land in
`deck.json`.

**Against the real repo:** when the sibling `../hwdesign` checkout and a
built hwdesign-soln package exist (skipped otherwise), build the snapshot and
graph from them and check:

- `s_axilite` finds `scalar_fun.cpp` 12-16;
- none of the real build outputs is served;
- procif 50 links to `procif`, fifo 28 to `stream`, fifo 55 to `fifoif`, and
  fsm 35 to `fsm`;
- the `demos/basic_logic` references are reported broken. This test needs
  updating when you fix them, which is intended.

**Live** (`tests/live`, `-m live`, no API cost): clone the real repo from
GitHub and check that the bitstreams were never downloaded.

**After deploy:** `curl` a `tools/call` of `search_demos`, and load a portal
page *while* the first clone runs to confirm grading isn't blocked.

## Phases

1. **Snapshot, sync and tools.** `code.py`, the `<code>` element, the four
   tools with docs and code, usage, and tests 1-8 and 14-19, behind
   `LLMGRADER_MCP_CODE`. `list_demos` at this point groups by the docs topic
   folder plus the code directory of the same name, without slides.
2. **Links.** `demo_links.py`, slide hyperlink extraction, the overrides
   file, the build-time report, `demos` on slide results, and tests 9-13 plus
   the real-repo test.
3. **Content and rollout.** Fix the broken references and add slide deep
   links in hwdesign; `<code>` in hwdesign-soln; rebuild, upload, docs, then
   set `LLMGRADER_MCP_CODE=1` on Render.
4. **Optional.** The webhook, and docs images.

Phases 1 and 2 can ship as one PR. They're split so phase 1 is useful on its
own, and so you can review the linking rules separately.

## Aside: the `search_slides` miss on `s_axilite`

Against the package built locally in hwdesign-soln, `search_slides("s_axilite")`
**does** return procif 2, 30, 48 and fifo 34, from their figure descriptions.
So the live miss is most likely the deployed package predating those
descriptions, which is the same rebuild and upload as above. There is also a
separate weakness: the tokenizer (`[a-z0-9]+`) splits `s_axilite` into `s` +
`axilite`, and the `s` adds noise (fixp 12 ranks fifth). Indexing
underscore-joined identifiers whole as well would fix it in a few lines. That's
out of scope here, but worth a separate small PR.

## Questions for you

1. ~~Demo granularity~~ -- decided: one demo per docs topic folder (decision 3).
2. **The naming rules:** link a docs topic to the `demos/` directory with the
   same name, and a demo to the deck with the same id? They are right for
   every case today (`fifoif`, `fixp`, `procif`, `loopopt`, `sharedmem`), and
   overrides can undo them. The alternative is citations only, which places 4
   of the 13 demos in a unit instead of 7.
3. **Overrides file:** `demos/demos.xml` (recommended; XML, with an XSD and
   line-numbered errors), TOML, or front matter on each docs `index.md` (no
   help for the 6 code-only demos)?
4. **Is `demos/project` a demo?** It holds `matchfilt.md` and `readme.md`
   only. Hide it, or keep it as a project description?
5. **Regex:** literal only (recommended) or the `regex` package with a timeout?
6. **Docs images:** leave them out of v1 (recommended; the assistant gets the
   alt text and the student opens the page), or serve them as image blocks the
   way slides are?
7. **Webhook:** skip unless the 10-minute TTL proves annoying (recommended),
   or build it now?
8. **Should I draft `demos/demos.xml`** and the broken-reference fixes in
   hwdesign once phase 2 has a link report to work from?
