"""What goes with what among a course's materials: ``plans/unified_materials.md``.

A helper, not a source of items.  The config makes the items; this module
reads the references the slides and docs pages already make -- a slide reads
"see demos/scalar_fun/scalar_fun_vitis", a docs page says "the files are in
``hwdesign/demos/stream/avgfilt``" -- and derives, every sync, without ever
writing back into the tree:

* **Slides and units**: a slide that cites an item's files links the item to
  that slide and, through the slide's deck, to the deck's units; a deck named
  like the item links the units alone.  That is how an item no config entry
  gives a unit can still have one, and the build prints where each came from.
* **Related items**: a docs page that cites another item's code or pages.
* **The report**: references that point at nothing, or at build output.

The repo's ``materials.xml`` (schema ``llmgrader_materials.xsd``) is parsed
here too, since a commit with a broken one is not served.  Every function is
pure -- a snapshot, slide data and item paths in, links out -- so the build's
check and the server share it.  (``plans/demo_code_mcp.md`` built the first
version of this, for demos alone.)
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

from llmgrader.coursemcp.code import PAGE, TEXT, CodeSnapshot, is_build_output

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "llmgrader_materials.xsd"


class OverridesError(Exception):
    """The repo's ``materials.xml`` is malformed or invalid."""


@dataclass
class SlideRef:
    """What the link graph needs of one lecture slide (or PDF page)."""
    deck: str
    units: tuple[str, ...]
    n: int
    text: str
    links: tuple[str, ...] = ()


@dataclass
class ItemLinks:
    slides: list[dict] = field(default_factory=list)   # {"deck", "slide", "via"}
    units: list[dict] = field(default_factory=list)    # {"unit", "via", "deck"?}
    related: list[str] = field(default_factory=list)

    def add_unit(self, unit: str, via: str, deck: str | None = None) -> None:
        if unit and not any(same_unit(u["unit"], unit) for u in self.units):
            self.units.append({"unit": unit, "via": via, **({"deck": deck} if deck else {})})

    def add_slide(self, deck: str, n: int, via: str) -> None:
        if not any(s["deck"] == deck and s["slide"] == n for s in self.slides):
            self.slides.append({"deck": deck, "slide": n, "via": via})


@dataclass
class LinkReport:
    broken: list[tuple[str, str]] = field(default_factory=list)        # (where, reference)
    build_output: list[tuple[str, str]] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"Broken reference: {where} cites {ref}, which does not exist"
               for where, ref in self.broken]
        out += [f"Build output (fine, but not served): {where} cites {ref}"
                for where, ref in self.build_output]
        return out


@dataclass
class Links:
    items: dict[str, ItemLinks]
    doc_cites: dict[str, list[str]]        # docs page -> the paths it cites
    report: LinkReport


def same_unit(a: str, b: str) -> bool:
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

_PATH_CHARS = r"[\w.\-/]"


def _patterns(snapshot: CodeSnapshot):
    config = snapshot.config
    roots = sorted(config.roots(), key=len, reverse=True)
    alternation = "|".join(re.escape(r) for r in roots) or r"(?!)"
    bare = re.compile(
        rf"(?<![\w/.\-])(?:{re.escape(config.repo_name)}/)?((?:{alternation})(?:/[\w.\-]*[\w\-])*)")
    github = re.compile(
        rf"github\.com/{re.escape(config.owner_repo)}/(?:blob|tree)/[^/\s)\]>\"'`]+/"
        rf"({_PATH_CHARS}*[\w\-])", re.IGNORECASE)
    site = None
    if snapshot.site:
        host_path = re.sub(r"^https?://", "", snapshot.site)
        site = re.compile(rf"{re.escape(host_path)}/({_PATH_CHARS}*[\w\-/])", re.IGNORECASE)
    return bare, github, site


_MD_LINK_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def _site_candidates(page: str) -> list[str]:
    page = page.strip("/")
    if page.endswith(".html"):
        page = page[:-5]
    # The page before the folder: .../procif/ is procif/index.md.
    return [f"{page}.md", f"{page}/index.md", page]


def find_references(text: str, snapshot: CodeSnapshot, *, page: str | None = None,
                    patterns=None) -> list[tuple[int, list[str]]]:
    """Each reference in *text*: ``(line number, [candidate repo paths])``.

    *page* is the docs page *text* comes from, for its relative links.
    """
    bare, github, site = patterns or _patterns(snapshot)
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in bare.finditer(line):
            found.append((number, [match.group(1)]))
        for match in github.finditer(line):
            found.append((number, [match.group(1).rstrip("/")]))
        if site is not None:
            for match in site.finditer(line):
                found.append((number, _site_candidates(match.group(1))))
        if page is not None:
            for match in _MD_LINK_TARGET.finditer(line):
                target = match.group(1).split("#", 1)[0]
                if not target or "://" in target or target.startswith(("/", "mailto:")):
                    continue
                joined = posixpath.normpath(posixpath.join(posixpath.dirname(page), target))
                if joined.startswith(".."):
                    continue
                found.append((number, [joined] if target.endswith(".md")
                              else _site_candidates(joined)))
    return found


