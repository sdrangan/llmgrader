"""``llmgrader_test`` -- run an instructor's grading tests.

Two subcommands, split by what they cost:

* ``check`` -- cross-references a test file against the unit it targets.  No
  API calls, no key, no :class:`~llmgrader.services.grader.Grader`.  This is
  the one to run on every edit, and the one that belongs in CI.
* ``run`` -- grades every case through the same path a student submission
  takes and compares the result to the expectations.  Real calls, real money.

All the logic lives in :mod:`llmgrader.services.gradetests`; this module is
argparse, a terminal table, and the exit code.

Exit codes: ``0`` everything passed, ``1`` at least one error-level finding
(``--strict`` promotes warnings), ``2`` the run could not be performed at all
-- a missing file, XML that does not parse, an unresolvable unit, a selector
that matched nothing.
"""

from __future__ import annotations

import argparse
import os
import sys

from llmgrader.services.gradetests import (
    DEFAULT_REPORT_PATH,
    DEFAULT_TIMEOUT,
    FAILING_VERDICTS,
    GRADESCOPE_DEFAULT_DIR,
    LEVEL_ERROR,
    LONG_CONTEXT_CAVEAT,
    VERDICT_FAIL,
    VERDICT_FLAKY,
    VERDICT_ERROR,
    VERDICT_PASS,
    VERDICT_WARN,
    CheckResult,
    GradeTestError,
    PackageContext,
    RunOptions,
    check_file,
    expand_paths,
    load_test_file,
    load_unit,
    resolve_unit_path,
    run_test_files,
    validate_test_file,
)


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "test_files",
        nargs="+",
        metavar="TEST-FILE",
        help="One or more test XML files, or a quoted glob such as 'unit1/tests/*.xml'.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--unit",
        metavar="PATH",
        default=None,
        help="Unit XML to check against. Defaults to the unit attribute of the test file.",
    )
    source.add_argument(
        "--pkg",
        metavar="PATH",
        default=None,
        help="Built solution package (directory or .zip) to check against, instead of a loose unit file.",
    )
    parser.add_argument(
        "--qtag",
        action="append",
        default=None,
        metavar="TAG",
        help="Only consider cases for this qtag. Repeatable.",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=None,
        metavar="ID",
        help="Only consider this case id. Repeatable.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Per-case detail.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Summary line and exit code only.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmgrader_test",
        description="Check and run instructor-authored grading tests.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check",
        help="Cross-reference test files against their units. Free: makes no grading calls.",
        description=(
            "Compare a grading test file against the unit it targets and report orphaned "
            "qtags, unknown part labels and rubric ids, impossible bands, assertions in the "
            "wrong form for the question's grading mode, and rubric items no case covers. "
            "Makes no API calls and needs no key."
        ),
    )
    _add_common_options(check_parser)
    check_parser.add_argument(
        "--coverage",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Report rubric items no case exercises (default: on).",
    )
    check_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Grade every case and compare the result to its expectations. Costs money.",
        description=(
            "Grade each case through the same path a student submission takes and compare "
            "the result to the case's expectations. Uses your API key and makes real "
            "grading calls; run `check` first, and `run --dry-run` to see the call count."
        ),
    )
    _add_common_options(run_parser)
    run_parser.add_argument(
        "--model",
        metavar="ID|TIER",
        default=None,
        help="Override the model for every case. A tier name (simple/standard/complex) or a model id.",
    )
    run_parser.add_argument(
        "--repeat", type=int, default=1, metavar="N",
        help="Grade each case N times and report the spread (default: 1).",
    )
    run_parser.add_argument(
        "--jobs", type=int, default=4, metavar="N",
        help="Concurrent grading calls (default: 4).",
    )
    run_parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SEC",
        help=f"Per-call timeout in seconds (default: {DEFAULT_TIMEOUT:g}).",
    )
    run_parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve every case and print the call count and per-model breakdown. No API calls.",
    )
    run_parser.add_argument(
        "--max-calls", type=int, default=None, metavar="N",
        help="Refuse to start if the run would exceed N calls.",
    )
    run_parser.add_argument(
        "--cost", action="store_true",
        help="Also report a dollar estimate from the registry rates, with its caveat.",
    )
    run_parser.add_argument(
        "--out", default=DEFAULT_REPORT_PATH, metavar="PATH",
        help=f"JSON report destination (default: {DEFAULT_REPORT_PATH}).",
    )
    run_parser.add_argument(
        "--html", default=None, metavar="PATH",
        help="Also write the readable HTML report.",
    )
    run_parser.add_argument(
        "--fail-fast", action="store_true", help="Stop at the first failing case.",
    )
    run_parser.add_argument(
        "--api-key", default=None, metavar="KEY",
        help="API key to grade with (default: the OPENAI_API_KEY environment variable).",
    )
    run_parser.add_argument(
        "--keep-db", action="store_true",
        help="Keep the temporary SQLite storage the run writes to, for inspection.",
    )
    run_parser.add_argument(
        "--gradescope",
        nargs="?",
        const=GRADESCOPE_DEFAULT_DIR,
        default=None,
        metavar="DIR",
        help=(
            "Also write a Gradescope submission from the graded cases: the folder DIR and "
            "DIR.zip beside it, the same zip the portal's Download submission produces. "
            "Defaults to ./submission."
        ),
    )
    run_parser.add_argument(
        "--first-case",
        action="store_true",
        help=(
            "For --gradescope: when a question has several selected cases, answer it with "
            "the first in document order instead of refusing to choose."
        ),
    )

    return parser


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def _selected_cases(test_file, qtags, case_ids):
    cases = test_file.cases
    if qtags:
        wanted = set(qtags)
        cases = [case for case in cases if case.qtag in wanted]
    if case_ids:
        wanted = set(case_ids)
        cases = [case for case in cases if case.case_id in wanted]
    return cases


