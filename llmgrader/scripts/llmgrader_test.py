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
    LEVEL_ERROR,
    CheckResult,
    GradeTestError,
    PackageContext,
    check_file,
    expand_paths,
    load_test_file,
    load_unit,
    resolve_unit_path,
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
# entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        return command_check(args)

    parser.error(f"unknown command {args.command!r}")
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
