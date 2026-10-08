"""Which demo is which, and what goes with it: ``plans/demo_code_mcp.md``, decision 3.

Nothing here is written by hand unless it has to be.  The slides and the docs
pages already say what goes with what -- a slide reads "see
demos/scalar_fun/scalar_fun_vitis", a docs page says "the files are in
``hwdesign/demos/stream/avgfilt``" -- so the link graph is built from those
references, every sync, and never written back into the tree:

* **A documented demo** is a docs topic folder (``docs/demos/<topic>/``), with
  the code its pages cite and the ``demos/`` directory of the same name.
* **A code-only demo** is a top-level code directory no documented demo
  covers.
* **Slides and units**: a slide that cites a demo's code or docs links the
  demo to that slide and, through its deck, to a unit; a deck with the
  demo's name links the unit alone.

``demos/demos.xml`` in the repo (optional) fills in what no slide or page
says, removes a wrong automatic link, or hides a demo.  Every function here
is pure -- a snapshot and slide data in, an index out -- so the build's link
report and the server share it.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

from llmgrader.coursemcp.code import CodeSnapshot, is_build_output

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "llmgrader_demos.xsd"
MAX_OVERRIDE_SLIDES = 60


class OverridesError(Exception):
    """``demos/demos.xml`` is malformed or invalid."""


@dataclass
class SlideRef:
    """What the link graph needs of one lecture slide."""
    deck: str
    unit: str
    n: int
    text: str
    links: tuple[str, ...] = ()


def slides_from_materials(materials) -> list[SlideRef]:
    """Every slide of the course's packaged decks, or [] if there are none."""
    if materials is None:
        return []
    slides = []
    for meta in materials.decks:
        deck = materials.deck(meta["id"])
        if not deck:
            continue
        for slide in deck["slides"]:
            text = "\n".join([slide.get("title", ""), slide.get("text", ""),
                              slide.get("notes", ""), slide.get("description", "")])
            slides.append(SlideRef(meta["id"], meta.get("unit", ""), slide["n"], text,
                                   tuple(slide.get("links") or ())))
    return slides


@dataclass
class Demo:
    id: str
    title: str = ""
    description: str = ""
    documented: bool = False
    docs: list[str] = field(default_factory=list)     # docs page paths, in nav order
    docs_dir: str | None = None
    code: list[str] = field(default_factory=list)     # code directories
    units: list[dict] = field(default_factory=list)   # {"unit", "via", "deck"?}
    slides: list[dict] = field(default_factory=list)  # {"deck", "slide", "via"}
    related: list[str] = field(default_factory=list)
    hidden: bool = False

    def owns(self, path: str) -> bool:
        if path in self.docs:
            return True
        return any(path == d or path.startswith(d + "/") for d in self.code)

    def add_unit(self, unit: str, via: str, deck: str | None = None) -> None:
        if unit and not any(_same_unit(u["unit"], unit) for u in self.units):
            self.units.append({"unit": unit, "via": via, **({"deck": deck} if deck else {})})

    def add_slide(self, deck: str, n: int, via: str) -> None:
        if not any(s["deck"] == deck and s["slide"] == n for s in self.slides):
            self.slides.append({"deck": deck, "slide": n, "via": via})


