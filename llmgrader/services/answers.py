"""Have a model sit the course's own questions.

``llmgrader_answer`` asks an LLM to answer a unit's questions from the
**question text alone** -- no solution, no rubric, no grading notes -- and
writes the answers out as a ``<unit_test>`` file that ``llmgrader_test run``
then grades.  The two commands together are a rubric stress test: a strong
model answering blind and scoring 3/10 usually indicts the question or the
rubric rather than the model.

Everything here is logic.  The terminal output, the argparse surface and the
exit code live in :mod:`llmgrader.scripts.llmgrader_answer`, the same split
:mod:`llmgrader.services.gradetests` and ``llmgrader_test`` use.

Three properties this module exists to hold:

* :func:`build_answer_prompt` sees ``question_text``, the part labels with
  their points, and question images.  Nothing else.  The moment the solution
  or the rubric leaks into it, the exercise stops measuring anything.
* Empty and refusing answers are emitted, never dropped.  A blank answer that
  goes on to score well is the most valuable thing this tool can surface.
* An unresolved question image is a loud warning rather than a fatal error, so
  the common image-free unit works without ``--pkg`` while a unit that needs
  one cannot quietly produce a meaningless number.
"""

from __future__ import annotations

import io
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date

from llmgrader.services.gradetests import (
    DEFAULT_TIMEOUT,
    GradeTestError,
    PackageContext,
    RunEnvironment,
    UnitTestFile,
    _IMG_SRC_RE,
    expand_paths,
    synthesize_package,
)
from llmgrader.services.unit_parser import UnitParser


__all__ = [
    "AnswerError",
    "AnswerOptions",
    "AnswerResult",
    "AnswerReport",
    "PlannedQuestion",
    "UnitAnswers",
    "DEFAULT_TIMEOUT",
    "EXPECT_NONE",
    "EXPECT_FULL",
    "build_answer_prompt",
    "case_id_for",
    "default_out_path",
    "make_openai_answer_caller",
    "plan_answers",
    "render_unit_test",
    "resolve_question_images",
    "run_answers",
    "slugify",
]


#: ``--expect`` values.  ``none`` is the default: the generated file's primary
#: destiny is to be edited into real cases, and a wrong assertion is worse than
#: no assertion.
EXPECT_NONE = "none"
EXPECT_FULL = "full"
EXPECT_CHOICES = (EXPECT_NONE, EXPECT_FULL)

#: Prefix on every generated case id, so a hand-written case and a generated
#: one are distinguishable at a glance in a file that ends up holding both.
CASE_ID_PREFIX = "ai_"

#: What ``--out`` appends to the unit's stem when it is not given.
OUT_SUFFIX = "_answers.xml"


class AnswerError(GradeTestError):
    """A run that could not be performed at all.

    Subclasses ``GradeTestError`` so a caller that already handles the
    gradetests failure mode -- a missing file, an unresolvable unit, a
    selector that matched nothing -- handles this one too.
    """


# ---------------------------------------------------------------------------
# Options and results
# ---------------------------------------------------------------------------


@dataclass
class AnswerOptions:
    """Everything a run needs that is not the unit files themselves."""

    pkg: str | None = None
    model: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    api_key: str | None = None
    repeat: int = 1
    jobs: int = 4
    qtags: list[str] | None = None
    out: str | None = None
    force: bool = False
    expect: str = EXPECT_NONE
    dry_run: bool = False
    cost: bool = False


@dataclass
class PlannedQuestion:
    """One question resolved to a prompt, a model and an output case id.

    Built without a single API call, so ``--dry-run`` and the emitter tests
    both work off it.
    """

    qtag: str
    unit_path: str
    unit_name: str
    case_id: str
    model: str
    partial_credit: bool
    parts: list[dict]
    prompt: str
    #: Which attempt at this question the entry is, counting from 1.  Carried
    #: on the plan rather than recomputed, so --repeat numbering has exactly
    #: one definition.
    repeat_index: int = 1
    images: list[str] = field(default_factory=list)
    #: ``<img>`` sources in the question text that did not resolve to a file.
    #: Non-zero means the model is being asked to solve a problem it cannot
    #: see, and the score means nothing.
    missing_images: int = 0


