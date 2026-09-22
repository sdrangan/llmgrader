# Plan: the course as a set of tools

Publish the course — questions, solutions, rubrics, and the skills they
exercise — as a remote MCP server that a student points their own AI at. The
portal keeps serving the students who do not, and the instructor keeps using it
to author and to see the cohort. Nothing here is a chat interface.

```
Student adds one connector:  https://<portal>/mcp/<course_token>
Their agent then calls:      list_skills, list_questions, get_question,
                             get_solution, get_rubric
```

Two halves that land independently. The **skill layer** (phase 0) is XML and is
useful with no server at all. The **MCP layer** (phases 1+) is delivery.

## Motivation

The portal's student-facing UI is a depreciating asset. It wraps a model we do
not own, and every capability we would add to it — chat, hints, explanation —
is something the student's own assistant already does better, on their
subscription rather than ours. The durable asset is the other half: 108 lines
of `unit.xsd`, the partial-credit modes, the rubric discipline, and 44 pages of
authoring docs. That is the part no vendor can hand an instructor, and the part
that outlives whichever surface is fashionable.

So the bet is to stop building the reader and publish material a reader can
consume. MCP is what makes that possible: an open tool protocol that lets any
app expose itself to any assistant without either side knowing about the other.

Three consequences drive the design.

**The inference is free because it is not ours.** Every call runs on the
student's subscription. This is the only arrangement whose economics work for a
single course with no per-seat fee — see `## Rejected alternatives`.

**We publish structure, not answers.** The recurring temptation is to build a
search engine, a diagnosis engine, a recommender. Each time the better move is
to publish the structure and let the agent infer. It is a frontier model; we
are a Flask app.

**Skills are the structure worth adding.** The convergent product in AI
education is upload → RAG → chat, which gives students answers and gives the
instructor nothing. A skill-tagged rubric turns every graded submission into
skill-level evidence, which is data an instructor can act on — once the
per-item grading results are stored, which today they are not (decision 8). That
tagging was historically unsustainable by hand; it is now a review task rather
than an authoring task, which is what makes this worth starting now.

## What already exists

| Need | Already in the tree |
| --- | --- |
| One process serving many courses | `CourseRegistry.grader_for()` (`course_registry.py:903`), `get()` (`course_registry.py:449`) |
| Course discovery payload | `list_courses()` (`api.py:614`) — id, name, semester, loaded |
| Unknown course must 404, never default | `bind_course` (`api.py:581`); the same rule the tools need |
| Full question dicts in memory | `grader.units[unit][qtag]` — `unit_parser.py:1344-1358` |
| Student-safe field filtering | `_strip_solution_fields` (`api.py:762`) |
| Solution figures as base64 data URIs | `UnitParser._extract_solution_images()` (`unit_parser.py:1027`) |
| Question figures resolved the same way | `resolve_question_images()` (`answers.py:333`) |
| Optional attributes on a rubric item | `rubricItemType` (`unit.xsd:47-59`) already carries four |
| A FastMCP server and its test suite | `llmgrader/mcp/server.py`, `tests/mcp/` |
| Per-request identity (weak) | `ensure_session_id` (`api.py:558`) |
| Add-a-column migration, run once | `portal_migrations` plus the `course_id` backfill pattern |

Three things that look reusable and are not:

- **`llmgrader/mcp/server.py` is the wrong server.** It is stdio transport and
  instructor-facing — skeleton generation, XML validation, repo scanning. The
  student server is a different audience over a different transport. Share the
  FastMCP dependency and nothing else, and prefix the new tools distinctly
  (`course_*`, not `llmgrader_*`) so someone running both can tell them apart.

- **`/unit/<unit_name>` cannot be wrapped as a tool.** It returns the full
  sanitized items dict (`api.py:775`), and `solution_images` are base64 data
  URIs. A single 100 KB figure is roughly 33k tokens; a unit with a few of them
  would exhaust the context window on the first call, and the student would
  just see the connector fail. Tool results are context, and every result has
  to be bounded by construction — see decision 3.

- **`POST /c/<id>/chat` (`api.py:735`) is dead code.** It calls
  `self.llm_client`, which is defined nowhere, so it 500s on first contact.
  Delete it in phase 1 rather than leaving a live endpoint that throws.