@dataclass
class LinkReport:
    broken: list[tuple[str, str]] = field(default_factory=list)        # (where, reference)
    build_output: list[tuple[str, str]] = field(default_factory=list)
    unknown_overrides: list[str] = field(default_factory=list)

    def lines(self, index: "DemoIndex") -> list[str]:
        out = [f"{len(index.visible())} demo(s):"]
        for demo in index.visible():
            units = ", ".join(u["unit"].split(":")[0] for u in demo.units) or "NO UNIT"
            slides = ", ".join(f"{s['deck']} {s['slide']}" for s in demo.slides) or "-"
            out.append(f"  {demo.id:<14} docs {len(demo.docs):>2}  code {', '.join(demo.code) or '-'}")
            out.append(f"  {'':<14} slides {slides}; unit {units}")
        missing_unit = [d.id for d in index.visible() if not d.units]
        missing_desc = [d.id for d in index.visible() if not d.description]
        if missing_unit:
            out.append("Demos with no unit (add a slide link, or <unit> in the overrides file): "
                       + ", ".join(missing_unit))
        if missing_desc:
            out.append("Demos with no description: " + ", ".join(missing_desc))
        for where, ref in self.broken:
            out.append(f"Broken reference: {where} cites {ref}, which does not exist")
        for where, ref in self.build_output:
            out.append(f"Build output (fine, but not served): {where} cites {ref}")
        for problem in self.unknown_overrides:
            out.append(f"Overrides: {problem}")
        return out


@dataclass
class DemoIndex:
    demos: dict[str, Demo]
    report: LinkReport
    doc_cites: dict[str, list[str]] = field(default_factory=dict)  # docs page -> code it cites

    def visible(self) -> list[Demo]:
        return [d for d in self.demos.values() if not d.hidden]

    def demos_for_path(self, path: str) -> list[str]:
        return [d.id for d in self.visible() if d.owns(path)]

    def demos_for_slide(self, deck: str, n: int) -> list[Demo]:
        return [d for d in self.visible() if any(s["deck"] == deck and s["slide"] == n
                                                 for s in d.slides)]

    def files_of(self, demo: Demo, snapshot: CodeSnapshot) -> list[str]:
        code = sorted(p for p in snapshot.files
                      if p not in demo.docs and any(p == d or p.startswith(d + "/") for d in demo.code))
        return list(demo.docs) + code


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
        if snapshot.config.kind_of(path) is None:
            continue    # above or beside the includes: a site root names no demo
        if path in snapshot.files:
            return "file", path
        if path in snapshot.served_dirs:
            return "dir", path
    for candidate in candidates:
        path = candidate.strip("/")
        if path in snapshot.tree_files or path in snapshot.tree_dirs:
            return "excluded", path
    path = candidates[-1].strip("/")    # as written: the bare page, not page.md
    if snapshot.config.kind_of(path) is None:
        return "outside", path
    if is_build_output(path + "/x"):
        return "build_output", path
    return "broken", path


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def parse_overrides(text: str | None):
    """The overrides file's root element, validated, or None if there is none."""
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
# The index
# ---------------------------------------------------------------------------


def _same_unit(a: str, b: str) -> bool:
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


def _nav_key(snapshot: CodeSnapshot, path: str):
    source = snapshot.files[path]
    try:
        order = float(source.meta.get("nav_order", ""))
    except ValueError:
        order = float("inf")
    return (posixpath.basename(path) != "index.md", order, source.title.lower(), path)


def _readme(snapshot: CodeSnapshot, directory: str):
    readmes = [p for p in snapshot.files
               if p.startswith(directory + "/") and posixpath.basename(p).lower() == "readme.md"]
    return snapshot.files[min(readmes, key=lambda p: (p.count("/"), p))] if readmes else None


def _covers(a: str, b: str) -> bool:
    return a == b or b.startswith(a + "/") or a.startswith(b + "/")


