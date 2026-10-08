"""llmgrader_mcp_build: build the course MCP's material into a package.

    llmgrader_mcp_build --dry-run                       # list what would be published
    llmgrader_mcp_build --package soln_package          # build into an extracted package
    llmgrader_mcp_build --root pub=../hwdesign ...      # override a <root> path

    llmgrader_mcp_build --describe --dry-run            # count slides to describe, estimate cost
    llmgrader_mcp_build --describe                      # describe them (OpenAI; costs money)
    llmgrader_mcp_build --describe --deck fsm --force   # redo one deck's descriptions

``create_soln_pkg`` runs the same build when ``llmgrader_mcp_config.xml`` sits
beside ``llmgrader_config.xml``, so this is mostly for checking what will be
published, and for --describe.

--describe asks a vision model to describe each slide's figures, so that
search_slides can find a topic that appears only in a diagram.  The results
go to llmgrader_mcp_descriptions/, one JSON file per deck in slide order,
beside the config -- commit it -- matched to slides by each image's content, so a slide is paid for once, and every later
build (including create_soln_pkg) reads it for free.  After editing slides,
plain --describe redoes just the ones whose image changed; --force redoes
slides that already have a description (a better --model, or a poor result).  Only slides with an
image can be described: a deck with no PDF, or a stale one, is skipped.

Needs python-pptx and PyMuPDF: ``pip install "llmgrader[mcp-build]"``;
--describe also needs OPENAI_API_KEY.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from llmgrader.coursemcp.materials import (
    MaterialsError,
    build_materials,
    describe_slides,
    descriptions_dir,
    estimate_cost,
    load_descriptions,
    plan_descriptions,
    read_config,
    read_unit_types,
    read_units,
    sync_descriptions,
)

DEFAULT_CONFIG = "llmgrader_mcp_config.xml"


def parse_roots(values: list[str]) -> dict[str, str]:
    roots = {}
    for value in values:
        root_id, sep, path = value.partition("=")
        if not sep or not root_id or not path:
            raise MaterialsError(f"--root expects id=path, got {value!r}")
        roots[root_id] = path
    return roots


def resolve_model(value: str):
    from llmgrader.services.models import resolve_preferred_model

    spec = resolve_preferred_model(value)
    if spec is None:
        raise MaterialsError(f"--model {value!r} is neither a tier nor a supported model id")
    if not spec.supports_images:
        raise MaterialsError(f"--model {spec.id} does not accept images")
    return spec


def run_describe(args, specs) -> int:
    model = resolve_model(args.model)
    directory = descriptions_dir(args.config)
    with tempfile.TemporaryDirectory() as work:
        print("Rendering slides to find the ones not yet described...")
        cache = load_descriptions(directory)
        plan = plan_descriptions(specs, cache, work, force=args.force,
                                 redo_empty=args.redo_empty)
        for deck_id in plan.text_only_decks:
            print(f"  [{deck_id}] skipped: no usable PDF, so no images to describe")
        cost = estimate_cost(model, len(plan.todo))
        print(f"\n{len(plan.todo)} slide(s) to describe, {plan.cached} already described "
              f"in {directory.name}/.")
        if plan.replacing:
            print(f"{plan.replacing} of them already have a description, "
                  "which will be replaced.")
        print(f"Model {model.id}: estimated ${cost:.2f} "
              f"(~{len(plan.todo)} calls; the estimate assumes a typical slide).")
        if args.dry_run:
            return 0
        if not plan.todo:
            # Nothing to buy, but the deck files are still brought up to date:
            # renumbered after slides moved, or split out of a legacy file.
            sync_descriptions(plan, directory, cache)
            print(f"Nothing to describe; {directory.name}/ is up to date.")
            return 0
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise MaterialsError("OPENAI_API_KEY is not set")
        if not args.yes:
            answer = input(f"Spend about ${cost:.2f} describing {len(plan.todo)} slide(s)? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                print("Nothing spent.")
                return 0
        described, spent = describe_slides(plan, directory, model_spec=model, api_key=api_key)
        print(f"\nDescribed {described} slide(s) for ${spent:.2f}; saved in {directory}.")
        print(f"Commit {directory.name}/, then rebuild the package (create_soln_pkg) "
              "to include them.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help=f"the MCP config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--package", default="soln_package",
                        help="the extracted course package to build into (default: soln_package)")
    parser.add_argument("--root", action="append", default=[], metavar="ID=PATH",
                        help="override a <root> path; may be repeated")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen, and build or spend nothing")
    parser.add_argument("--describe", action="store_true",
                        help="describe each slide's figures with a vision model (costs money)")
    parser.add_argument("--model", default="simple",
                        help="model for --describe: a tier or a model id (default: simple)")
    parser.add_argument("--yes", action="store_true",
                        help="with --describe, do not ask before spending")
    parser.add_argument("--force", action="store_true",
                        help="with --describe, redo slides that already have a description "
                             "(not needed after editing slides: changed slides are redone anyway)")
    parser.add_argument("--redo-empty", action="store_true",
                        help="with --describe, redo only slides whose description is empty "
                             "(judged text-only)")
    parser.add_argument("--deck", action="append", default=[], metavar="ID",
                        help="with --describe, only these decks (by id); may be repeated")
    args = parser.parse_args(argv)

    try:
        specs = read_config(args.config, parse_roots(args.root))
        if (args.deck or args.force or args.redo_empty) and not args.describe:
            raise MaterialsError("--deck, --force and --redo-empty go with --describe")
        if args.deck:
            known = {spec.id for spec in specs}
            unknown = [d for d in args.deck if d not in known]
            if unknown:
                raise MaterialsError(f"unknown deck(s) {', '.join(unknown)}; "
                                     f"decks in the config: {', '.join(sorted(known))}")
            specs = [spec for spec in specs if spec.id in args.deck]
        if args.describe:
            return run_describe(args, specs)
        if args.dry_run:
            print(f"Would publish {len(specs)} slide deck(s):")
            for spec in specs:
                print(f"  [{spec.id}] unit={spec.unit!r}")
                print(f"      {spec.pptx}")
                if spec.pdf:
                    print(f"      {spec.pdf}")
            units = read_units(args.config, parse_roots(args.root))
            if units:
                print(f"Would publish {len(units)} unit(s) to the MCP only:")
                for unit in units:
                    print(f"  [{unit.name}]" + (f" section={unit.section!r}" if unit.section else ""))
                    print(f"      {unit.path}")
            print("\nNothing else from these repositories is published.")
            return 0
        print(f"Building course MCP material into {args.package}:")
        build_materials(specs, args.package,
                        descriptions=load_descriptions(descriptions_dir(args.config)),
                        units=read_units(args.config, parse_roots(args.root)),
                        unit_types=read_unit_types(args.config))
    except MaterialsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"Error: {exc}. Install the build dependencies: "
              'pip install "llmgrader[mcp-build]"', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