## Design decisions

### 1. `course_id` is a tool parameter, not a URL segment

One connector per student, added once, picking up new courses and new semesters
with no student action. A course-scoped URL means re-adding a connector every
term, and two connectors for a student in two courses. For a feature whose
dominant risk is setup friction, that decides it.

It maps cleanly onto the registry — `grader_for(course_id)` is already the
lookup — but it reintroduces the hazard `multicourse.md` decision 5 guards
against in URLs: a wrong-but-valid id silently serving another course's
content. Three rules make it safe.

- `list_courses()` is the discovery tool, and every other tool's description
  says `course_id` must come from it. The agent never guesses.
- An unknown id errors. Mirror `bind_course` exactly; never fall back.
- **The listing is scoped to the caller's token.** A valid-but-unauthorized id
  errors too, rather than returning empty. That makes the parameter safe by
  construction: the agent can only pass an id it learned from a call that was
  already authorized.

The third rule also forces an explicit answer to something that would otherwise
be decided by accident — whether a token grants one course or the whole portal.
With solutions exposed, portal-wide means a student in one course reads every
course's answer keys.

### 2. No search tool. Return the whole index.

The course has 75 questions. A summary — qtag, an 80-character derived label,
part labels and points, two flags — is roughly 70 tokens, so the entire course
index is about 5k tokens. One modest tool result.

So `list_questions(course_id, unit=None)` returns everything when `unit` is
omitted, and the agent does the matching itself. This beats both alternatives.

- **Substring match fails exactly where it is needed.** "state machine" does
  not match "FSM"; "flip flop" does not match "register". The agent handles
  synonymy natively.
- **Embeddings would reintroduce a server-side token cost**, plus a key on the
  server, an index to rebuild on every package upload, and a vector store — for
  a corpus that fits in one context window.

There is a correctness argument too: a search tool returns its top hits and
hides the rest, while a full index lets the agent notice that two questions
look relevant and ask which one the student means.

The index scales linearly, so the ceiling is roughly 300–500 questions. The
graceful path if that is crossed: shorten the label, then make `unit` primary,
then BM25 over `question_text` (pure Python, no API calls). Embeddings for a
question bank are hard to justify at any size this course will reach.

**The bank stays small because of decision 11**: the server holds exemplars,
and generated variants live in the student's conversation rather than in the
database. Persisting good variants back into the bank is the one realistic way
to breach the ceiling, and it is therefore a decision to take deliberately
rather than drift into.

### 3. Every tool result is bounded by construction

The rule that follows from the `/unit/<name>` trap.

- `list_*` tools return summaries only — never `question_text`, never images.
- `get_question` returns one question: text plus its figures as image content
  blocks, split out of the existing data URIs.
- `get_solution` and `get_rubric` are separate calls, one question each.

Not only a budget concern. Separating solution from question is what lets the
tool *description* act as a soft guardrail — "prefer using this to check the
student's reasoning or construct a hint rather than reproducing it" — and what
makes it visible in logs how often the answer key is actually pulled.

### 4. Solutions and rubrics are exposed; the gate is the answer key, not cheating

This is practice material. A student determined to shortcut it has a dozen
easier routes, and the portal has never pretended otherwise. Withholding
solutions from the tools would cost the tutoring use case everything and buy
nothing.

The token gate exists for a different reason: a complete answer key should not
sit on the open, crawlable web, where it is indexed and becomes training data.
That is a publishing concern, not a conduct one, and one URL path segment
satisfies it.

Two things to do first. Skim `grading_notes` across the units, since that is
the field most likely to hold instructor-only asides. And note that
`get_rubric` is the highest-value and lowest-risk of the three — the rubric
tells an agent what counts without handing over the derivation. If only one
were exposed, it would be that one.

### 5. Phase 1 has no identity at all

Dropping per-student data drops OAuth, per-student tokens and the submissions
migration, which is most of the work. One shared course token, posted in the
LMS, is adequate for read-only course content and takes an afternoon.

