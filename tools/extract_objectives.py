#!/usr/bin/env python
"""Pull the "Learning Objectives" slide out of every unit deck.

Phase 0a of `plans/course_mcp.md` drafts the skill taxonomy from the objectives
slides rather than from the lectures, because those slides exist for every unit
including the ones that have not been reworked yet. This is the extraction half
of that step; the clustering and the cut are done by hand against the output.

    python tools/extract_objectives.py <course_repo>/units

A `.pptx` is a zip of XML. Slide text lives in `<a:t>` runs inside
`ppt/slides/slideN.xml`, so the whole job is "unzip, find the slide whose runs
mention learning objectives, print its runs in order". PowerPoint splits a
single bullet across several runs wherever formatting changes -- a bolded term
mid-sentence is its own run -- so the runs are printed one per line and the
reader reassembles the bullet. Trying to re-join them here would need the
paragraph (`<a:p>`) boundaries and is not worth it for a step that is read once.

Editing and temp files (`~$deck.pptx`) and superseded versions (`*_v1.pptx`)
are skipped, since both would otherwise contribute stale objectives.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import zipfile

# stdout on Windows is cp1252 unless told otherwise, and a deck with a
# non-breaking hyphen then kills the run mid-unit. See
# grading-py-unicode-crash-on-cp1252: the failure looks like a parsing bug and
# is not one.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUN_RE = re.compile(r"<a:t>(.*?)</a:t>", re.S)
SLIDE_RE = re.compile(r"ppt/slides/slide(\d+)\.xml$")
TAG_RE = re.compile(r"<.*?>")
HEADING_RE = re.compile(r"learning\s+objective", re.I)


def slide_runs(archive: zipfile.ZipFile, name: str) -> list[str]:
    xml = archive.read(name).decode("utf-8", "ignore")
    return [TAG_RE.sub("", run).strip() for run in RUN_RE.findall(xml)]


def objectives_slide(path: pathlib.Path) -> tuple[str, list[str]] | None:
    """`(slide name, runs)` for the first slide that looks like the objectives."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        print(f"!! {path}: {exc}", file=sys.stderr)
        return None

    slides = sorted(
        (n for n in archive.namelist() if SLIDE_RE.match(n)),
        key=lambda n: int(SLIDE_RE.match(n).group(1)),
    )
    for name in slides:
        runs = slide_runs(archive, name)
        if HEADING_RE.search(" ".join(runs)):
            return name, [r for r in runs if r]
    return None


def decks(units_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(
        p for p in units_dir.glob("*/*.pptx")
        if not p.name.startswith("~$") and "_v1" not in p.name
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("units_dir", type=pathlib.Path,
                        help="the course repo's units/ directory")
    args = parser.parse_args()

    if not args.units_dir.is_dir():
        print(f"Not a directory: {args.units_dir}", file=sys.stderr)
        return 2

    found = 0
    for deck in decks(args.units_dir):
        hit = objectives_slide(deck)
        if hit is None:
            print(f"\n=== {deck.parent.name} [{deck.name}] -- no objectives slide ===")
            continue
        slide, runs = hit
        found += 1
        print(f"\n=== {deck.parent.name} [{deck.name} {slide}] ===")
        for run in runs:
            print("  -", run)

    print(f"\n{found} deck(s) with an objectives slide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
