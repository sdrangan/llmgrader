"""llmgrader_mcp_build: build the course MCP's material into a package.

    llmgrader_mcp_build --dry-run                       # list what would be published
    llmgrader_mcp_build --package soln_package          # build into an extracted package
    llmgrader_mcp_build --root pub=../hwdesign ...      # override a <root> path

    llmgrader_mcp_build --materials                     # print the index the portal will serve
    llmgrader_mcp_build --links                         # check the links slides and docs make

    llmgrader_mcp_build --describe --dry-run            # count slides to describe, estimate cost
    llmgrader_mcp_build --describe                      # describe them (OpenAI; costs money)
    llmgrader_mcp_build --describe --deck fsm --force   # redo one deck's descriptions

``create_soln_pkg`` runs the same build when ``llmgrader_mcp_config.xml`` sits
beside ``llmgrader_config.xml``, so this is mostly for checking what will be
published, and for --describe.

--materials prints every item the course MCP will serve (plans/unified_materials.md):
its kind, its units and where each came from -- the config, the repo's
materials.xml, or a slide that cites it -- and its parts and their formats.
Mirrored items are resolved against the local checkout that <code root=...>
names, exactly as the portal will resolve them against its copy; package
items come from --package when it has been built, or from a build into a
temporary folder.  --links prints the references in slides and docs pages
that point at nothing.  Both are free, and build nothing into --package.

The build fails, naming them, on a refinement (<item id>) that matches no
item and on an item with no unit; with no local checkout, the mirrored items
cannot be checked here, and the portal reports them when it syncs.

--describe asks a vision model to describe each slide's (and each PDF
page's) figures, so that search_materials can find a topic that appears only
in a diagram.  The results go to llmgrader_mcp_descriptions/, one JSON file
per deck in slide order, beside the config -- commit it -- matched to slides
by each image's content, so a slide is paid for once, and every later build
(including create_soln_pkg) reads it for free.  After editing slides, plain
--describe redoes just the ones whose image changed; --force redoes slides
that already have a description (a better --model, or a poor result).  Only
slides with an image can be described: a deck with no PDF, or a stale one,
is skipped.  Mirrored PDFs are rendered by the portal and not described.

Needs python-pptx and PyMuPDF: ``pip install "llmgrader[mcp-build]"``;
--describe also needs OPENAI_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from llmgrader.coursemcp.materials import (
    FORMAT_VERSION,
    MANIFEST,
    MATERIALS_DIR,
    MaterialsError,
    build_materials,
    describe_slides,
    descriptions_dir,
    estimate_cost,
    load_descriptions,
    plan_descriptions,
    portal_unit_names,
    read_code,
    read_materials,
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


def unit_names(config, roots) -> list[str]:
    """Every unit an item may name besides the material units."""
    return portal_unit_names(config) + [u.name for u in read_units(config, roots)]


def check_materials(config, roots: dict, spec, code, package_dir, *, log=print,
                    strict: bool = True):
    """Build the index the portal will serve from *package_dir* and the local
    checkout, report what it finds, and raise MaterialsError on what fails
    the build.  Returns the catalog."""
    from llmgrader.coursemcp.catalog import catalog_problems, local_catalog

    mirrored = any(item.source == "mirror" for item in spec.items) or spec.patterns
    local_root = code.local_root if code is not None else None
    if mirrored and local_root is None:
        log("  No local checkout of the mirrored repo (<code root=...>): its items are "
            "checked by the portal when it syncs, not here.")
    catalog = local_catalog(code.config if code else None, local_root, package_dir,
                            unit_names(config, roots))
    if local_root is None:
        catalog.report = [r for r in catalog.report if "has not been fetched" not in r]
    problems = catalog_problems(catalog)
    if local_root is None:
        # Pattern items are not there to refine or to have units.
        problems = [p for p in problems if "matches no item" not in p]
        missing = [i.id for i in catalog.items.values() if not i.units]
        problems = [p for p in problems if not p.startswith("every item needs a unit")]
        if missing:
            problems.append("every item needs a unit; these have none: " + ", ".join(missing))
    for line in catalog.report:
        if line not in problems:
            log(f"  {line}")
    if problems and strict:
        raise MaterialsError("; ".join(problems))
    return catalog, problems


def built_package(args, spec, code) -> tuple[str, tempfile.TemporaryDirectory | None]:
    """--package when it has been built, else a build into a temporary folder."""
    manifest = Path(args.package) / MATERIALS_DIR / MANIFEST
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version", 1)
    except (OSError, ValueError):
        version = None
    if version == FORMAT_VERSION:
        return args.package, None
    work = tempfile.TemporaryDirectory()
    print(f"({args.package} has not been built" + (" since <materials>" if version else "")
          + ": building the package items into a temporary folder)")
    build_materials(spec, work.name, log=lambda *_: None,
                    descriptions=load_descriptions(descriptions_dir(args.config)),
                    units=read_units(args.config, parse_roots(args.root)),
                    unit_types=read_unit_types(args.config),
                    code=code.config if code else None)
    return work.name, work


def run_report(args, spec) -> int:
    from llmgrader.coursemcp.catalog import catalog_lines

    roots = parse_roots(args.root)
    code = read_code(args.config, roots, spec=spec)
    package, work = built_package(args, spec, code)
    try:
        catalog, problems = check_materials(args.config, roots, spec, code, package,
                                            log=lambda *_: None, strict=False)
        if args.materials:
            for line in catalog_lines(catalog):
                print(f"  {line}")
        else:
            lines = [line for line in catalog.report if line not in problems]
            print(f"  {len(lines)} reference problem(s)" + (":" if lines else "."))
            for line in lines:
                print(f"  {line}")
    finally:
        if work is not None:
            work.cleanup()
    for problem in problems:
        print(f"Error: {problem}", file=sys.stderr)
    return 1 if problems else 0


def print_dry_run(args, spec) -> None:
    print(f"Would publish {len(spec.items)} explicit item(s) in {len(spec.kinds)} kind(s):")
    for item in spec.items:
        policy = spec.policy(item.kind)
        print(f"  [{item.id}] {item.kind} ({item.source})"
              + (f", {policy}: listed only" if policy == "private" else "")
              + f"  units: {'; '.join(item.units) or '-'}")
        for part in item.parts:
            print(f"      {part.source_path or part.path}" + (f"  (pdf {part.pdf})" if part.pdf else ""))
    for pattern in spec.patterns:
        print(f"  <items kind={pattern['kind']!r}> one per folder of {pattern['path']}"
              + (f" with {pattern['docs']}" if pattern["docs"] else "") + " in the mirror")
    units = read_units(args.config, parse_roots(args.root))
    if units:
        print(f"Would publish {len(units)} unit(s) to the MCP only:")
        for unit in units:
            print(f"  [{unit.name}]" + (f" section={unit.section!r}" if unit.section else ""))
            print(f"      {unit.path}")
    code = read_code(args.config, parse_roots(args.root), spec=spec)
    if code is not None:
        print(f"Would point the MCP at {code.config['repo']} ({code.config['branch']}): "
              + ", ".join(i["path"] for i in code.config["includes"])
              + " -- synced by the portal, not packaged")
    print("\nNothing else from these repositories is published.")


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
    parser.add_argument("--materials", action="store_true",
                        help="print every item the portal will serve, its units and parts "
                             "(free; builds nothing into --package)")
    parser.add_argument("--links", action="store_true",
                        help="report references in slides and docs pages that point at "
                             "nothing (free; builds nothing into --package)")
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
    # Titles come from the course's own pages and slides, in any script;
    # a Windows console or a redirect would otherwise be cp1252 and fail on them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    try:
        roots = parse_roots(args.root)
        spec = read_materials(args.config, roots)
        specs = spec.decks
        if (args.deck or args.force or args.redo_empty) and not args.describe:
            raise MaterialsError("--deck, --force and --redo-empty go with --describe")
        if args.deck:
            known = {deck.id for deck in specs}
            unknown = [d for d in args.deck if d not in known]
            if unknown:
                raise MaterialsError(f"unknown deck(s) {', '.join(unknown)}; "
                                     f"decks in the config: {', '.join(sorted(known))}")
            specs = [deck for deck in specs if deck.id in args.deck]
        if args.materials or args.links:
            return run_report(args, spec)
        if args.describe:
            return run_describe(args, specs)
        if args.dry_run:
            print_dry_run(args, spec)
            return 0
        print(f"Building course MCP material into {args.package}:")
        code = read_code(args.config, roots, spec=spec)
        build_materials(spec, args.package,
                        descriptions=load_descriptions(descriptions_dir(args.config)),
                        units=read_units(args.config, roots),
                        unit_types=read_unit_types(args.config),
                        code=code.config if code else None)
        check_materials(args.config, roots, spec, code, args.package)
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