def _unit_for(test_file, args, pkg_context):
    """Resolve the unit a test file is checked against.

    ``--pkg`` matches the test file's unit against the package's config; a
    loose ``--unit`` path, or the file's own unit attribute, is read directly.
    """
    if pkg_context is not None:
        return pkg_context.unit_for(test_file, unit_override=args.unit)
    return load_unit(resolve_unit_path(test_file, args.unit))


def command_check(args) -> int:
    try:
        paths = expand_paths(args.test_files)
    except GradeTestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    pkg_context = None
    if args.pkg:
        try:
            pkg_context = PackageContext(args.pkg)
        except GradeTestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    filtered = bool(args.qtag or args.case)
    coverage = args.coverage and not filtered

    total_errors = 0
    total_warnings = 0
    total_cases = 0
    selected_any = False

    for path in paths:
        try:
            result = _check_one(path, args, pkg_context, coverage=coverage)
        except GradeTestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

        if filtered and result.case_count == 0:
            continue
        selected_any = selected_any or result.case_count > 0

        total_cases += result.case_count
        total_errors += len(result.errors)
        total_warnings += len(result.warnings)

        if not args.quiet:
            _print_check_result(result, verbose=args.verbose)

    if filtered and not selected_any:
        selector = ", ".join(args.qtag or []) + ", ".join(args.case or [])
        print(f"error: no cases matched the selector ({selector}).", file=sys.stderr)
        return EXIT_USAGE

    if filtered and not args.quiet and args.coverage:
        print("note: coverage reporting is off because --qtag/--case selected a subset of cases.")

    summary = (
        f"{total_cases} case{'s' if total_cases != 1 else ''}, "
        f"{total_errors} error{'s' if total_errors != 1 else ''}, "
        f"{total_warnings} warning{'s' if total_warnings != 1 else ''}"
    )
    print(summary)

    if total_errors:
        return EXIT_FAILED
    if args.strict and total_warnings:
        return EXIT_FAILED
    return EXIT_OK


def _check_one(path, args, pkg_context, *, coverage: bool) -> CheckResult:
    """Schema-validate, parse and check one file, honouring --qtag/--case."""
    schema_findings = validate_test_file(path)
    if schema_findings:
        return CheckResult(test_path=path, unit_path=None, findings=schema_findings)

    test_file = load_test_file(path)
    unit = _unit_for(test_file, args, pkg_context)

    selected = _selected_cases(test_file, args.qtag, args.case)
    if len(selected) != len(test_file.cases):
        test_file.cases = selected

    return CheckResult(
        test_path=path,
        unit_path=unit.path,
        findings=check_file(test_file, unit, coverage=coverage),
        test_file=test_file,
        unit=unit,
    )


