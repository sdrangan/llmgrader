"""llmgrader_mcp_build: build the course MCP's slide material into a package.

    llmgrader_mcp_build --dry-run                       # list what would be published
    llmgrader_mcp_build --package soln_package          # build into an extracted package
    llmgrader_mcp_build --root pub=../hwdesign ...      # override a <root> path

``create_soln_pkg`` runs the same build when ``llmgrader_mcp_config.xml`` sits
beside ``llmgrader_config.xml``, so this is mostly for checking what will be
published, and for rebuilding the slides of an existing package.

Needs python-pptx and PyMuPDF: ``pip install "llmgrader[mcp-build]"``.
"""

from __future__ import annotations

import argparse
import sys

from llmgrader.coursemcp.materials import MaterialsError, build_materials, read_config

DEFAULT_CONFIG = "llmgrader_mcp_config.xml"


def parse_roots(values: list[str]) -> dict[str, str]:
    roots = {}
    for value in values:
        root_id, sep, path = value.partition("=")
        if not sep or not root_id or not path:
            raise MaterialsError(f"--root expects id=path, got {value!r}")
        roots[root_id] = path
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help=f"the MCP config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--package", default="soln_package",
                        help="the extracted course package to build into (default: soln_package)")
    parser.add_argument("--root", action="append", default=[], metavar="ID=PATH",
                        help="override a <root> path; may be repeated")
    parser.add_argument("--dry-run", action="store_true",
                        help="list every file that would be published, and build nothing")
    args = parser.parse_args(argv)

    try:
        specs = read_config(args.config, parse_roots(args.root))
        if args.dry_run:
            print(f"Would publish {len(specs)} slide deck(s):")
            for spec in specs:
                print(f"  [{spec.id}] unit={spec.unit!r}")
                print(f"      {spec.pptx}")
                if spec.pdf:
                    print(f"      {spec.pdf}")
            print("\nNothing else from these repositories is published.")
            return 0
        print(f"Building slide material into {args.package}:")
        build_materials(specs, args.package)
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