@dataclass
class AnswerResult:
    """One attempt at one question.

    ``text`` is whatever the model returned, including nothing at all.
    ``error`` is set when the call itself failed, in which case there is no
    answer to emit.
    """

    case_id: str
    qtag: str
    model: str
    repeat_index: int
    repeat_total: int
    text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.error is None and not self.text.strip()

    @property
    def is_refusal(self) -> bool:
        return self.error is None and looks_like_refusal(self.text)

    @property
    def emitted(self) -> bool:
        """Whether this attempt becomes a ``<case>``.

        A failed call did not produce an answer, so emitting one would invent
        a blank submission where in fact nothing was submitted.  An *empty*
        answer from a call that succeeded is the opposite: the model really
        did answer with nothing, and that is the case worth keeping.
        """
        return self.error is None


@dataclass
class UnitAnswers:
    """Every attempt at one unit's questions, and where they are written."""

    unit_path: str
    unit_name: str
    out_path: str
    planned: list[PlannedQuestion] = field(default_factory=list)
    results: list[AnswerResult] = field(default_factory=list)

    @property
    def missing_images(self) -> int:
        return sum(item.missing_images for item in self.planned)

    @property
    def questions_missing_images(self) -> list[PlannedQuestion]:
        return [item for item in self.planned if item.missing_images]


@dataclass
class AnswerReport:
    """The whole run: what was planned, what came back, what was written."""

    units: list[UnitAnswers] = field(default_factory=list)
    planned_calls: int = 0
    planned_by_model: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    dry_run: bool = False
    written: list[str] = field(default_factory=list)

    @property
    def results(self) -> list[AnswerResult]:
        return [result for unit in self.units for result in unit.results]

    @property
    def errors(self) -> list[AnswerResult]:
        return [result for result in self.results if result.error is not None]

    @property
    def empty(self) -> list[AnswerResult]:
        return [result for result in self.results if result.is_empty]

    @property
    def refusals(self) -> list[AnswerResult]:
        return [result for result in self.results if result.is_refusal]

    @property
    def missing_images(self) -> int:
        return sum(unit.missing_images for unit in self.units)

    @property
    def calls(self) -> int:
        return len(self.results)

    @property
    def tokens_in(self) -> int:
        return sum(result.tokens_in for result in self.results)

    @property
    def tokens_out(self) -> int:
        return sum(result.tokens_out for result in self.results)

    def estimated_cost(self) -> tuple[float, bool]:
        """``(usd, used_long_rate)`` over every attempt, per the registry rates."""
        from llmgrader.services.gradetests import price_call
        from llmgrader.services.models import get_spec

        total = 0.0
        long_rate = False
        for result in self.results:
            usd, used_long = price_call(get_spec(result.model), result.tokens_in, result.tokens_out)
            total += usd
            long_rate = long_rate or used_long
        return total, long_rate


# ---------------------------------------------------------------------------
# The prompt (§3 of plans/answer_cli.md)
# ---------------------------------------------------------------------------


_PROMPT_HEADER = (
    "You are a student answering a question on a university engineering course "
    "assignment. Answer it as well as you can, showing your work.\n"
    "\n"
    "Write the answer a strong student would hand in: the reasoning, not just "
    "the result. Plain prose and standard LaTeX for mathematics are both fine. "
    "Do not ask clarifying questions and do not comment on the question itself "
    "-- there is nobody to answer you. If you cannot solve it, write down as "
    "much correct partial work as you have.\n"
)


