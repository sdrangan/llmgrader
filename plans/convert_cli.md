# Plan: `llmgrader_convert`, and the example corpus it shares with the MCP server

A new console script that turns an instructor's existing problem set — LaTeX
first, PDF second — into a unit XML file and a starter `<unit_test>` file, and
a rebuild of the MCP server on the same core.

```
llmgrader_convert HW3.tex --solution HW3_Soln.tex --out hw3.xml --tests
llmgrader_answer hw3.xml --expect full --out hw3_ai.xml
llmgrader_test run hw3_ai.xml --html hw3_report.html
```

The converter is the on-ramp; the last two lines already exist and are the
point. Deadline: the department demo on 2026-09-18.

## Motivation

**The demo.** Colleagues will not author XML by hand, and most will never open
VS Code. What they can judge is a problem set they recognise going in and a
working, graded unit coming out. A fixed pipeline behind one command gives a
repeatable demo and a context that is exactly what the code sends — no session
memory making it "work too well".

**The MCP server has decayed.** It restates the XSD and the docs as
hand-written Python dicts (`get_unit_xml_structure`, `explain_rubric_rules`,
`get_unit_test_structure`), and the three copies now disagree. Its example
catalog is three questions from one file with hand-typed `features` tags. Every
new example costs a hand edit, so the catalog never grew.

Both problems have the same fix: a corpus whose features are computed, and a
guide read from the docs. The converter and the MCP server are then two thin
front ends over one core.

## Phases

| Phase | Deliverable | Demo-critical |
| --- | --- | --- |
| 1 | Shared core: corpus index + guide sections; fix doc drift | yes |
| 2 | `llmgrader_convert` | yes |
| 3 | HW3 acceptance test; demo rehearsal | yes |
| 4 | MCP server rebuilt on the core; optional Claude Code skill | no — after the demo if time is short |

Phase 4 can slip without touching the demo. Phases 1–3 cannot.

## Design decisions

### 1. Two folders, two roles: inputs are held out, the corpus is learned from

| Role | Holds | Used as |
| --- | --- | --- |
| **Inputs** | Raw source: problem `.tex`/`.pdf`, solution, figures, code | Acceptance tests for the converter. Never shown to it as examples. |
| **Corpus** (see 4) | Reviewed unit XML **with a passing tests file**, plus the source it came from when there is one | Few-shot material for the converter and the MCP server |

Inputs live in `tests/example_problems/<set>/`; see 4 for what that exposes.

A problem set is promoted from input to corpus only after it has been
converted, reviewed by the instructor, and has grading tests that pass
`llmgrader_test check`. While a set is serving as an acceptance test it stays
out of the corpus; testing the converter on its own examples measures nothing.
HW3 stays held out through the demo.

Corpus entries keep their source alongside the XML. A (LaTeX → XML) pair
teaches the mapping — macro expansion, delimiter rewrite, where grading notes
go — which the XML alone cannot. Units with no source (the hwdesign units) are
still valid examples of the XML and test style.

### 2. A unit is an example only if it has grading tests

No tagging, no allow-list. `find_examples` accepts a unit XML only when a
`tests/*.xml` beside it passes `check_file` against it. Today that admits
`example_repo/unit1/calculus.xml` and hwdesign `unit00`–`unit02`, and excludes
the old binary-format units `unit03`–`unit10` without anyone marking them. As
units are upgraded and tested they join automatically.

### 3. Features are computed; the model picks by content

Every structural feature the old catalog hand-tagged can be read off the XML:
binary vs partial credit, part count, `rubric_total`, rubric groups, question
or solution images, `grading_notes`, `<tool>`, tier vs concrete
`preferred_model`, and the number and kind of test cases. Semantic similarity
("a proof", "a derivation with a given result") cannot, so the index also
carries each question's qtag and the first sentence of its question text, and
the caller — the converter's selection step or the MCP client — chooses from
that. Nobody writes descriptions.

A concrete model id in an example (`gpt-4.1-mini`, still in about 60
hwdesign questions) is surfaced as a warning on the example, so it is not
copied into new units.

### 4. The corpus has a public part and a private part

The llmgrader repo is **public**. A corpus entry is a problem *with its
solution*, and committing one publishes it.

- **Bundled corpus** (`llmgrader/corpus/`, shipped as package data): only
  material the author is willing to publish — `calculus.xml` and retired
  problem sets.