def _print_check_result(result: CheckResult, *, verbose: bool) -> None:
    unit_label = os.path.basename(result.unit_path) if result.unit_path else "unresolved"
    print()
    print(f"{result.test_path}  (unit: {unit_label}, {result.case_count} cases)")
    print()

    if verbose and result.test_file is not None and result.unit is not None:
        for case in result.test_file.cases:
            question = result.unit.questions.get(case.qtag)
            mode = "?" if question is None else ("partial" if question.partial_credit else "binary")
            claims = []
            if case.expected_result:
                claims.append(f"result={case.expected_result}")
            for band in case.expected_points:
                claims.append(f"{band.label}=[{band.min}, {band.max}]")
            for expectation in case.expected_rubrics:
                if expectation.expect is not None:
                    claims.append(f"{expectation.item_id}={expectation.expect}")
                else:
                    claims.append(f"{expectation.item_id}=[{expectation.min}, {expectation.max}]")
            print(f"  {case.case_id:<32}{case.qtag:<26}{mode:<9}{'; '.join(claims) or '(no assertions)'}")
        print()

    for finding in result.findings:
        label = "ERROR" if finding.level == LEVEL_ERROR else "WARN "
        location = f"line {finding.line}: " if finding.line is not None else ""
        print(f"  {label}  {location}{finding.message}")

    if not result.findings:
        print("  no problems found")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _run_options(args) -> RunOptions:
    return RunOptions(
        unit=args.unit,
        pkg=args.pkg,
        model=args.model,
        timeout=args.timeout,
        api_key=args.api_key or os.environ.get("OPENAI_API_KEY"),
        repeat=args.repeat,
        jobs=args.jobs,
        keep_db=args.keep_db,
        fail_fast=args.fail_fast,
        dry_run=args.dry_run,
        qtags=args.qtag,
        case_ids=args.case,
        max_calls=args.max_calls,
        out=args.out,
        html=args.html,
        cost=args.cost,
        gradescope=args.gradescope,
        first_case=args.first_case,
    )