def build_answer_prompt(question_dict: dict) -> str:
    """Assemble the prompt for one question.

    Reads exactly three things out of ``question_dict``: ``question_text``,
    ``parts`` (labels and points), and nothing else.  ``solution``,
    ``solution_images``, ``grading_notes``, ``rubrics`` and ``rubric_total``
    are never touched -- that is the property the whole tool rests on, and
    ``tests/services/test_answers.py`` asserts it against sentinel strings.

    Part labels are here for a mundane reason: the grader scores per part, and
    an answer that silently skips part (b) loses those points for a reason
    that has nothing to do with the model's ability.
    """
    question_text = str((question_dict or {}).get("question_text") or "").strip()
    parts = list((question_dict or {}).get("parts") or [])

    sections = [_PROMPT_HEADER, "--- QUESTION ---", question_text, _points_section(parts)]
    return "\n\n".join(section for section in sections if section).strip() + "\n"


def _points_section(parts: list[dict]) -> str:
    """The part labels and their points, phrased for the shape of the question."""
    labelled = [part for part in parts if str(part.get("part_label") or "").strip()]
    if not labelled:
        return ""

    total = _num(sum(float(part.get("points") or 0) for part in labelled))

    if len(labelled) == 1 and str(labelled[0].get("part_label")).strip() == "all":
        return (
            "--- PARTS AND POINTS ---\n"
            f"The question is graded as a whole and is worth {total} points."
        )

    lines = [
        "--- PARTS AND POINTS ---",
        "The question is graded part by part. Answer every part, and label each "
        "section of your answer with the part's label so it can be matched up:",
    ]
    for part in labelled:
        label = str(part.get("part_label")).strip()
        lines.append(f"  ({label})  {_num(float(part.get('points') or 0))} points")
    lines.append(f"Total: {total} points")
    return "\n".join(lines)