- **Private corpus**: the instructor's own course repos, passed as
  `--corpus DIR` (repeatable) to the converter and as `roots` to the MCP tool.
  hwdesign-soln and wirelesscomm-soln stay where they are.

Inputs are committed here. `tests/example_problems/HW3` holds full solutions
and this repo is public; the author has accepted that — students can get a
model to answer these problems anyway. A set the author does want kept private
stays in its course repo and is passed by path; the acceptance tests skip any
set that is absent.

### 5. The guide is read from the docs, not restated

`docs/admin/buildcourse/*.md` becomes the one copy of the authoring prose.
`guide_topics()` lists sections by heading; `guide(topic)` returns one. Exact
facts — enum values, allowed `rubric_total` modes, model tiers — are read from
`unit.xsd` and `models.py`, never typed into the guide.

`docs/` is outside the package, so an installed (non-editable) llmgrader cannot
read it. Ship a copy under `llmgrader/guide/` via package data, generated by a
small sync script, with a test that fails when the copy differs from `docs/`.
That is one enforced copy instead of three drifting ones.

Phase 1 fixes the drift this exposes in `unitxml.md`: `<text>` for
`<question_text>`, `<preferred_model>` shown as an element (it is an
attribute), a required `points` attribute on `<question>` that `unit.xsd` does
not have, and `unit id` marked required (the XSD makes it optional).

### 6. The converter flags; it does not silently copy or silently fix

The reference solution is what the grader trusts. HW3's 2015 solution has
typos that would make the grader penalise correct students. The converter
writes its best corrected version **and** reports every deviation from the
source as a flag, with an XML comment at the spot. The instructor confirms.

The model returns JSON:

```json
{
  "unit_xml": "<unit ...>...</unit>",
  "tests_xml": "<unit_test ...>...</unit_test>",
  "flags": [
    {"kind": "solution_error", "where": "Problem 2(c)",
     "detail": "t = sigma^2/t in the source; should be sigma^2/lambda"}
  ]
}
```