It also sidesteps a client constraint: the claude.ai web connector UI is built
around OAuth and does not generally expose arbitrary header configuration,
while Claude Desktop and Claude Code take headers from config files. So the
token goes in the URL path — `/mcp/<course_token>` — and the student pastes
exactly one string. A secret in a URL is unclean; for a practice answer key it
is proportionate. Verify current client behaviour before building, as this area
moves monthly.

### 6. When identity arrives, the token is the identity

`client_id` is written from `session_id` (`grader.py:1689`), an 8-hex value
minted per browser session and never linked to the `users` table. A submission
belongs to a cookie, not a person: clear cookies and you are someone new, phone
and laptop are two students. This is already wrong for analytics, independent
of MCP.

The fix that avoids re-collecting PII: the portal mints an opaque `st_<random>`
on first visit, keeps it in `localStorage`, and shows it in Preferences with a
copy button. Submissions carry it as `client_id` — the column's existing shape,
just stable. The same string is what the student pastes into their connector.
One secret is both identity and credential, and no email, `users` row or Google
linkage is involved.

Honest limit: unverified. Anyone holding the token reads that student's
submissions. Proportionate for practice; **not** a basis for anything graded. A
self-typed handle is the obvious alternative and is worse — it collides, it is
mistyped across devices, and students type their netid, which collects PII by
accident.

### 7. A skill is something that appears in more than one unit

The course has 11 units and roughly 60 learning objectives, 5–8 per deck. They
are not skills, and that difference is the whole design.

The test: does it appear in another unit? If not it is a learning objective,
and tagging a question with it says nothing the unit name did not. Applied to
unit02's five objectives — define FSMs (unit02 only), implement with sequential
logic in SV (recurs), break functions over multiple clock cycles (recurs in
five later units), write a testbench (recurs), simulate and synthesize (recurs)
— four of five are cross-cutting.

So the reduction runs *across* units, not within them. Merging within a unit
destroys exactly the information that makes tagging useful. The recurrences are
already visible in the objectives: overflow and truncation (01, 03), AXI4-Lite
(04, 09), timing analysis and diagrams (02, 05, 06, 10), Vitis HLS
implementation (04, 05, 07, 08, 10), memory partitioning and bit width (07, 08,
10), loop unrolling (07, 08, 10).

Target **15–25 skills**, at the granularity of "a thing you could write one
problem about". Taxonomies bloat; everyone who builds one ends up with 400
skills nobody can navigate. A taxonomy can always be split later and can never
be un-split once people have tagged against it.

**A skill is an id, a name, a description, and prerequisite edges** (plus
optional outcome refs). Tagging unit04 settled this by cutting fields rather
than adding them:

- A `type` (concept, analysis, construction, procedure) was tried and dropped:
  an agent reads it off the description's leading verb.
- A `status` (provisional, active, deprecated) was tried and dropped: whether a
  skill is in use is computed from the tags, and under the rule below an
  unused skill is simply deleted.
- An `area` grouping was dropped for the same reason as `type`.
- Structured misconceptions were dropped too; see decision 8.

This matches how agent skills are packaged (Anthropic's SKILL.md: a `name`, a
`description`, and prose), and for the same reason — the consumer is a model,
and anything it can infer is a field to maintain for nothing. The description
follows the SKILL.md form: what the student can do, then "Use when ...", which
is what an agent needs both to place a student's confusion and to propose tags
for new rubric items. A skill's examples are the solved problems that tag it,
found through the tags rather than listed.

**A skill exists only if some problem assesses it.** Skills taught only in
lecture or a demo are left out rather than parked; adding one back when a
problem arrives costs nothing. Tagging unit04 under this rule deleted
`memory-organization` (untestable as "identify the components"),
`simulate-synthesize-toolflow` and `fpga-deployment` (demo only), and folded
`memory-selection` into `memory-sizing`.

unit00's objectives are course-level outcomes, not unit skills. They are the
ABET tier: a shorter, separate list that skills map up into.

#### The taxonomy is global; the tagging is incremental