def _num(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


# ---------------------------------------------------------------------------
# Question images (caveat 1)
# ---------------------------------------------------------------------------


def resolve_question_images(
    question_dict: dict,
    *,
    soln_pkg_path: str,
    unit_xml_path: str,
) -> tuple[list[str], int]:
    """``(data_uris, unresolved_count)`` for the ``<img>`` tags in the question.

    ``UnitParser._extract_solution_images`` already does HTML-to-data-URI
    resolution for a question's *solution*; the same resolution rules apply to
    the question text, so it is pointed at that instead of reimplemented.

    Under a package synthesized from a loose unit file some sources will not
    resolve.  That is a warning here rather than the fatal error
    ``llmgrader_test run`` raises -- an image-free unit is the common case and
    must work without ``--pkg`` -- but the count comes back so the caller can
    say so loudly.  Silence would produce a plausible-looking score that is
    worthless.
    """
    question_text = str((question_dict or {}).get("question_text") or "")
    if not question_text:
        return [], 0

    log = io.StringIO()
    resolved = UnitParser._extract_solution_images(question_text, soln_pkg_path, unit_xml_path, log)

    declared = sum(1 for src in _IMG_SRC_RE.findall(question_text) if not src.startswith("data:"))
    return resolved, max(0, declared - len(resolved))


# ---------------------------------------------------------------------------
# Case ids
# ---------------------------------------------------------------------------


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """A qtag reduced to a readable, id-safe token.

    Case ids have to be deterministic and derived from the qtag so that
    re-running the tool produces a readable diff rather than a reshuffle.
    """
    slug = _SLUG_STRIP_RE.sub("_", str(text or "").lower()).strip("_")
    return slug or "question"


def case_id_for(qtag: str, repeat_index: int, *, taken: set[str] | None = None) -> str:
    """The generated case id for one attempt at one question.

    ``taken`` disambiguates the rare collision -- two distinct qtags that
    slugify to the same token -- by appending a counter, so ids stay unique
    within a file without becoming opaque.
    """
    base = f"{CASE_ID_PREFIX}{slugify(qtag)}_{repeat_index}"
    if taken is None or base not in taken:
        if taken is not None:
            taken.add(base)
        return base

    suffix = 2
    while f"{base}_{suffix}" in taken:
        suffix += 1
    candidate = f"{base}_{suffix}"
    taken.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# Refusals (caveat 2)
# ---------------------------------------------------------------------------


#: Openers a refusal actually uses.  Deliberately narrow: mislabelling a real
#: answer as a refusal would put a false note in a file an instructor reads as
#: evidence, and an unmarked refusal still gets emitted and still gets graded.
_REFUSAL_MARKERS = (
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "i can't answer",
    "i cannot answer",
    "i won't be able to",
    "i'm not able to help",
    "i am not able to help",
    "i'm unable to help",
    "i am unable to help",
    "i must decline",
    "sorry, but i can't",
    "sorry, but i cannot",
)

#: A refusal is short.  Past this, a leading apology is far more likely to be
#: hedging in front of a real answer.
_REFUSAL_MAX_CHARS = 400


def looks_like_refusal(text: str) -> bool:
    """Whether an answer reads as a refusal rather than an attempt."""
    stripped = str(text or "").strip()
    if not stripped or len(stripped) > _REFUSAL_MAX_CHARS:
        return False
    lowered = stripped.lower()
    return any(marker in lowered for marker in _REFUSAL_MARKERS)


# ---------------------------------------------------------------------------
# The emitter (§1 and §2 of plans/answer_cli.md)
# ---------------------------------------------------------------------------


def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _cdata(text: str) -> str:
    """Wrap arbitrary model output in a CDATA section.

    Model output may contain ``]]>``.  Splitting the section around it is the
    XML-native fix; escaping the payload instead would change the text the
    grader sees.
    """
    return "<![CDATA[" + str(text).replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _comment_safe(text: str) -> str:
    """``--`` is illegal inside an XML comment, and so is a trailing ``-``."""
    return str(text).replace("--", "- -").rstrip("-")


def unit_attribute(unit_path: str, out_path: str) -> str:
    """The ``unit`` attribute for a file at ``out_path`` targeting ``unit_path``.

    Relative to the output file, so the generated file and the unit move
    together the way a hand-written test file does, and with forward slashes
    so the same file reads the same on both platforms.
    """
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    try:
        relative = os.path.relpath(os.path.abspath(unit_path), out_dir)
    except ValueError:
        # Different drives on Windows: an absolute path is the honest answer.
        relative = os.path.abspath(unit_path)
    return relative.replace(os.sep, "/")


def _description_for(result: AnswerResult, planned: PlannedQuestion) -> str:
    """Provenance, in the one element the schema leaves room for it in.

    ``caseType`` is a closed ``xs:all`` carrying only ``id`` and ``qtag``, so
    there is nowhere to hang a ``model=`` attribute -- and ``unit_test.xsd`` is
    shared with hand-written files, so this tool does not get to grow it.
    ``<description>`` is required anyway and is printed whenever a case fails,
    which makes it the right place.
    """
    attempt = (
        f" (attempt {result.repeat_index} of {result.repeat_total})"
        if result.repeat_total > 1
        else ""
    )
    lines = [
        f"{result.model} answered this from the question text alone{attempt}: "
        "no solution, no rubric, no grading notes."
    ]
    if result.is_empty:
        lines.append(
            "The model returned an empty answer. The case is kept deliberately: "
            "a blank submission that still scores is a finding about the rubric."
        )
    elif result.is_refusal:
        lines.append("The model declined to answer. Read the solution before trusting the score.")
    if planned.missing_images:
        lines.append(
            f"WARNING: {planned.missing_images} image(s) in the question text did not "
            "resolve, so the model answered without seeing them. Regenerate with --pkg."
        )
    return " ".join(lines)


def _expectation_xml(planned: PlannedQuestion, expect: str, indent: str) -> list[str]:
    """The full-credit assertion ``--expect full`` adds, or nothing.

    Binary questions get ``<expected_result>pass</expected_result>``;
    partial-credit questions get one ``<part min="{the part's points}"/>`` per
    part with no ``max``.  Neither trips a ``check_file`` finding: the "spans
    the whole range" warning needs ``min <= 0`` and the "max above the part
    total" error needs a ``max``.  A part worth zero points cannot be banded
    without tripping that warning, so it is left unasserted.
    """
    if expect != EXPECT_FULL:
        return []

    if not planned.partial_credit:
        return [f"{indent}<expected_result>pass</expected_result>"]

    bands = [
        f'{indent}  <part label="{_xml_escape(str(part.get("part_label")).strip())}" '
        f'min="{_num(float(part.get("points") or 0))}"/>'
        for part in planned.parts
        if str(part.get("part_label") or "").strip() and float(part.get("points") or 0) > 0
    ]
    if not bands:
        return []
    return [f"{indent}<expected_points>", *bands, f"{indent}</expected_points>"]


def render_unit_test(
    unit: UnitAnswers,
    *,
    expect: str = EXPECT_NONE,
    generated_on: str | None = None,
) -> str:
    """Render one unit's answers as a ``<unit_test>`` document.

    Assertion-free by default (§2): ``check_file`` treats an assertion-less
    case as a warning rather than an error, so the file passes
    ``llmgrader_test check`` and is accepted by ``run``, and the instructor
    can type real bands into it without first deleting wrong ones.
    """
    by_case = {item.case_id: item for item in unit.planned}
    stamp = generated_on or date.today().isoformat()
    models = sorted({result.model for result in unit.results if result.emitted})

    # Everything inside the comment goes through _comment_safe together: a
    # literal "--" anywhere in it -- a model id, a file name, or this prose --
    # makes the document not well-formed.
    comment = _comment_safe(
        "\n".join(
            [
                f"    Generated by llmgrader_answer on {stamp} from "
                f"{os.path.basename(unit.unit_path)}.",
                "",
                "    Every answer below was produced from the question text alone: no",
                "    solution, no rubric, no grading notes. The model was "
                + (", ".join(models) if models else "not called")
                + ".",
                "",
                "    This file is meant to be edited. Read each answer, decide what the",
                "    answer is worth, and write the band in. That is the near-miss",
                "    grading case that is tedious to author by hand. Until then the",
                "    cases grade and claim nothing, which `llmgrader_test check`",
                "    reports as a warning per case.",
            ]
        )
    )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<unit_test unit="{_xml_escape(unit_attribute(unit.unit_path, unit.out_path))}">',
        "",
        "  <!--",
        comment,
        "  -->",
    ]

    for result in unit.results:
        if not result.emitted:
            continue
        planned = by_case.get(result.case_id)
        if planned is None:  # pragma: no cover - a result always has its plan
            continue
        lines.append("")
        lines.append(
            f'  <case id="{_xml_escape(result.case_id)}" qtag="{_xml_escape(result.qtag)}">'
        )
        lines.append(f"    <description>{_xml_escape(_description_for(result, planned))}</description>")
        lines.append(f"    <solution>{_cdata(result.text)}</solution>")
        lines.extend(_expectation_xml(planned, expect, "    "))
        lines.append("  </case>")

    lines.append("")
    lines.append("</unit_test>")
    return "\n".join(lines) + "\n"