def command_run(args) -> int:
    options = _run_options(args)

    if options.fail_fast and options.gradescope is not None:
        print(
            "error: --fail-fast and --gradescope ask for opposite things. --fail-fast stops "
            "at the first failing case, which leaves questions with no grade to submit.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if options.first_case and options.gradescope is None:
        print(
            "error: --first-case only means something with --gradescope; it chooses which "
            "case answers a question that has several.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if not options.dry_run and not options.api_key:
        print(
            "error: no API key. Pass --api-key or set OPENAI_API_KEY. "
            "Use --dry-run to see what a run would cost first.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if options.repeat < 1:
        print("error: --repeat must be at least 1.", file=sys.stderr)
        return EXIT_USAGE

    progress = _stream_case if (args.verbose and not args.quiet) else None

    try:
        report = run_test_files(args.test_files, options, progress=progress)
    except GradeTestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if options.dry_run:
        _print_dry_run(report, options)
        return EXIT_OK

    if not args.quiet:
        _print_run_report(report, options, streamed=progress is not None)

    _print_run_summary(report, options)
    return EXIT_FAILED if (report.failed or report.submission_error) else EXIT_OK


def _print_dry_run(report, options: RunOptions) -> None:
    plural = "s" if report.planned_calls != 1 else ""
    print()
    print(
        f"dry run: {report.planned_calls} call{plural} across {len(report.cases)} cases"
        + (f", {options.repeat} repeats each" if options.repeat > 1 else "")
    )
    for model_id, count in sorted(report.planned_by_model.items()):
        print(f"  {model_id:<24}{count:>6}")

    # The plan already resolved the submission, so a dry run is where an
    # ambiguous qtag or a missing signing key shows up -- before the money.
    plan = report.submission_plan
    if plan is not None:
        answered = {qtag: item.case.case_id for qtag, item in plan.chosen.items()}
        print()
        print(f"gradescope submission would be written to {plan.zip_path}")
        for qtag in plan.qtags:
            print(f"  {qtag:<28} {answered.get(qtag, '(unanswered, scores 0)')}")
        if plan.digitalsign:
            print("  signed with LLMGRADER_PRIVATE_KEY")
        if plan.optional_case_ids:
            print(
                f"  note: {len(plan.optional_case_ids)} case(s) answer optional questions and "
                f"are not in the submission ({', '.join(plan.optional_case_ids)}); the portal "
                "submits required questions only."
            )

    print("no API calls were made")


def _score_column(case) -> str:
    """The middle column: a score and its band, or a pass/fail verdict."""
    attempt = case.attempts[0] if case.attempts else None
    if attempt is None:
        return ""
    if attempt.error is not None:
        return "error"

    if not case.partial_credit:
        results = [str(one.result) for one in case.attempts]
        return " ".join(dict.fromkeys(results))

    bands = attempt.expectations.get("points") or []
    if not bands:
        scores = [f"{one.points:g}" if one.points is not None else "-" for one in case.attempts]
        return " ".join(scores)

    # One segment per asserted part, so a multi-part question does not show
    # the question total against a single part's band.
    segments = []
    for band in bands:
        label = band["label"]
        scored = " ".join(
            f"{one.part_scores.get(label):g}" if one.part_scores.get(label) is not None else "-"
            for one in case.attempts
        )
        low = "" if band["min"] is None else f"{band['min']:g}"
        high = "" if band["max"] is None else f"{band['max']:g}"
        prefix = "" if len(bands) == 1 and label == "all" else f"{label}="
        segments.append(f"{prefix}{scored} [{low}-{high}]")
    return "  ".join(segments)


def _margin_column(case) -> str:
    if case.verdict == VERDICT_FLAKY:
        return f"{case.pass_count}/{len(case.attempts)} passed"
    margins = [one.margin for one in case.attempts if one.margin is not None]
    if not margins:
        return ""
    return f"margin {min(margins):g}"


def _print_case_line(case) -> None:
    print(
        f"  {case.verdict:<6}{case.case_id:<28}{case.qtag:<26}"
        f"{_score_column(case):<22}{_margin_column(case):<16}{case.model}"
    )
    if case.verdict == VERDICT_WARN:
        print("        on the band edge; widen the band or accept flakiness")
    if case.verdict in FAILING_VERDICTS:
        if case.description.strip():
            print(f"        {' '.join(case.description.split())}")
        for attempt in case.attempts:
            if attempt.error is not None:
                print(f"        {attempt.error}")
            for failure, evidence in attempt.failure_lines():
                print(f"        {failure}")
                if evidence:
                    print(f'        evidence: "{" ".join(evidence.split())}"')
            break  # the first attempt's failures are enough to locate the problem


def _stream_case(case) -> None:
    _print_case_line(case)


def _print_run_report(report, options: RunOptions, *, streamed: bool) -> None:
    if streamed:
        return
    for file_run in report.files:
        print()
        print(f"{file_run.path}  (unit: {file_run.unit_file}, {len(file_run.cases)} cases)")
        print()
        for case in file_run.cases:
            _print_case_line(case)


def _print_run_summary(report, options: RunOptions) -> None:
    verdicts = report.verdicts
    parts = [
        f"{verdicts.get(VERDICT_PASS, 0)} passed",
        f"{verdicts.get(VERDICT_FAIL, 0)} failed",
    ]
    if verdicts.get(VERDICT_FLAKY):
        parts.append(f"{verdicts[VERDICT_FLAKY]} flaky")
    if verdicts.get(VERDICT_ERROR):
        parts.append(f"{verdicts[VERDICT_ERROR]} errored")
    if verdicts.get(VERDICT_WARN):
        parts.append(f"{verdicts[VERDICT_WARN]} warning")

    print()
    print(", ".join(parts))
    print(
        f"{report.calls} calls, {report.elapsed_seconds:.1f} s, "
        f"{report.tokens_in:,} in / {report.tokens_out:,} out"
    )

    # When nothing was graded at all the fault is the run's, not the rubrics'.
    # Say so once, with the first error, instead of leaving it to be inferred
    # from a zero token count.
    attempts = [attempt for file_run in report.files for case in file_run.cases for attempt in case.attempts]
    errored = [attempt for attempt in attempts if attempt.error is not None]
    if attempts and len(errored) == len(attempts):
        first = errored[0].error or ""
        print()
        print(f"no case was graded: all {len(attempts)} attempts errored.")
        print(f"first error: {first.strip().splitlines()[0] if first.strip() else 'unknown'}")

    if options.cost:
        usd, long_rate = report.estimated_cost()
        suffix = " (includes long-context calls: LOWER BOUND)" if long_rate else ""
        print(f"estimated cost ${usd:.4f}{suffix}")
        print(LONG_CONTEXT_CAVEAT)

    if report.report_path:
        print(f"report: {report.report_path}")
    if report.html_path:
        print(f"html:   {report.html_path}")
    if report.kept_db:
        print(f"kept storage: {report.storage_path}")

    _print_submission(report)


def _print_submission(report) -> None:
    """What the submission scored, and which case answered each question.

    The score is the point of it: it is what Gradescope should display back
    after the test upload, so seeing it here is how the instructor knows the
    autograder read the file rather than defaulted to zero.
    """
    if report.submission_error:
        print()
        print(f"gradescope submission not written: {report.submission_error}", file=sys.stderr)
        return

    submission = report.submission
    if submission is None:
        return

    print()
    print(
        f"gradescope submission: {_num(submission.score)}/{_num(submission.max_score)}"
        + ("  (signed)" if submission.signed else "")
    )
    for question in submission.questions:
        answer = f"case {question.case_id}" if question.answered else "unanswered"
        print(
            f"  {question.qtag:<28} {_num(question.score):>4}/{_num(question.max_score):<4} {answer}"
        )
    if submission.zip_path:
        print(f"  folder: {submission.directory}")
        print(f"  zip:    {submission.zip_path}")

    skipped = (report.submission_plan.optional_case_ids if report.submission_plan else []) or []
    if skipped:
        print(
            f"  note: {len(skipped)} case(s) answer optional questions and are not in the "
            f"submission ({', '.join(skipped)}); the portal submits required questions only."
        )


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)

# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        return command_check(args)
    if args.command == "run":
        return command_run(args)

    parser.error(f"unknown command {args.command!r}")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