The course is being reworked unit by unit through the semester — lectures, labs
and problems are current through unit 3, unit 4 is next. The two duplications
the extraction found (**unit09_sharedmem's objectives slide is a verbatim copy
of unit04_procif's**, and **unit07_loopopt already contains almost all of
unit08_unroll's**) are un-reworked units, not wrong ones.

The naive incremental split — do skills for units 0–4 now, the rest later —
would break decision 7. A skill is defined by recurring across units, and that
recurrence is invisible if you only look at the first five. "Break functions
over multiple clock cycles" would be defined from unit02's perspective, missing
that it is the spine of fifo, loopopt, unroll and arrays. The taxonomy would be
shaped wrong, and several hundred rubric items would be tagged against it
before anyone noticed.

So split at a different seam:

- **Draft the skill list and DAG from all 11 units at once**, using the
  objectives slides only. Those exist for every unit already, including the
  un-reworked ones, and they are enough to see that AXI4-Lite appears in 04 and
  09. This costs a day and does not require the lectures to be fixed.
- **Tag rubric items per unit, as each unit is reworked.** That is the
  expensive half and it tracks the teaching schedule naturally.

Patching lectures now to serve the taxonomy would be backwards: curriculum work
in service of a data model. Rework on the teaching schedule and tag as you go.

Where a unit's objectives are known to be stale, its skills are drafted
provisionally and revisited when the unit is reworked. That is a normal
revision, not a failure. Renaming or merging a skill is a find-and-replace
across `skills.xml` and the unit files, which the validator can check: per-item
grading results are keyed by rubric item id, and the join to skills happens when
they are read. **The ids that must stay stable are the rubric item ids**, not
the skill ids.

#### Untagged is not unassessed

Per-unit tagging state is computed, not authored: a unit is tagged when its
rubric items carry `skill=`. The MCP tools must surface it, because
an agent that cannot distinguish "this student has no evidence on this skill"
from "this unit is not tagged yet" will confidently diagnose a gap that does
not exist. This matters most for the phase 3 mastery tools, and since the state
is computed it costs nothing to carry from the start.

### 8. Skills are tagged on rubric items, not on questions

`rubricItemType` already carries four optional attributes. One more:

```xml
<xs:attribute name="skill" type="xs:token" use="optional"/>
```

Backward compatible; untagged rubrics keep working unchanged.

Tagging the rubric item rather than the question is what makes this cheap. The
grader already decides each item separately in `rubric_eval`, with evidence and
a point decision, so a tagged rubric can say which skill a student missed rather
than only which skills a problem touches — with no new grading path, no new
model call and no prompt change.

**But `rubric_eval` is not stored.** It is returned with every grade and then
dropped: `insert_submission` writes points per part, feedback and the
explanation, and the submissions table has no rubric column. Until a
`rubric_eval_json` column is added (via the existing add-a-column migration in
`PortalStorage`), tags describe the questions correctly but no skill-level
evidence accumulates. That column is the prerequisite for everything in this
plan that reads evidence, and it is a change to llmgrader itself, so it lands
as its own reviewed change.

**Misconceptions stay prose, in the rubric item's `<notes>`.** An earlier draft
gave them ids, nested under their skill and referenced from a `misconception=`
attribute. Unit04 used nine. They were dropped because the knowledge was
already in the notes, which is also where it is least likely to rot — the
instructor is looking at them whenever the question changes — and the one
thing an id added, counting a misconception across items, is something a model
can do at analysis time by reading the notes of the items a cohort missed. The
knowledge itself is the most valuable non-inferable thing in the package: the
specific wrong models *these* students form exist only in the instructor's
head.

### 9. No diagnosis engine, no mastery model

Publish `skill_graph` and tagged rubrics, and the agent walks the prerequisite
edges itself: the student missed items tagged `fixed-point-scaling`, that
depends on `binary-number-representation`, check that first. We do not build
the inference.

Explicitly out: Bayesian knowledge tracing and its descendants. The graph and
the tagging are around 90% of the value; the statistical layer needs
cohort-scale data that will not exist for two semesters, and it is where
projects like this die.

### 10. Build the tool layer; the UI layer is not standardized yet

MCP's tool and transport layer is an open spec under neutral governance. The UI
layer is not: OpenAI's Apps SDK renders components inline in ChatGPT but is a
vendor extension, and MCP-UI is a community spec with standardization work in
progress. Both are interesting; neither is stable enough to build a course on.

The consequence is convenient rather than limiting. The tool layer is the
durable part, so building only it is also the right sequencing — if in-chat UI
settles, it becomes a rendering layer over a server that already exists.

### 11. The bank holds exemplars; variants are generated client-side

Students ask for more practice problems than 6–10 per unit. The PrairieLearn
answer is a parameterized template — `question.html` plus a `server.py` that
randomizes parameters and *computes* the answer, so grading stays exact. The
tempting AI answer is to generate variants from an exemplar, which fails at
exactly the point PL succeeds: a generated problem does not come with a
trustworthy answer. An LLM will occasionally produce a variant that is
ambiguous, unsolvable, or stated with a subtly wrong result.

The resolution is that **we do not build generation at all.** Once phase 1
exposes the exemplar, its worked solution and its rubric, "give me three more
problems like this one" is something the student's agent already does well —
and does better than a server could, because it has the worked solution as a
pattern and the student in front of it to calibrate difficulty. The infinite
problem supply is a client-side capability that falls out of decision 4 for
free.

Three consequences.

**The corpus stays at ~75, so decision 2 holds.** Variants live in the
conversation. Nothing is written back. If that ever changes — "this variant was
good, keep it" — the bank grows without bound and search stops being optional.
That is the trigger condition to watch, and it is the only realistic one.

**Exemplar quality is now the lever, not exemplar count.** If one question
seeds an unbounded number of variants, its rubric and solution quality are
amplified by every one of them. This is good news for the "we need more
problems" complaint: the answer is not more questions, it is sharper ones. And
the quality bar is already testable with tools in the tree —
`llmgrader_answer` exists precisely because a question a strong model answers
badly is usually under-specified rather than hard (`answer_cli.md`,
Motivation).

**An exemplar should say what is safe to vary.** PL encodes this in code; here
it is a prose hint to an agent. A small optional element on `questionType`:

```xml
<variation_guidance>
  Vary word lengths, scaling factors and the input range.  Keep the
  saturation/wrap choice, since the rubric keys on it.
</variation_guidance>
```

Returned by `get_question`, ignored by the grader, backward compatible. It is
the cheapest possible version of a PL generator and it costs one element.

Instructor visibility is the real loss: practice on generated variants is
invisible to the portal. The mitigation is the skill layer — a variant inherits
its exemplar's skill tags, so anything the student does submit still attributes
to skills. That is an argument for phase 0, not against generation.

## Phases

**Phase 0a — the taxonomy, once, over all 11 units. Done.** `unit.xsd` gained a
`skill` attribute on rubric items and `<variation_guidance>` on questions;
`skills.xsd` defines the vocabulary; `tools/extract_objectives.py` pulls the
~60 objectives from the decks; and the course's `skills.xml` holds 36 drafted
skills with a prerequisite DAG. Required no lecture changes.

**Phase 0b — tagging, rolling, one unit at a time.** Tag a unit's rubric items
when that unit is reworked — model proposes, spot-check by pulling each
skill's questions together and seeing whether they belong. Unit04 was the
first: converted to partial credit and tagged in one pass, 33 items across 7
skills. Whether a unit is tagged is computed from its rubric items, so there
is no flag to flip. The rest follow the teaching schedule, *roughly an hour
per unit*, revising drafted skills as each unit arrives — adding, merging and
deleting freely, keeping rubric item ids stable.

**Before any of it yields evidence: store `rubric_eval`** (decision 8). One
column and one line in `insert_submission`, on its own branch.

Everything in phase 0 lands independently of everything below.

**Phase 1 — read-only course MCP.** Mount FastMCP's ASGI app at `/mcp` beside
the WSGI Flask app (`asgiref.wsgi.WsgiToAsgi`, served under
`gunicorn -k uvicorn.workers.UvicornWorker`). Shared course token in the URL
path. Tools: `list_courses`, `list_units`, `list_questions`, `get_question`,
`get_solution`, `get_rubric`, plus `list_skills`, `get_skill` and `skill_graph`
if phase 0 has landed. Delete the dead `/chat` route. *2–3 days; most of it is
the ASGI wiring, and the tool layer is on the order of 100 lines.*

**Phase 2 — deep link.** A button in the portal opens
`claude.ai/new?q=Help me with <course> <unit> <qtag>`. Because MCP is
connected, the link carries only the pointer and the agent pulls text, figures
and rubric through tools — which sidesteps URL length limits entirely and
brings figures along. *An afternoon.*

**Phase 3 — identity.** Stable `st_<random>` in `localStorage`, written as
`client_id`, surfaced in Preferences. No backfill: old rows keep their
session-scoped ids and are simply not attributable, which is already true.
Then `my_submissions` and `my_mastery`. *2–3 days.*

**Phase 4 — `submit_answer`, conditional.** Only for formative work, where the
answer → grade → read rubric → revise loop running inside the student's agent
*is* the learning. For anything counting toward a grade, do not build it: an
agent with a grading tool will farm it. If built, record provenance (a `via`
column on `submissions`) and rate-limit per qtag, so the traffic is at least
visible.

**Phase 5 — course material.** `list_documents`, `get_document`,
`grep_documents` over the notes, before any embedding work. For a semester of
structured files this often beats chunked RAG, because chunk boundaries destroy
derivations and break figure references — which in this course is most of the
value. Real retrieval earns its place only when the material is unstructured or
scanned.

## Rejected alternatives

**In-app chat tab.** Costed at 1.5–3 weeks for a production version, plus
roughly $40–380 per semester per 100 students depending on tier. Cost is not
the blocker. The blocker is that a consumer subscription is not an API key, so
there is no way to route the spend to the student, and the result would be a
worse chat than the one they already have open in another tab.

**Embedding the student's chat in the portal.** Not possible. claude.ai and
chatgpt.com send `frame-ancestors 'none'`, and no OAuth flow exposes a consumer
subscription to a third-party app. A browser extension can do it, at the cost
of shipping an extension, Web Store review, and DOM breakage.

**Clipboard handoff.** Cheap and universal, and worth keeping as a fallback for
students who never configure a connector — but it cannot carry figures, which
in this course is most of what a student needs to transfer.

## Open questions

- **Connector gating.** Custom connectors are a paid-plan feature on claude.ai
  and ChatGPT. If the platform is the student's AI, course access becomes
  contingent on a consumer subscription. That is an equity question the
  university will raise before any technical one, and it is the strongest
  argument for keeping the portal alive as the no-AI-required path. Confirm
  current gating before promising anything to a class.

- **Token scope.** Per-course or portal-wide (decision 1). Needs an answer
  before phase 1 ships, not after.

- **SQLite under MCP traffic.** Concurrent writes from several gunicorn workers
  are already a latent concern, and MCP adds a second front door. May be the
  nudge to Postgres. Note that a *separate* Render service is not an option: a
  persistent disk attaches to one service, so the MCP server cannot open the
  same database and has to be mounted in-process.

- **Where `skills.xml` lives.** A sibling of `llmgrader_config.xml` in the
  package, or a block inside it. The former is easier to hand-edit and to share
  between courses; the latter keeps course identity in one file.

- **Whether generated variants are ever persisted.** Decision 11 keeps them in
  the conversation, which is what holds the bank at ~75 and keeps decision 2
  true. The pressure to keep a good variant will be real, and giving in means
  building search, deciding who validates a persisted problem, and versioning
  a bank that is no longer hand-authored. Worth a deliberate no for now, and
  worth revisiting only with a validation story — plausibly
  `llmgrader_answer` grading a candidate variant before it is admitted.

- **Whether some exemplars should become real PL-style generators.** For
  question types where the answer is computable — fixed-point scaling, timing
  arithmetic, resource estimates — a small Python generator gives unbounded
  variants *with* exact answers, which no LLM can promise. That is a different
  and narrower feature than decision 11, it only applies to a minority of
  questions, and it should not be started until the exemplar bank is good.

- **Sharing the format.** If the format is the durable asset, the interesting
  adoption path is other ECE instructors adopting `unit.xsd` plus the skill
  conventions without running this Flask app at all — a standard rather than a
  product, with a generic MCP server over any conforming repo. Out of scope
  here, but it is what this plan is quietly building toward.