def build_index(snapshot: CodeSnapshot, slides: list[SlideRef]) -> DemoIndex:
    """Derive the demos and their links.  Raises OverridesError on a bad overrides file."""
    config = snapshot.config
    patterns = _patterns(snapshot)
    report = LinkReport()
    demos: dict[str, Demo] = {}
    doc_cites: dict[str, list[str]] = {}
    code_roots = config.roots("code")

    def note(status: str, where: str, path: str) -> None:
        if status == "broken":
            report.broken.append((where, path))
        elif status == "build_output":
            report.build_output.append((where, path))

    # Documented demos: one per docs topic folder.
    same_name: dict[str, str] = {}
    for root in config.roots("doc"):
        topics = sorted({p[len(root) + 1:].split("/", 1)[0] for p in snapshot.files
                         if p.startswith(root + "/") and p[len(root) + 1:].count("/") >= 1})
        for topic in topics:
            prefix = f"{root}/{topic}/"
            pages = sorted((p for p in snapshot.files if p.startswith(prefix)),
                           key=lambda p: _nav_key(snapshot, p))
            index_page = snapshot.files.get(prefix + "index.md") or snapshot.files[pages[0]]
            demo = demos.setdefault(topic, Demo(
                id=topic, title=index_page.title, description=index_page.first_paragraph(),
                documented=True, docs=pages, docs_dir=prefix.rstrip("/")))
            for code_root in code_roots:
                directory_named = f"{code_root}/{topic}"
                if directory_named in snapshot.served_dirs and directory_named not in demo.code:
                    demo.code.append(directory_named)
                    same_name[topic] = directory_named

    # What each docs page cites.
    for demo in list(demos.values()):
        for page in demo.docs:
            text = "\n".join(snapshot.files[page].lines)
            first = snapshot.files[page].first_line
            cites: list[str] = []
            for number, candidates in find_references(text, snapshot, page=page, patterns=patterns):
                status, path = resolve(candidates, snapshot)
                note(status, f"{page}:{number + first - 1}", path)
                if status not in ("file", "dir"):
                    continue
                if config.kind_of(path) == "code":
                    directory = posixpath.dirname(path) if status == "file" else path
                    if directory in code_roots:
                        continue        # citing all of demos/ says nothing
                    if path not in cites:
                        cites.append(path)
                    if directory not in demo.code:
                        demo.code.append(directory)    # nesting is pruned below
                elif config.kind_of(path) == "doc":
                    for other in demos.values():
                        if other.id != demo.id and other.docs_dir and (
                                path.startswith(other.docs_dir + "/") or path == other.docs_dir):
                            if other.id not in demo.related:
                                demo.related.append(other.id)
            doc_cites[page] = cites

    # A same-name directory that holds another demo's cited code is a folder
    # of demos (demos/stream holds avgfilt and poly), not this demo's code.
    for demo in demos.values():
        directory = same_name.get(demo.id)
        if directory and any(other is not demo and any(d.startswith(directory + "/") for d in other.code)
                             for other in demos.values()):
            demo.code.remove(directory)
    for demo in demos.values():
        demo.code = _outermost(demo.code)

    # Code-only demos: top-level code directories no documented demo covers.
    covered = [d for demo in demos.values() for d in demo.code]
    for code_root in code_roots:
        tops = sorted({p[len(code_root) + 1:].split("/", 1)[0] for p in snapshot.files
                       if p.startswith(code_root + "/") and p[len(code_root) + 1:].count("/") >= 1})
        for top in tops:
            directory = f"{code_root}/{top}"
            if any(_covers(directory, d) for d in covered):
                continue
            demo_id = top if top not in demos else f"{top}-code"
            readme = _readme(snapshot, directory)
            demos[demo_id] = Demo(
                id=demo_id, code=[directory],
                title=readme.title if readme else top,
                description=readme.first_paragraph() if readme else "")

    # Slides that cite a demo.
    deck_units: dict[str, str] = {}
    for slide in slides:
        deck_units.setdefault(slide.deck, slide.unit)
        where = f"slide {slide.deck}:{slide.n}"
        refs = find_references(slide.text, snapshot, patterns=patterns)
        for link in slide.links:
            refs += find_references(link, snapshot, patterns=patterns)
        for _, candidates in refs:
            status, path = resolve(candidates, snapshot)
            note(status, where, path)
            if status not in ("file", "dir") or path in config.roots():
                continue
            for demo in demos.values():
                if demo.owns(path) or (status == "dir" and any(_covers(path, d) for d in demo.code)) \
                        or (demo.docs_dir and _covers(path, demo.docs_dir)):
                    via = f"{where} cites {path}"
                    demo.add_slide(slide.deck, slide.n, via)
                    demo.add_unit(slide.unit, via, slide.deck)

    # Decks with a demo's name.
    for deck, unit in deck_units.items():
        for demo in demos.values():
            names = {demo.id} | {posixpath.basename(d) for d in demo.code}
            if deck in names:
                demo.add_unit(unit, f"deck {deck} has the demo's name", deck)

    _apply_overrides(parse_overrides(snapshot.overrides_text), demos, deck_units, report)
    for demo in demos.values():
        demo.slides.sort(key=lambda s: (s["deck"], s["slide"]))
    return DemoIndex(demos, report, doc_cites)