def resolve(candidates: list[str], snapshot: CodeSnapshot) -> tuple[str, str]:
    """``(status, path)``: status is file, dir, excluded, build_output, outside or broken."""
    for candidate in candidates:
        path = candidate.strip("/")
        if snapshot.config.format_of(path) is None:
            continue    # above or beside the includes: a site root names no item
        if snapshot.served(path):
            return "file", path
        if path in snapshot.served_dirs:
            return "dir", path
    for candidate in candidates:
        path = candidate.strip("/")
        if path in snapshot.tree_files or path in snapshot.tree_dirs:
            return "excluded", path
    path = candidates[-1].strip("/")    # as written: the bare page, not page.md
    if snapshot.config.format_of(path) is None:
        return "outside", path
    if is_build_output(path + "/x"):
        return "build_output", path
    return "broken", path


# ---------------------------------------------------------------------------
# The repo's materials.xml
# ---------------------------------------------------------------------------


def parse_overrides(text: str | None):
    """The repo's ``materials.xml`` root element, validated, or None if there is none."""
    if not text or not text.strip():
        return None
    import xml.etree.ElementTree as ET

    import xmlschema

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise OverridesError(f"not well-formed XML: {exc}") from exc
    schema = xmlschema.XMLSchema(str(SCHEMA_PATH))
    errors = []
    for error in schema.iter_errors(text):
        where = f"line {error.sourceline}: " if getattr(error, "sourceline", None) else ""
        errors.append(where + str(error.reason or error))
    if errors:
        raise OverridesError("; ".join(errors))
    return root


# ---------------------------------------------------------------------------
# Linking items
# ---------------------------------------------------------------------------


def _covers(a: str, b: str) -> bool:
    return a == b or b.startswith(a + "/") or a.startswith(b + "/")


def _owns(roots: list[str], path: str) -> bool:
    return any(path == r or path.startswith(r + "/") for r in roots)


def link_items(snapshot: CodeSnapshot | None, slides: list[SlideRef],
               roots: dict[str, list[str]]) -> Links:
    """Derive each item's slides, units and related items.

    *roots* maps an item id to the mirror paths (folders or files) its parts
    are; an item from the package has none, and is linked only by name.
    """
    items = {item_id: ItemLinks() for item_id in roots}
    report = LinkReport()
    doc_cites: dict[str, list[str]] = {}

    def note(status: str, where: str, path: str) -> None:
        if status == "broken":
            report.broken.append((where, path))
        elif status == "build_output":
            report.build_output.append((where, path))

    def owners(path: str, status: str) -> list[str]:
        return [item_id for item_id, item_roots in roots.items()
                if _owns(item_roots, path)
                or (status == "dir" and any(_covers(path, r) for r in item_roots))]

    if snapshot is not None:
        config = snapshot.config
        patterns = _patterns(snapshot)
        top_roots = set(config.roots())

        # What each docs page cites, and the items it points to.
        for item_id, item_roots in roots.items():
            for root in item_roots:
                for page in snapshot.under(root):
                    source = snapshot.files.get(page)
                    if source is None or source.format != PAGE or page in doc_cites:
                        continue
                    text = "\n".join(source.lines)
                    cites: list[str] = []
                    for number, candidates in find_references(text, snapshot, page=page,
                                                              patterns=patterns):
                        status, path = resolve(candidates, snapshot)
                        note(status, f"{page}:{number + source.first_line - 1}", path)
                        if status not in ("file", "dir") or path in top_roots:
                            continue     # citing all of demos/ says nothing
                        if config.format_of(path) == TEXT and path not in cites:
                            cites.append(path)
                        for other in owners(path, status):
                            if other != item_id and other not in items[item_id].related:
                                items[item_id].related.append(other)
                    doc_cites[page] = cites

        # Slides that cite an item.
        for slide in slides:
            where = f"slide {slide.deck}:{slide.n}"
            refs = find_references(slide.text, snapshot, patterns=patterns)
            for link in slide.links:
                refs += find_references(link, snapshot, patterns=patterns)
            for _, candidates in refs:
                status, path = resolve(candidates, snapshot)
                note(status, where, path)
                if status not in ("file", "dir") or path in top_roots:
                    continue
                for item_id in owners(path, status):
                    via = f"{where} cites {path}"
                    items[item_id].add_slide(slide.deck, slide.n, via)
                    for unit in slide.units:
                        items[item_id].add_unit(unit, via, slide.deck)

    # Decks with an item's name.
    deck_units: dict[str, tuple[str, ...]] = {}
    for slide in slides:
        deck_units.setdefault(slide.deck, slide.units)
    for item_id, item_roots in roots.items():
        if not item_roots:
            continue        # a package item: the deck of its name is itself
        names = {item_id} | {posixpath.basename(r) for r in item_roots}
        for deck, units in deck_units.items():
            if deck in names:
                for unit in units:
                    items[item_id].add_unit(unit, f"deck {deck} has the item's name", deck)

    for links in items.values():
        links.slides.sort(key=lambda s: (s["deck"], s["slide"]))
    return Links(items, doc_cites, report)
