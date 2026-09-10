"""``llmgrader_answer`` -- have a model sit the course's own questions.

Asks a model to answer a unit's questions from the **question text alone** --
no solution, no rubric, no grading notes -- and writes the answers out as a
``<unit_test>`` file that ``llmgrader_test run`` then grades::

    llmgrader_answer example_repo/unit1/calculus.xml --out ai_answers.xml
    llmgrader_test run ai_answers.xml --html ai_report.html

The point is not the score.  When a strong model answers blind and scores
3/10, the usual cause is that the question is under-specified or that a rubric
item keys on phrasing rather than substance -- signal you cannot get from your
own hand-written cases, because you write those already knowing what the
rubric wants.  The generated file is also meant to be *edited*: read each
answer, type a band, keep it, and the near-miss grading cases that are tedious
to author have written themselves.

All the logic lives in :mod:`llmgrader.services.answers`; this module is
argparse, a terminal summary, and the exit code.

Exit codes: ``0`` every question was answered and the file was written, ``1``
at least one call failed, ``2`` the run could not be performed at all -- a
missing unit, a selector that matched nothing, no API key, an output file that
already exists.
"""

from __future__ import annotations

import argparse
import os
import sys

from llmgrader.services.answers import (
    DEFAULT_TIMEOUT,
    EXPECT_CHOICES,
    EXPECT_NONE,
    AnswerError,
    AnswerOptions,
    run_answers,
)
from llmgrader.services.gradetests import LONG_CONTEXT_CAVEAT, GradeTestError


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def _caller_factory():
    """The seam the tests replace.

    Returning ``None`` hands :func:`run_answers` back to its own per-model
    provider dispatch, which is what a real run wants; a test monkeypatches
    this to a fake and never reaches OpenAI.
    """
    return None


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmgrader_answer",
        description=(
            "Ask a model to answer a unit's questions from the question text alone and "
            "write the answers as a <unit_test> file. The prompt never contains the "
            "solution, the rubric or the grading notes, so a low score is evidence about "
            "the question rather than about the model. Uses your API key and makes real "
            "calls; --dry-run prints the call count first."
        ),
    )
    parser.add_argument(
        "unit_files",
        nargs="+",
        metavar="UNIT-FILE",
        help="One or more unit XML files, or a quoted glob such as 'units/*.xml'.",
    )
    parser.add_argument(
        "--pkg",
        metavar="PATH",
        default=None,
        help=(
            "Built solution package (directory or .zip) to read the units from, instead of "
            "loose unit files. Needed when a question embeds an image."
        ),
    )
    parser.add_argument(
        "--qtag",
        action="append",
        default=None,
        metavar="TAG",
        help="Only answer this qtag. Repeatable.",
    )
    parser.add_argument(
        "--model",
        metavar="ID|TIER",
        default=None,
        help=(
            "Answer every question with this model. A tier name (simple/standard/complex) "
            "or a model id. Unflagged, each question is answered by the model the course "
            "would grade it with."
        ),
    )
    parser.add_argument(
        "--repeat", type=int, default=1, metavar="N",
        help="Answer each question N times, as N separate cases (default: 1).",
    )
    parser.add_argument(
        "--jobs", type=int, default=4, metavar="N",
        help="Concurrent calls (default: 4).",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SEC",
        help=f"Per-call timeout in seconds (default: {DEFAULT_TIMEOUT:g}).",
    )
    parser.add_argument(
        "--out", default=None, metavar="FILE",
        help=(
            "Where to write the generated test file (default: <unit-stem>_answers.xml in "
            "the current directory). One unit per file."
        ),
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite the output file if it exists. It is meant to be hand-edited, so this is off by default.",
    )
    parser.add_argument(
        "--expect", choices=EXPECT_CHOICES, default=EXPECT_NONE,
        help=(
            "'full' adds a full-credit assertion to every case, so `llmgrader_test run` "
            "reports the score as a pass count. Default 'none' asserts nothing, which is "
            "what you want if you are going to write real bands in by hand."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve every question and print the call count and per-model breakdown. No API calls.",
    )
    parser.add_argument(
        "--cost", action="store_true",
        help="Also report a dollar estimate from the registry rates, with its caveat.",
    )
    parser.add_argument(
        "--api-key", default=None, metavar="KEY",
        help="API key to answer with (default: the OPENAI_API_KEY environment variable).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Per-question detail.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Summary line and exit code only.")
    return parser


def _options(args) -> AnswerOptions:
    return AnswerOptions(
        pkg=args.pkg,
        model=args.model,
        timeout=args.timeout,
        api_key=args.api_key or os.environ.get("OPENAI_API_KEY"),
        repeat=args.repeat,
        jobs=args.jobs,
        qtags=args.qtag,
        out=args.out,
        force=args.force,
        expect=args.expect,
        dry_run=args.dry_run,
        cost=args.cost,
    )


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------


def _print_dry_run(report, options: AnswerOptions) -> None:
    questions = sum(len(unit.planned) for unit in report.units) // max(1, options.repeat)
    plural = "s" if report.planned_calls != 1 else ""
    print()
    print(
        f"dry run: {report.planned_calls} call{plural} across {questions} questions"
        + (f", {options.repeat} repeats each" if options.repeat > 1 else "")
    )
    for model_id, count in sorted(report.planned_by_model.items()):
        print(f"  {model_id:<24}{count:>6}")

    for unit in report.units:
        print()
        print(f"{unit.unit_path}  ->  {unit.out_path}")
        for item in unit.planned:
            if item.repeat_index != 1:
                continue
            print(f"  {item.qtag:<28}{item.model}")

    _print_image_warning(report)

    if options.cost:
        # No tokens have been spent, so the estimate is priced off the prompt
        # that would be sent and a rough answer length -- enough to tell a
        # $0.02 run from a $2 one, which is what the flag is for.
        usd, long_rate = _estimate_planned_cost(report, options)
        suffix = " (includes long-context calls: LOWER BOUND)" if long_rate else ""
        print()
        print(f"estimated cost ${usd:.4f}{suffix}")
        print(LONG_CONTEXT_CAVEAT)

    print()
    print("no API calls were made")


#: Answer length assumed by the --dry-run estimate, in output tokens.  A worked
#: solution to an engineering problem, not a one-line reply.
ASSUMED_ANSWER_TOKENS = 900

#: Characters per token, for sizing a prompt that has not been tokenized.
_CHARS_PER_TOKEN = 4


def _estimate_planned_cost(report, options: AnswerOptions) -> tuple[float, bool]:
    from llmgrader.services.gradetests import price_call
    from llmgrader.services.models import get_spec

    total = 0.0
    long_rate = False
    for unit in report.units:
        for item in unit.planned:
            tokens_in = max(1, len(item.prompt) // _CHARS_PER_TOKEN)
            usd, used_long = price_call(get_spec(item.model), tokens_in, ASSUMED_ANSWER_TOKENS)
            total += usd
            long_rate = long_rate or used_long
    return total, long_rate


def _print_image_warning(report) -> None:
    """Name every question the model answered without seeing its figure.

    Loud rather than fatal (caveat 1): an image-free unit is the common case
    and must work without --pkg, but a score produced without the figure is
    worthless, and silence here would let it look fine.
    """
    if not report.missing_images:
        return
    print()
    for unit in report.units:
        for item in unit.questions_missing_images:
            if item.repeat_index != 1:
                continue
            print(
                f"  warning: '{item.qtag}' has {item.missing_images} question image(s) that "
                "did not resolve; the model answers without seeing them."
            )
    print("  Build a solution package and pass --pkg to fix this.")


def _print_answer(result) -> None:
    status = "error" if result.error else ("empty" if result.is_empty else ("refused" if result.is_refusal else "ok"))
    print(f"  {status:<8}{result.case_id:<34}{result.qtag:<28}{result.model}")
    if result.error:
        print(f"        {result.error}")


def _print_report(report, *, verbose: bool, streamed: bool) -> None:
    if streamed:
        return
    for unit in report.units:
        print()
        print(f"{unit.unit_path}  ({len(unit.results)} answers)")
        if verbose:
            print()
            for result in unit.results:
                _print_answer(result)


def _print_summary(report, options: AnswerOptions) -> None:
    answered = [r for r in report.results if r.emitted and not r.is_empty]
    parts = [
        f"{len(answered)} answered",
        f"{len(report.empty)} empty",
        f"{len(report.errors)} failed",
    ]
    if report.refusals:
        parts.append(f"{len(report.refusals)} refused")

    print()
    print(", ".join(parts))
    print(
        f"{report.calls} calls, {report.elapsed_seconds:.1f} s, "
        f"{report.tokens_in:,} in / {report.tokens_out:,} out"
    )

    if report.missing_images:
        count = report.missing_images
        print(
            f"{count} question image{'s' if count != 1 else ''} did not resolve; "
            "those answers were written without seeing the figure. Rebuild with --pkg."
        )

    if report.errors:
        print()
        first = report.errors[0]
        print(f"first failure: {first.qtag}: {first.error}", file=sys.stderr)

    if options.cost:
        usd, long_rate = report.estimated_cost()
        suffix = " (includes long-context calls: LOWER BOUND)" if long_rate else ""
        print(f"estimated cost ${usd:.4f}{suffix}")
        print(LONG_CONTEXT_CAVEAT)

    for path in report.written:
        print(f"wrote: {path}")

    if report.written and options.expect == EXPECT_NONE:
        print(
            "The cases assert nothing yet. Read each answer, write the band you think it "
            "deserves, and it becomes a real grading case."
        )
    if report.written:
        print(f"next:  llmgrader_test run {report.written[0]} --html ai_report.html")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    options = _options(args)

    if options.repeat < 1:
        print("error: --repeat must be at least 1.", file=sys.stderr)
        return EXIT_USAGE

    if options.jobs < 1:
        print("error: --jobs must be at least 1.", file=sys.stderr)
        return EXIT_USAGE

    if not options.dry_run and not options.api_key:
        print(
            "error: no API key. Pass --api-key or set OPENAI_API_KEY. "
            "Use --dry-run to see what a run would cost first.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    progress = _print_answer if (args.verbose and not args.quiet) else None

    try:
        report = run_answers(
            args.unit_files,
            options,
            caller_factory=_caller_factory(),
            progress=progress,
        )
    except GradeTestError as exc:  # AnswerError is one of these
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if options.dry_run:
        _print_dry_run(report, options)
        return EXIT_OK

    if not args.quiet:
        _print_report(report, verbose=args.verbose, streamed=progress is not None)
        _print_image_warning(report)

    _print_summary(report, options)
    return EXIT_FAILED if report.errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
