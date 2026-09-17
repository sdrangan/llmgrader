# Plan: multiple courses on one portal

Today a deployed portal serves exactly one course: `create_app` builds one
`Grader` over one solution package, and every route reaches course content
through `self.grader`. This plan turns that singleton into a registry of
courses, adds a course picker to the File menu, and scopes the pieces of state
that must not leak between courses.

The grading path itself does not change. `grader.grade()`, `PromptBuilder`,
`UnitParser` and the model registry are course-agnostic already and stay that
way.

## Motivation

One portal per course means one Render service, one storage disk, one admin
allow-list and one set of OAuth credentials **per course**. That cost is paid
again every semester, and it is paid in the place where mistakes are most
expensive -- deploy configuration. Serving several courses from one instance
collapses that to one service the instructor administers once.

The secondary benefit is that a course becomes a first-class object rather than
"whatever ZIP was uploaded last". Today `/admin/upload` rmtrees the solution
package directory and extracts over it (`grader.py:665`); there is no way to
stage next semester's package, and no way to go back. A registry makes "load a
package" mean "load a package *into a course*", which is a smaller and safer
operation.

## What already exists

Most of the structure is in place; the work is mostly threading an id through
it.

| Need | Already in the tree |
| --- | --- |
| Course identity in the package | `<course><name>` + `<semester>`, both required by `llmgrader_config.xsd` |
| Course metadata parsed and surfaced | `UnitParser._parse_course_info()` (`unit_parser.py:76`), `APIController.banner_context()` (`api.py:64`) |
| Course name already on the wire | `/units` returns `"course": banner_context()` (`api.py:572`) |
| Banner already data-driven | `index.html:34` renders `banner.title` / `banner.instructors` |
| Per-request identity | `session["session_id"]` from `ensure_session_id` (`api.py:445`) |
| Storage root indirection | `Grader.get_storage_path()` (`grader.py:1673`), `UnitParser._resolve_solution_package_path()` (`unit_parser.py:689`) |
| Add-a-column DB migration | `Grader.temp_modify_db()` (`grader.py:479`), schema-driven `insert_submission` (`grader.py:552`) |
| A second isolated course package for tests | `tests/ui/fixtures/` is already a standalone package separate from `example_repo` |

Two things that look reusable and are not:

- **`Grader` cannot simply be instantiated N times.** `__init__` rmtrees
  `scratch_dir` (`grader.py:469`), so the second course's construction wipes the
  first course's scratch. It also re-runs `init_db`/`temp_modify_db` against the
  shared SQLite file and owns `get_admin_pref_path()` and
  `get_soln_images_path()`, which are global concerns. The class has to be split
  before it can be multiplied. This is phase 1.
- **`banner_context()` is not enough for a course list.** It returns only
  `title` and `instructors`, deliberately, for the banner. The picker needs
  `id`, `name`, `semester` and a loaded/empty flag, so `/api/courses` builds its
  own payload from the registry rather than reusing the banner helper.

## Design decisions

### 1. One database with a `course_id` column, not a database per course

Per-course SQLite files are the intuitive choice and the wrong one here.

- `users` and `admin_users` are inherently cross-course: one Google sign-in, one
  admin list. Splitting the DB means either duplicating those tables in every
  course file or keeping a separate global file alongside -- N+1 databases and a
  two-tier lookup, in place of one column.