def _outermost(directories: list[str]) -> list[str]:
    """*directories* without any that sits inside another, order kept."""
    return [d for d in directories
            if not any(other != d and d.startswith(other + "/") for other in directories)]


def _apply_overrides(root, demos: dict[str, Demo], deck_units: dict[str, str],
                     report: LinkReport) -> None:
    if root is None:
        return
    for elem in root:
        demo_id = elem.get("id")
        demo = demos.get(demo_id)
        if demo is None:
            report.unknown_overrides.append(
                f"<{elem.tag} id={demo_id!r}> matches no demo; demos are: "
                + ", ".join(sorted(demos)))
            continue
        if elem.tag == "hide":
            demo.hidden = True
            continue
        if elem.get("title"):
            demo.title = elem.get("title").strip()
        description = elem.findtext("description")
        if description and description.strip():
            demo.description = " ".join(description.split())
        for unit in elem.findall("unit"):
            # As written: unit names can carry double spaces ("Unit 2:  FSMs").
            demo.add_unit((unit.text or "").strip(), "demos.xml")
        for removed in elem.findall("not_slides"):
            deck = removed.get("deck")
            demo.slides = [s for s in demo.slides if s["deck"] != deck]
            demo.units = [u for u in demo.units if u.get("deck") != deck]
        for slides in elem.findall("slides"):
            deck = slides.get("deck")
            if deck not in deck_units:
                report.unknown_overrides.append(
                    f"<demo id={demo_id!r}>: unknown deck {deck!r}; decks are: "
                    + ", ".join(sorted(deck_units)))
                continue
            demo.add_unit(deck_units[deck], f"demos.xml: deck {deck}", deck)
            if slides.get("first"):
                first = int(slides.get("first"))
                last = int(slides.get("last") or first)
                for n in range(first, min(last, first + MAX_OVERRIDE_SLIDES - 1) + 1):
                    demo.add_slide(deck, n, "demos.xml")


def local_report(config: dict, local_root: str | Path, package_dir: str | Path | None) -> list[str]:
    """The link report for a local checkout of the demo repo: what the portal
    will derive once it syncs, checked on the instructor's machine first.

    Only tracked files are read when *local_root* is a git checkout, so
    untracked build output does not show up as demos.  Slides come from the
    built package in *package_dir*, when there is one.
    """
    from llmgrader.coursemcp.code import CodeConfig, GitError, build_snapshot, run_git
    from llmgrader.coursemcp.materials import load_materials

    code_config = CodeConfig.from_dict(config)
    local_root = Path(local_root)
    try:
        only = set(run_git(["ls-files"], cwd=local_root, timeout=30).splitlines())
    except GitError:
        only = None
    snapshot = build_snapshot(local_root, code_config, "local", only=only)
    materials = load_materials(str(package_dir)) if package_dir else None
    slides = slides_from_materials(materials)
    lines = [f"Demo links from {local_root} ({len(snapshot.files)} files served"
             + (f", {len(slides)} slides" if slides else ", no slides: build the package first")
             + "):"]
    try:
        index = build_index(snapshot, slides)
    except OverridesError as exc:
        return lines + [f"Error in {code_config.links_path}: {exc}"]
    return lines + index.report.lines(index)