Flag kinds: `solution_error`, `statement_error`, `missing_solution` (the model
wrote one), `figure_not_carried`, `equivalent_forms` (answers that look
different but are correct), `external_reference` (for example "look it up on
Wikipedia"). Flags print as the run's summary and are written beside the
output as `<out>.flags.md`.

### 7. Deterministic lint around the model, not instead of it

The model does the rewriting; code checks it. After each attempt:

1. `UnitParser.validate_unit_text()` — schema and semantic rules.
2. **Math lint**: no `$…$` delimiters (the portal's MathJax config recognises
   only `\( \)` and `\[ \]`, `templates/index.html:15`), and no command that
   the source preamble defines with `\def`/`\newcommand` survives into
   `question_text`, `solution`, or the rubric. The preamble is parsed for the
   macro names; HW3 defines about 100. Package commands MathJax lacks are
   linted too: `siunitx` (`\SI`, `\si`, `\ang`, `\qty` — used throughout the
   wireless problems), `\mcode`, `lstlisting`, `\url`.
3. `validate_test_file()` + `check_file()` on the tests XML.

Errors go back to the model with the previous attempt; at most three rounds,
then the run fails with the remaining errors printed. `--dry-run` prints the
assembled prompt and makes no call, as `llmgrader_answer` does.

### 8. Structure mapping

- One `<question>` per numbered problem; sub-items (a), (b), … become
  `<part>` elements. qtags read like "Problem 2: MAP with exponential prior".
- Partial credit with `sum_positive` is the default; a single short "show
  that" may be binary.
- Parts that build on earlier ones get carried-forward credit written into
  `grading_notes` ("if H in (b) is wrong but (c) follows correctly from it,
  award (c)").
- `preferred_model` is a tier, never an id: `standard` for derivations and
  proofs.
- Course logistics ("send submissions to the TA") are dropped.
- Figures referenced from LaTeX with a relative path are copied beside the
  unit and referenced from it. Figures embedded only in a PDF are flagged
  `figure_not_carried` — cropping them is out of scope.
- Plot and code parts (HW3 2e) become answer-by-image questions; the portal
  already accepts student images. "Complete this MATLAB function" parts
  (wireless unit01 problems 3 and 9) are graded by reading the code, not by
  running it; the grading notes say so.
- Two source layouts: a problem file plus a separate solution file (HW3), or
  one file with `\begin{solution}` blocks after each problem (every
  `wirelesscomm-soln/*_soln.tex`). The second needs no alignment step.
- Pure numeric problems (dB conversions, Friis' law) are the weakest fit — a
  deterministic checker does them better. They still convert, with a rubric on
  the method and the value; the converter does not refuse them.

### 9. Tests target the traps

The generated tests file carries, per question: the reference answer expecting
full credit; an equivalent-form answer expecting full credit when the question
has one; a carried-forward error expecting credit in the later part; and one
common misconception. Bands follow `gradetests.md` guidance. These are
unverified until `llmgrader_test run` grades them, and the tool says so.

### 10. Provider and call

OpenAI through the model registry, like everything else: one API key. Client
construction and the `spec.supports_temperature` gate follow
`answers.make_openai_answer_caller` (`answers.py:770`), with JSON output.
LaTeX is sent as text. A PDF is sent as an `input_file`. The default tier is
`complex`, because this is one call per problem set, not per student.

## What already exists

| Need | In the tree |
| --- | --- |
| Validate unit XML text | `UnitParser.validate_unit_text()` (`unit_parser.py:221`) |
| Validate and cross-check a tests file | `validate_test_file()`, `check_file()` (`gradetests.py:252`, `:471`) |
| Full question dicts from a loose unit | `synthesize_package()` (`gradetests.py:1247`) |
| Model call pattern, temperature gate | `make_openai_answer_caller()` (`answers.py:770`) |
| Cost estimate | `price_call()` (`gradetests.py:1083`) |
| XML escaping, CDATA | `_xml_escape`, `_cdata` in `answers.py` — lift to a shared helper |
| CLI conventions, `--dry-run`, `--cost` | `scripts/llmgrader_answer.py` |
| Blind answer + grade loop | `llmgrader_answer`, `llmgrader_test run` |

## Module layout

```
llmgrader/services/corpus.py      index roots, compute features, tests gate, get example (+ its cases)
llmgrader/services/guide.py       topics and sections from llmgrader/guide/, facts from XSD + models.py
llmgrader/services/convert.py     preprocess, prompt, call, lint, retry, emit
llmgrader/scripts/llmgrader_convert.py
llmgrader/corpus/                 bundled public corpus (package data)
llmgrader/guide/                  synced copy of docs/admin/buildcourse (package data)
scripts/sync_guide.py             docs -> llmgrader/guide, checked by a test
```

## Phase 3 acceptance test: HW3

`tests/example_problems/HW3` (EE6333 Bayesian estimation, 4 problems, 13
parts) is the acceptance input. It was chosen because almost none of it can be
graded by a numeric or symbolic checker.

The converted unit must:

- pass `validate_unit_text` and the math lint;
- flag every known source error:
  - 1(b): `Z_162` should be `Z_1^2`;
  - 2(c): `t = \sigma^2/t` should be `\sigma^2/\lambda`;
  - 2(d): the completed-square constant is `(x^2-\mu^2)/(2\sigma^2)`, not
    `(x^2-t^2)/(2\sigma^2)`; the next line drops the square on `\theta-\mu`;
    the `\phi` argument should be `(\theta-\mu)/\sigma`. The final
    `E(\theta|x)` is correct;
  - 4(a): the likelihood is labelled "negative log likelihood", and "= 0" is
    missing;
  - problem statement 2(b): "for some `C(\theta)`" should be `C(x)`;
- note both Gamma parameterizations in 4(b) as `equivalent_forms` (shape–rate
  and shape–scale give different-looking `\alpha', \beta'`; 4(c) and 4(d)
  agree, because they are stated in terms of `\mu` and `\tau`), and
  `Q(u)` versus `\Phi(\mu/\sigma)` forms of the 2(d) posterior mean;
- carry forward credit for 2(c)–(d) and 4(c)–(d) in `grading_notes`;
- produce a tests file that passes `check`.

The static part (validity, lint, flags) runs against a recorded model response
so it costs nothing. The live part is marked `live`: it grades the
generated cases and a `--repeat 3` blind-answer run, and expects the
alternate-parameterization case to get full credit on every repeat.

### Not now: the wireless course

`sdrangan/wirelesscomm` (public, problems) and `wirelesscomm-soln` (private,
`*_soln.tex` for units 01–05, 08 and exams) are **not** converted in this
plan. The author may teach the course next semester and will migrate the whole
repo then — see "Next semester" below. Two things learned from a look at
`unit01_antennas` are kept because they shape the converter now: the
combined-file layout and the `siunitx` lint (8 and 7 above).

It also showed that solutions disagreeing with their statements are common,
not a HW3 accident. From the first two problems alone:

- 1(b): writes `S = E_0^2/(2\mu_0)`; the flux is `E_0^2/(2\eta_0)` (the
  numbers that follow correctly use 377 Ω, so the symbol is wrong, not the
  value);
- 2(a): −97 **dBW** is converted as if it were dBm: `2(10)^{-10}` mW should
  be `2(10)^{-7}` mW;
- 2(b): the statement asks about `8(10)^{-8}` W, but the solution converts
  `(10)^{-8}` and gets −80 dBm; the stated value is about −41 dBm.

**Demo target: HW3 Problem 4.** It is short, has no plot, and the Gamma
parameterization is the clean story: an answer that looks different, is
correct, and is marked wrong by any answer checker. Problem 3 is the backup if
a pure proof is wanted.

## Phase 4: the MCP server on the core

| Tool | Status |
| --- | --- |
| `llmgrader_guide_topics`, `llmgrader_guide` | new, over `guide.py` |
| `llmgrader_find_examples(features, roots)`, `llmgrader_get_example(file, qtag)` | new, over `corpus.py`; an example returns its test cases too |
| `llmgrader_validate_unit_xml`, `llmgrader_validate_config_xml`, `llmgrader_validate_unit_test_xml` | kept |
| `llmgrader_scan_repo_for_*` | kept |
| `get_*_structure`, `explain_rubric_rules`, `plan_question_draft` | removed — replaced by the guide |
| `create_unit_xml_skeleton`, `create_config_skeleton` | removed — an example plus a validator does the job |
| `list/get_question_example`, `mcp/examples/calculus.xml` | removed — replaced by the corpus |

`blind_user_llm.py` re-declares every tool schema by hand. Either build its
schemas from the server's own tool list or retire it. `mcp/README.md` and
`docs/admin/buildcourse/agent.md` are rewritten for the new tool set.

Optional: a Claude Code skill (`SKILL.md`) that points at the MCP tools and
`llmgrader_convert`, for authors who work in an editor.

## Next semester: whole-repo migration

The likely wireless migration is a Claude Code agent run over the course repo
with three jobs: LaTeX problems → unit XML, MATLAB → Python, and MATLAB 5G
Toolbox calls → Sionna. Only the first touches llmgrader, and this plan is
what makes it cheap:

- The agent calls `llmgrader_convert` once per problem set instead of
  improvising XML, so every unit gets the same lint, validation, retry loop
  and flags.
- It uses the Phase 4 MCP tools — `find_examples`, `guide`, the validators —
  for anything the converter does not cover, such as reworking a problem
  whose MATLAB became Python.
- Its judgement goes where it is needed: the code translation, and deciding
  per problem whether LLM grading is the right fit at all. Numeric problems
  (dB conversions, Friis) are better served by a deterministic checker.

That argues for doing Phase 4 soon after the demo rather than leaving it open.

## Schedule

| Day | Work |
| --- | --- |
| Tue 09-15 | Phase 1: `corpus.py` with the tests gate, `guide.py` + sync, `unitxml.md` fixes, tests |
| Wed 09-16 | Phase 2: `llmgrader_convert`, lint and retry loop; first run on HW3 |
| Thu 09-17 | Phase 3: HW3 acceptance; demo rehearsal on a clean run, saved outputs |
| Fri 09-18 | Demo |
| after 09-18 | Phase 4; instructor doc in the style of `aitest.md` |

All work on a feature branch — a push to `main` deploys to the live course.

## Out of scope

- Cropping figures out of PDFs.
- Randomized per-student variants.
- A "convert" button in the admin portal.
- Upgrading the old binary hwdesign units. The converter could later take an
  old unit XML as its input; not now.

## Open questions

1. Is `llmgrader/corpus/` the right home for the bundled corpus, or should
   `example_repo/` move into the package and serve both roles?
2. Which converted set becomes the first new corpus entry? HW3 after the demo
   is the natural candidate once it has been reviewed and tested — at which
   point it stops being an acceptance input and another set takes its place.