- Analytics is admin-entered raw SQL over a single connection
  (`api.py:925`, `is_safe_analytics_sql` at `api.py:219`). Per-course files
  force either N connections or `ATTACH`, and cross-course questions ("which
  model is costing the most across everything I run") stop being expressible.
- The migration is nearly free in the other direction: `temp_modify_db` already
  adds missing columns on boot, and `insert_submission` reads its column list
  from `DB_SCHEMA`, so a `course_id TEXT` entry plus a backfill is the whole
  change.
- Contention is not the constraint. The app serializes grading to one job per
  instance today (`api.py:655`), and even after that is relaxed the write rate
  is a handful of rows per minute.

Add `course_id` to `DB_SCHEMA` (`grader.py:373`), add it to the `new_columns`
map in `temp_modify_db`, and backfill existing rows to the default course id in
the same migration -- existing rows predate multi-course, so they all belong to
the one course that was deployed. Index it:
`CREATE INDEX IF NOT EXISTS idx_submissions_course ON submissions(course_id)`.

The one real argument for separate files is portability -- handing a colleague
their course's data, or a hard legal separation. Neither applies yet, and
`SELECT ... WHERE course_id = ?` exports per course whenever it does.

### 2. Admin preferences stay global

`admin-config.json` holds `openaiApiKey`, `allowedModels` and `tokenLimit`
(`api.py:31`). All three stay in the single global file at
`get_admin_pref_path()`.

The shared OpenAI key is obviously global -- it is the deployer's key, billed to
the deployer, and there is no story in which one course on a portal bills
someone else. `allowedModels` and `tokenLimit` are arguably per-course, but
making them per-course now buys nothing concrete and costs a merge layer plus a
second migration. Global first; if a real need appears, the natural shape later
is a per-course override file that merges over the global defaults, exactly as
`get_admin_preferences` already merges over `get_default_admin_prefs()`.

This means the admin Preferences modal is unchanged by this plan.

### 3. Course id is assigned at upload, never re-derived

The id is a slug of `<name>` + `<semester>` -- `demo-class-spring-2026` -- but it
is computed **once**, when a package is first loaded into a new course, and then
stored in a small registry file. It is not recomputed from the XML on each boot.

This matters: an instructor fixing a typo in `<name>` would otherwise change the
id, orphaning every submission row and every student's saved localStorage state
with no error message anywhere. Re-uploading a package whose `<course>` block
has changed updates the display name and leaves the id alone.

**That decision requires a guard at upload.** `create_soln_pkg` writes a
hardcoded `soln_package.zip` (`scripts/create_soln_pkg.py:206`) into the working
directory; the `<course>` block is read only to *print* a confirmation line. So
an instructor running two courses has two files with the same name, and the
portal cannot tell them apart from the upload alone. Without a check, uploading
course B's ZIP into course A silently replaces A's content and renames it to B,
while keeping A's id and A's submission history -- which is precisely the
corruption the "never re-derive the id" rule was meant to prevent.

Uploading into an existing course therefore derives the id from the package's
`<course>` block and compares it to the target. On a mismatch, refuse with both
names shown and require an explicit "rename this course" confirmation. Deriving
the id is already needed to create a course, so this is a comparison, not new
machinery.

The upstream half is worth doing too: have `create_soln_pkg` name its archive
after the course slug -- `demo-class-spring-2026.zip` -- instead of
`soln_package.zip`. It is a few lines, it makes the ZIP self-describing on disk,
and it removes the ambiguity at the point where it is created rather than
catching it at the point where it does damage. Keep `soln_package/` as the
staging directory name so nothing else in the docs moves, and mention the new
archive name in `docs/admin/buildcourse/upload.md`.

Registry file at `<storage>/courses/courses.json`:

```json
{
  "courses": [
    {"id": "demo-class-spring-2026", "name": "Demo Class", "semester": "Spring 2026", "created_at": "..."}
  ],
  "default": "demo-class-spring-2026"
}
```

On first boot after the upgrade, if `<storage>/soln_pkg` exists and
`courses.json` does not, migrate: read the existing package's `<course>` block,
mint its id, move `soln_pkg` to `<storage>/courses/<id>/soln_pkg`, write
`courses.json`, and backfill `submissions.course_id`. A deployed portal must
come back up with its course intact and no admin action.

### 4. Storage layout

```
<storage>/
  db/llmgrader.db          # global
  pref/admin-config.json   # global
  soln_images/             # global (per-submission student uploads, admin-only retrieval)
  courses/
    courses.json
    <course_id>/
      soln_pkg/            # was <storage>/soln_pkg
      scratch/             # was cwd/scratch, shared
```

`UnitParser._resolve_solution_package_path()` (`unit_parser.py:689`) gains a
course id and resolves under `courses/<id>/soln_pkg`. Scratch moves under the
course for the same reason -- the rmtree in `Grader.__init__` is per-instance and
must not reach another course's files.

`soln_images/` stays global. Those are student-submitted images keyed by
submission, retrieved only through the admin-gated
`/admin/soln_images/<path:filename>` route, and the submission row itself
carries the course.

### 5. Course in the URL, not only in the session

Two candidate shapes:

- **Session key** (`session["course_id"]`). ~50 lines, every route untouched.
  But two browser tabs cannot hold two courses, nothing is linkable, and an
  instructor who runs two courses will hit this on day one.
- **Path prefix** `/c/<course_id>/...`. Correct, linkable, tab-safe. Costs a
  rewrite of every `fetch` in `app.js`, `dashboard.js`, `menu.js`,
  `analytics.js`.

Take the path prefix. `/` redirects to the last course in the session, falling
back to `courses.json`'s `default`. Keep `session["course_id"]` as the
*remembered* course for that redirect only -- never as the authority for a
request, which always comes from the path.

A `before_request` resolves `<course_id>` to a `Grader` from the registry and
stashes it on `g`; routes read `g.grader` where they read `self.grader` today.
An unknown id is a 404, not a fallback to the default -- silently grading against
the wrong course is worse than an error page.

Admin and analytics routes stay unprefixed and global (`/admin`,
`/admin/dbviewer`), since the admin list, preferences and DB are global. The
analytics view gains a course filter in its default query rather than a
different URL.

### 6. `/pkg_assets` is the sharpest hazard

`pkg_assets` (`api.py:767`) sends straight from `self.grader.soln_pkg`. With two
courses loaded and no scoping, course A's question HTML resolves its images out
of whichever package the singleton happens to hold. This must be course-scoped
in the same commit that admits the second course, not afterwards -- it is a
cross-course content leak, and the failure is silent (a wrong figure, not an
error).

Route becomes `/c/<course_id>/pkg_assets/<path:filename>`, resolving against
that course's package. `send_from_directory` keeps handling traversal.

The image paths are written into question HTML by `UnitParser`
(`_extract_solution_images`, `unit_parser.py:985`, and the `/pkg_assets/`
references cross-checked at `unit_parser.py:614`), so the parser needs the
course id to emit prefixed URLs -- or, cheaper, the front end rewrites
`/pkg_assets/` to `/c/<id>/pkg_assets/` at render time. Prefer the parser: one
place, and it keeps the served HTML self-contained.

### 7. Client-side state is namespaced per course, with a migration

`sessionState` lives in `localStorage["llmgrader_session"]`, keyed
`[unitName][qtag]` (`app.js:173`, `app.js:197`). Namespace it by course.

Use a **separate key per course** -- `llmgrader_session:<course_id>` -- rather
than adding a third nesting level. One course's state can then be cleared
without touching another's, and the quota failure in `saveSessionState`
(`app.js:188`) degrades per course instead of globally.

**Write the migration.** On first load under a course, if
`llmgrader_session:<id>` is absent and the legacy `llmgrader_session` key is
present, copy it across and leave the legacy key in place for one release.
Students have real graded work in that key; dropping it on deploy day is the
most visible way this whole change can fail, and it fails for people who cannot
diagnose it.

Same treatment for `sessionStorage["selectedUnit"]` (`app.js:1172`). Not for
`selectedModel`, `gradeTimeout` or `openai_api_key` (`menu.js:241`) -- those are
user preferences and should follow the user across courses.

### 8. Gradescope submissions carry the course id

The autograder verifies an Ed25519 signature over the exact `results.json` bytes
against a single `LLMGRADER_PUBLIC_KEY` (`gradescope/autograde.py`,
`services/signing.py`). One key pair shared across all courses on a portal is
fine -- the key authenticates *the portal*, not the course.

But `results.json` should gain `course_id` so an autograder configured for
course B can reject a submission generated against course A. Without it, a
student with two courses on one portal can upload the wrong file and receive a
plausible-looking score.

Per `CLAUDE.md`, `run --gradescope` in `gradetests.py` mirrors
`downloadSubmission` in `dashboard.js` **entry for entry**, over bytes that are
then signed. Both must change in the same commit or every signature breaks. The
autograder's check is a warn-then-fail: accept a `results.json` with no
`course_id` for one release (old submissions in flight), then require it.

### 9. Per-session grade jobs are a prerequisite, not a follow-up

`start_grade_job` (`api.py:655`) allows exactly one active job per app instance
and returns 409 `already_running` to everyone else. That is already tight for
one course. Put several courses' students on one portal -- which is the entire
point of this work -- and it becomes the binding constraint well before any
storage or routing concern.

`self.grade_jobs` is already a dict keyed by job id with a lock; the change is
to drop `self.active_grade_job_id` as a single slot and key the
already-running check by `session_id` instead. Do this before the picker ships.

## Phases

Each phase is independently shippable and leaves single-course behaviour intact
at every commit. That matters: merging to `main` auto-deploys to a live course,
and CI does not run the Playwright suite -- so the UI suite must be run by hand
before each of these merges.

| # | Phase | Shape |
| --- | --- | --- |
| 1 | Split global infrastructure out of `Grader` | Pure refactor. DB, admin prefs, `soln_images` move to a shared service; `Grader` keeps units, package and scratch. No behaviour change, no UI change. |
| 2 | `CourseRegistry` + per-course storage | Registry, `courses.json`, per-course `soln_pkg`/`scratch`, boot migration from the legacy layout. Still exactly one course. No UI change. |
| 3 | `course_id` column | `DB_SCHEMA` + `temp_modify_db` + index + backfill. Analytics default query filters by course. |
| 4 | Per-session grade jobs | Independent of the rest; ship whenever ready. |
| 5 | URL scoping and the picker | `/c/<id>/...`, `g.grader`, scoped `pkg_assets`, `GET /api/courses`, "Select Course..." in the File menu, localStorage namespacing + migration. The big front-end commit. |
| 6 | Course management and Gradescope | Admin create/rename/delete course, upload scoped to a course with the id-mismatch guard, `create_soln_pkg` naming its archive after the course slug, `course_id` in `results.json` and the autograder. |

Phases 1-4 are invisible to users and can land over several weeks. Phase 5 is
the one that needs a careful deploy and a hand-run UI suite.

**Phase 1 is done** on `feature/course-registry-refactor` (`fb4d8dc`):
`PortalStorage` in `services/portal_storage.py` owns the database, the admin
preferences file and the student image store; `Grader` keeps course content and
holds a `storage`, with delegating shims so existing callers still work. Scratch
ownership is decided once in `claim_scratch_dir`. Verified at that commit: 451
passed / 33 deselected, and `tests/ui/` green three runs out of three.

## Test fixtures: a second course belongs in `tests/ui/fixtures/`, not `example_repo`

`example_repo` is the documented teaching artifact. Eight doc pages and seven
test modules reference its paths (`docs/admin/buildcourse/*`,
`tests/services/test_gradetests_*`, `tests/scripts/*`, `tests/live/*`).
Restructuring it into `course_a/ course_b/` would churn every one of those paths
and every doc code block.

It would also teach the wrong thing. Multi-course is a property of the
**portal**, not of a package: a course package is completely unchanged by this
plan -- same ZIP, same `llmgrader_config.xml`, same `create_soln_pkg`
invocation. An instructor authoring their first course has nothing to learn from
a second one sitting next to it.

What actually needs two courses is the portal test suite, and that already uses
its own fixture package at `tests/ui/fixtures/` (`tests/ui/conftest.py:89`),
independent of `example_repo`. Add `tests/ui/fixtures/course2/` -- one config,
one two-question unit, no images -- and have `live_server` register both. That is
roughly 40 lines and touches no documentation.

The one place `example_repo` should grow is at phase 5, for hand-testing course
switching locally: add `example_repo/course2/` as a **leaf** -- a minimal config
and a single short unit -- alongside the existing `unit1/` and `unit2/`. Every
existing path stays valid, the docs keep working unchanged, and
`python run.py --soln_pkg ...` gains a second thing to point at.

## Open questions

- **Does `--soln_pkg` still mean anything?** `run.py` passes a single package
  path for local testing. Simplest answer: it registers that package as the sole
  course and skips the registry file entirely, preserving today's local
  workflow. A `--courses <dir>` flag can come later if it is wanted.
- **Course deletion semantics.** Dropping a course should probably archive
  rather than delete its submission rows -- grades are the one thing here that is
  not reconstructible. Default to a `deleted_at` on the registry entry with rows
  retained, and make hard deletion a separate explicit action.
- **Cross-course dashboard.** A student in two courses on one portal sees them
  as unrelated sites. Whether that is a problem depends on how many such
  students exist; defer until it is observed.
- **Scratch ownership across gunicorn workers.** `claim_scratch_dir` (phase 1)
  is a process-global set, which is the right scope for several `Grader`s in one
  process and no protection at all across processes. Render runs `gunicorn
  run:app` with no `--workers` flag (`docs/admin/deploy/render.md:69`), so today
  there is one worker and the claim holds. But more students on one instance is
  the point of this work, and `--workers 2` is the obvious response to that --
  at which point both workers rmtree `cwd/scratch` and both run `init_db`. This
  is pre-existing, not introduced by phase 1. Phase 2 should make scratch
  per-course *and* per-process (append the pid, or a per-worker temp root)
  rather than rely on a lock.