def default_out_path(unit_path: str) -> str:
    """``<unit-stem>_answers.xml``, beside the current directory."""
    return os.path.splitext(os.path.basename(unit_path))[0] + OUT_SUFFIX


def write_answer_file(unit: UnitAnswers, options: AnswerOptions, *, generated_on: str | None = None) -> str:
    """Render and write one unit's file, refusing to clobber without ``--force``.

    The output is meant to be hand-edited afterwards, so a second run that
    silently overwrote it would destroy an evening of band-writing (caveat 4).
    """
    if os.path.exists(unit.out_path) and not options.force:
        raise AnswerError(
            f"{unit.out_path}: already exists. This file is meant to be hand-edited after "
            "it is generated, so it is not overwritten by default. Pass --force to replace "
            "it, or --out to write somewhere else."
        )

    directory = os.path.dirname(os.path.abspath(unit.out_path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    text = render_unit_test(unit, expect=options.expect, generated_on=generated_on)
    with open(unit.out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return unit.out_path


# ---------------------------------------------------------------------------
# Planning (the shape of gradetests._plan_run, with the grading call removed)
# ---------------------------------------------------------------------------


def _pkg_entry_for_unit(pkg_context: PackageContext, unit_path: str) -> dict:
    """Match a loose unit path against the units inside a built package.

    ``PackageContext`` matches by the config's authoring-time ``<source>``
    path, which is what a unit file's own path also names, so the existing
    resolution is reused rather than duplicated.
    """
    stand_in = UnitTestFile(path=unit_path, unit_attr=os.path.basename(unit_path))
    return pkg_context.entry_for(stand_in)


def plan_answers(
    unit_paths: list[str],
    options: AnswerOptions,
    env: RunEnvironment,
    pkg_context: PackageContext | None,
    model_override: str | None,
) -> list[UnitAnswers]:
    """Resolve every question to a prompt, a model and a case id. No API calls.

    Mirrors :func:`llmgrader.services.gradetests._plan_run`: a loose unit path
    becomes a synthesized one-unit package, a ``Grader`` loads it, and
    ``grader.units[unit_name]`` yields the complete question dict that
    ``UnitParser.parse`` built.  ``gradetests.load_unit`` is not enough here --
    it reads only what a *check* needs and deliberately drops
    ``question_text``, which is the one field answering cannot do without.
    """
    from llmgrader.services.grader import Grader, preferred_model_for
    from llmgrader.services.models import DEFAULT_MODEL_SIMPLE

    units: list[UnitAnswers] = []
    repeat = max(1, options.repeat)

    for index, unit_path in enumerate(unit_paths):
        if not os.path.isfile(unit_path):
            raise AnswerError(f"{unit_path}: unit file does not exist.")

        if pkg_context is not None:
            entry = _pkg_entry_for_unit(pkg_context, unit_path)
            package_dir = pkg_context.path
            unit_name = entry["name"]
            unit_xml_path = pkg_context.unit_xml_path(entry)
        else:
            package_dir, unit_name = synthesize_package(unit_path, env.package_dir(index))
            unit_xml_path = os.path.join(package_dir, os.path.basename(unit_path))

        grader = Grader(scratch_dir=env.scratch_for(index), soln_pkg=package_dir)
        if grader.unit_validation_errors:
            raise AnswerError(
                "the unit failed validation:\n  " + "\n  ".join(grader.unit_validation_errors)
            )

        questions = grader.units.get(unit_name)
        if not questions:
            known = ", ".join(sorted(grader.units)) or "(none)"
            raise AnswerError(
                f"{unit_path}: unit '{unit_name}' loaded no questions. Units available: {known}."
            )

        selected = _select_qtags(questions, options.qtags)
        if options.qtags and not selected:
            known = ", ".join(sorted(questions)) or "(none)"
            raise AnswerError(
                f"{unit_path}: no question matched --qtag "
                f"({', '.join(options.qtags)}). Questions in that unit: {known}."
            )

        out_path = options.out or default_out_path(unit_path)
        unit_answers = UnitAnswers(
            unit_path=os.path.abspath(unit_path),
            unit_name=unit_name,
            out_path=out_path,
        )

        taken: set[str] = set()
        for qtag in selected:
            question_dict = questions[qtag]
            images, missing = resolve_question_images(
                question_dict, soln_pkg_path=package_dir, unit_xml_path=unit_xml_path
            )
            model = (
                model_override
                or preferred_model_for(question_dict, qtag)
                or DEFAULT_MODEL_SIMPLE
            )
            prompt = build_answer_prompt(question_dict)
            for repeat_index in range(1, repeat + 1):
                unit_answers.planned.append(
                    PlannedQuestion(
                        qtag=qtag,
                        unit_path=unit_answers.unit_path,
                        unit_name=unit_name,
                        case_id=case_id_for(qtag, repeat_index, taken=taken),
                        model=model,
                        repeat_index=repeat_index,
                        partial_credit=bool(question_dict.get("partial_credit")),
                        parts=list(question_dict.get("parts") or []),
                        prompt=prompt,
                        images=images,
                        missing_images=missing,
                    )
                )

        units.append(unit_answers)

    return units


def _select_qtags(questions: dict, qtags: list[str] | None) -> list[str]:
    """The qtags to answer, in the unit's own document order."""
    if not qtags:
        return list(questions)
    wanted = set(qtags)
    return [qtag for qtag in questions if qtag in wanted]


# ---------------------------------------------------------------------------
# The model call (the free-form sibling of grader._make_openai_caller)
# ---------------------------------------------------------------------------


def make_openai_answer_caller(*, model: str, api_key: str | None, prompt: str, timeout: float, images):
    """Build the callable that answers one question through the Responses API.

    The same client construction and the same ``spec.supports_temperature``
    gate as :func:`llmgrader.services.grader._make_openai_caller`, with the
    two grading-specific pieces removed: no ``text.format`` pinning the reply
    to JSON, and no parse into ``GraderRawResult``.  Answering wants prose.

    Returns a callable yielding ``(text, tokens_in, tokens_out)``.
    """
    from llmgrader.services.grader import OpenAI
    from llmgrader.services.models import get_spec

    client = OpenAI(api_key=api_key)
    spec = get_spec(model)

    image_uris = list(images or [])
    if image_uris:
        # Responses API expects top-level input items to be messages, not raw
        # content parts -- the same wrapping _make_openai_caller does.
        content = [{"type": "input_text", "text": prompt}]
        for data_uri in image_uris:
            content.append({"type": "input_image", "image_url": data_uri})
        openai_input = [{"role": "user", "content": content}]
    else:
        openai_input = prompt

    def call_openai() -> tuple[str, int, int]:
        request_kwargs = {
            "model": model,
            "input": openai_input,
            "timeout": timeout,
        }

        # Reproducibility matters more than variety here: --repeat exists to
        # expose instability, and it says more when the only source of
        # variation is the provider's own nondeterminism.  The GPT-5.6 family
        # rejects the parameter outright, so the key must be absent rather
        # than set; unknown models are treated the same way.
        if spec is not None and spec.supports_temperature:
            request_kwargs["temperature"] = 0

        resp = client.responses.create(**request_kwargs)

        # An empty reply is a result, not a failure (caveat 2).  The grading
        # caller raises here because it has nothing to parse; this one has an
        # answer to record, and "the model said nothing" is the finding.
        text = resp.output_text or ""

        if resp.usage is not None:
            return text, resp.usage.input_tokens or 0, resp.usage.output_tokens or 0
        return text, 0, 0

    return call_openai


#: Provider dispatch, keyed by ``ModelSpec.provider`` the way
#: ``grader.PROVIDER_CALLERS`` is.  One entry, because there is one provider;
#: generalizing ahead of the second would be inventing a shape for a caller
#: nobody has written yet.
PROVIDER_CALLERS = {
    "openai": make_openai_answer_caller,
}


def _answer_one(
    planned: PlannedQuestion,
    repeat_index: int,
    repeat_total: int,
    options: AnswerOptions,
    caller_factory,
) -> AnswerResult:
    """Answer one question once.

    A failed call is recorded as a result rather than raised, so one question
    failing does not lose the other twenty answers -- the same contract
    ``gradetests._grade_attempt`` holds.
    """
    result = AnswerResult(
        case_id=planned.case_id,
        qtag=planned.qtag,
        model=planned.model,
        repeat_index=repeat_index,
        repeat_total=repeat_total,
    )
    try:
        call = caller_factory(
            model=planned.model,
            api_key=options.api_key,
            prompt=planned.prompt,
            timeout=options.timeout,
            images=planned.images,
        )
        text, tokens_in, tokens_out = call()
    except Exception as exc:  # a failed call is a result to report, not a crash
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    result.text = text or ""
    result.tokens_in = tokens_in or 0
    result.tokens_out = tokens_out or 0
    return result


def _caller_factory_for(model: str, caller_factory):
    """The provider factory for ``model``, or the injected override."""
    if caller_factory is not None:
        return caller_factory

    from llmgrader.services.models import get_spec

    spec = get_spec(model)
    provider = spec.provider if spec is not None else "openai"
    factory = PROVIDER_CALLERS.get(provider)
    if factory is None:
        raise AnswerError(
            f"model '{model}' uses provider '{provider}', which llmgrader_answer cannot call. "
            f"Providers it can: {', '.join(sorted(PROVIDER_CALLERS))}."
        )
    return factory


def execute_answers(
    units: list[UnitAnswers],
    options: AnswerOptions,
    *,
    caller_factory=None,
    progress=None,
) -> None:
    """Answer every planned question, concurrently.

    ``caller_factory`` is the seam the tests replace; left None, the provider
    dispatch above picks the real one per model.  The ThreadPoolExecutor block
    is ``gradetests._execute_run``'s: results are collected in submission
    order, so the output file's case order matches the unit's, whatever order
    the calls finish in.
    """
    repeat_total = max(1, options.repeat)
    tasks = [(unit, planned) for unit in units for planned in unit.planned]

    def answer(unit: UnitAnswers, planned: PlannedQuestion) -> AnswerResult:
        return _answer_one(
            planned,
            planned.repeat_index,
            repeat_total,
            options,
            _caller_factory_for(planned.model, caller_factory),
        )

    if options.jobs <= 1:
        for unit, planned in tasks:
            result = answer(unit, planned)
            unit.results.append(result)
            if progress is not None:
                progress(result)
        return

    with ThreadPoolExecutor(max_workers=options.jobs) as pool:
        futures = [pool.submit(answer, unit, planned) for unit, planned in tasks]
        for (unit, _), future in zip(tasks, futures):
            result = future.result()
            unit.results.append(result)
            if progress is not None:
                progress(result)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_answers(
    unit_paths,
    options: AnswerOptions | None = None,
    *,
    caller_factory=None,
    progress=None,
) -> AnswerReport:
    """Answer every question in ``unit_paths`` and write the ``<unit_test>`` files.

    Everything expensive happens last: the units are resolved, every question
    is planned to a model, and ``--dry-run`` returns before a single request
    goes out.
    """
    options = options or AnswerOptions()
    resolved_paths = expand_paths(list(unit_paths))

    if options.out and len(resolved_paths) > 1:
        raise AnswerError(
            "--out names one file but this run covers "
            f"{len(resolved_paths)} units, and a <unit_test> file targets one unit. "
            "Run them one at a time, or drop --out and take the default "
            "<unit-stem>_answers.xml per unit."
        )

    if options.expect not in EXPECT_CHOICES:
        raise AnswerError(
            f"--expect '{options.expect}' is not one of {', '.join(EXPECT_CHOICES)}."
        )

    model_override = None
    if options.model:
        from llmgrader.services.models import resolve_preferred_model

        spec = resolve_preferred_model(options.model)
        if spec is None:
            raise AnswerError(
                f"--model '{options.model}' is not a tier name or a known model id. "
                "Use simple, standard, complex, or an id from the registry."
            )
        model_override = spec.id

    started = time.time()
    env = RunEnvironment()
    pkg_context = None
    try:
        if options.pkg:
            pkg_context = PackageContext(options.pkg, workdir=os.path.join(env.root, "pkg_zip"))

        units = plan_answers(resolved_paths, options, env, pkg_context, model_override)

        report = AnswerReport(units=units, dry_run=options.dry_run)
        report.planned_calls = sum(len(unit.planned) for unit in units)
        breakdown: dict[str, int] = {}
        for unit in units:
            for planned in unit.planned:
                breakdown[planned.model] = breakdown.get(planned.model, 0) + 1
        report.planned_by_model = breakdown

        # Refuse a clobber before the calls, not after the bill.  The file is
        # meant to be hand-edited, so finding out it exists should not cost
        # twenty grading calls first.
        if not options.dry_run:
            for unit in units:
                if os.path.exists(unit.out_path) and not options.force:
                    raise AnswerError(
                        f"{unit.out_path}: already exists. This file is meant to be "
                        "hand-edited after it is generated, so it is not overwritten by "
                        "default. Pass --force to replace it, or --out to write elsewhere."
                    )

        if options.dry_run:
            report.elapsed_seconds = time.time() - started
            return report

        execute_answers(units, options, caller_factory=caller_factory, progress=progress)

        for unit in units:
            report.written.append(write_answer_file(unit, options))

        report.elapsed_seconds = time.time() - started
        return report
    finally:
        env.close()
