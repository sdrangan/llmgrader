"""One index of a course's materials: ``plans/unified_materials.md``.

The four material tools read nothing else.  It joins:

* the **package items** the build made (``materials.py``), complete;
* the **mirror items** -- the config's ``<item source="mirror">`` and one
  item per folder an ``<items>`` pattern matches -- resolved against the
  portal's copy of the repo (``code.py``);
* the **links** the slides and docs pages make (``links.py``): an item's
  slides, and units it has no config entry for;
* the **refinements**: the config's, then the repo's ``materials.xml``.

A catalog is built from one package and one snapshot and never changed, so
readers take no lock; :func:`catalog_for` caches it until either changes.
"""

from __future__ import annotations

import fnmatch
import posixpath
import threading
from dataclasses import dataclass, field

from llmgrader.coursemcp import code as code_module
from llmgrader.coursemcp.code import CodeError, CodeSnapshot, PdfDoc
from llmgrader.coursemcp.links import (
    OverridesError,
    SlideRef,
    link_items,
    parse_overrides,
    same_unit,
)
from llmgrader.coursemcp.materials import (
    PAGE,
    PAGED_FORMATS,
    PDF,
    TEXT,
    Materials,
    TermIndex,
    UnitResolver,
    refinement_of,
    snippet,
)

MAX_OVERRIDE_SLIDES = 60
MAX_RANKED_HITS = 12     # slides, PDF pages and docs sections
MAX_HITS = 25            # in all, with code lines
# Where a line of text lands among the ranked hits, whose scores run from
# RELATIVE_CUTOFF to 1: a docs page or slide that explains a thing ranks
# above the code that does it, and hand-written source above scripts and
# notebooks (code.text_rank).
TEXT_HIT_SCORES = {1: 0.8, 2: 0.6, 3: 0.5}
TEXT_HIT_DEFAULT = 0.4


@dataclass
class Part:
    """One file of an item, with the format it is read in."""
    path: str
    format: str                      # slides, pdf, page or text
    source: str                      # package or mirror
    deck: str | None = None          # a package paged part's deck
    stored: dict | None = None       # a package text part's manifest entry


@dataclass
class Material:
    id: str
    kind: str
    source: str
    title: str = ""
    description: str = ""
    units: list[dict] = field(default_factory=list)     # {"unit", "via"}
    parts: list[Part] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)      # mirror folders and files
    slides: list[dict] = field(default_factory=list)    # {"deck", "slide", "via"}
    related: list[str] = field(default_factory=list)
    policy: str = "open"
    listed_parts: int = 0            # a private package item: parts never built

    @property
    def readable(self) -> bool:
        return self.policy != "private"

    @property
    def unit_names(self) -> list[str]:
        return [u["unit"] for u in self.units]

    def add_unit(self, unit: str, via: str, deck: str | None = None) -> None:
        """Add *unit* unless the item has it.  *deck* marks a unit a deck's
        slides gave, so that ``<not_slides deck>`` can take it away again."""
        if unit and not any(same_unit(u["unit"], unit) for u in self.units):
            self.units.append({"unit": unit, "via": via, **({"deck": deck} if deck else {})})

    def part_count(self) -> int:
        return len(self.parts) or self.listed_parts


@dataclass
class Paged:
    """A paged part, a package deck or a mirrored PDF, read alike."""
    title: str
    pages: list
    image_path: object               # name -> Path | None
    deck: str | None = None          # a package deck: the slide route serves it
    error: str | None = None

    @property
    def images(self) -> bool:
        return any(p.get("image") for p in self.pages)


class Catalog:
    def __init__(self, materials: Materials | None, snapshot: CodeSnapshot | None,
                 resolver: UnitResolver):
        self.materials = materials
        self.snapshot = snapshot
        self.resolver = resolver
        self.kinds: dict[str, dict] = {k["id"]: k for k in (materials.kinds if materials else [])}
        self.material_units = list(materials.material_units if materials else [])
        self.items: dict[str, Material] = {}
        self.report: list[str] = []
        self.doc_cites: dict[str, list[str]] = {}
        self.mirror_configured = bool(materials and materials.code)
        self._index: TermIndex | None = None
        self._index_lock = threading.Lock()

    # -- lookups -------------------------------------------------------------

    def get(self, item_id: str) -> Material | None:
        return self.items.get((item_id or "").strip().lower())

    def item_for_deck(self, deck: str) -> Material | None:
        return next((i for i in self.items.values()
                     for p in i.parts if p.deck == deck), None)

    def items_for_slide(self, deck: str, n: int) -> list[Material]:
        return [i for i in self.items.values() if i.readable
                and any(s["deck"] == deck and s["slide"] == n for s in i.slides)]

    def items_for_path(self, path: str) -> list[str]:
        return [i.id for i in self.items.values() if any(p.path == path for p in i.parts)]

    def paged(self, part: Part) -> Paged:
        if part.deck is not None:
            deck = self.materials.deck(part.deck) or {"title": part.path, "slides": []}
            return Paged(deck["title"], deck["slides"],
                         lambda name, d=part.deck: self.materials.image_path(d, name),
                         deck=part.deck)
        doc = self.snapshot.pdfs.get(part.path) if self.snapshot else None
        if doc is None:
            doc = PdfDoc(part.path, error="its pages have not been rendered yet")
        return Paged(doc.title, doc.pages, doc.image_path, error=doc.error)

    def text(self, part: Part):
        """A text or page part as a ``code.SourceFile``."""
        if part.source == "package":
            source = self.materials.text_source(part.stored or {})
            if source is None:
                raise CodeError(f"{part.path!r} could not be read from the course package.")
            return source
        return self.snapshot.get(part.path)

    def links_for(self, part: Part):
        """``links_for(path, start, end, anchor)`` for a mirrored file, else None:
        a package file has no public address."""
        return self.snapshot.links_for if part.source == "mirror" and self.snapshot else None

    def unit_names_matching(self, unit: str) -> list[str]:
        """Every unit name *unit* refers to: the unit it resolves to (a name
        in any case and spacing, or a material unit's id), or, failing that,
        each unit whose name before its colon it is -- "unit 5" for
        "Unit 5:  FIFOs and Streaming Interfaces", but never "Unit 50"."""
        names = list(dict.fromkeys(
            [*self.resolver.all_names(), *(n for i in self.items.values() for n in i.unit_names)]))
        resolved = self.resolver.resolve(unit)
        if resolved is not None:
            return [resolved]
        wanted = " ".join((unit or "").lower().split())
        exact = [n for n in names if same_unit(n, wanted)]
        if exact:
            return exact
        return [n for n in names if ":" in n and same_unit(n.split(":", 1)[0], wanted)]

    def matches_unit(self, item: Material, unit: str) -> bool:
        wanted = self.unit_names_matching(unit)
        return any(same_unit(name, w) for name in item.unit_names for w in wanted)

    # -- search --------------------------------------------------------------

    def _term_index(self) -> TermIndex:
        with self._index_lock:
            if self._index is None:
                documents = []
                for item in self.items.values():
                    if not item.readable:
                        continue
                    for number, part in enumerate(item.parts):
                        if part.format in PAGED_FORMATS:
                            for page in self.paged(part).pages:
                                documents.append((page.get("title", ""), [
                                    page.get("text", ""), page.get("notes", ""),
                                    page.get("description", "")],
                                    ("paged", item.id, number, page["n"])))
                        elif part.format == PAGE:
                            try:
                                source = self.text(part)
                            except CodeError:
                                continue
                            for section in _sections(source):
                                documents.append((section["heading"] or source.title,
                                                  [section["text"]],
                                                  ("page", item.id, number, section)))
                self._index = TermIndex(documents)
            return self._index

    def search(self, query: str, *, items: list[Material], fmt: str | None = None,
               slide_url=lambda deck, n: None) -> dict:
        """Hits across *items*, best first: slides, PDF pages and docs
        sections ranked together (``materials.TermIndex``), then merged by
        score with literal matches in text files (``code.find_lines``)."""
        allowed = {i.id for i in items if i.readable}
        ranked = []
        if fmt in (None, *PAGED_FORMATS, PAGE):
            def keep(payload):
                part = self.items[payload[1]].parts[payload[2]]
                return payload[1] in allowed and (fmt is None or part.format == fmt)
            ranked = self._term_index().search(query, keep=keep)
        best = ranked[0][0] if ranked else 1.0
        hits = [(score / best, self._ranked_hit(payload, query, slide_url))
                for score, payload in ranked[:MAX_RANKED_HITS]]
        more = max(0, len(ranked) - MAX_RANKED_HITS)

        if fmt in (None, TEXT):
            sources, owner = [], {}
            for item in items:
                if item.id not in allowed:
                    continue
                for part in item.parts:
                    if part.format != TEXT or part.path in owner:
                        continue
                    try:
                        source = self.text(part)
                    except CodeError:
                        continue
                    sources.append(source)
                    owner[part.path] = (item, part)
            blocks = code_module.find_lines(sources, query)
            for source, block in blocks[:MAX_HITS]:
                item, part = owner[source.path]
                hit = {"id": item.id, "kind": item.kind,
                       **code_module.line_hit(source, block, self.links_for(part))}
                rank = code_module.text_rank(source)
                hits.append((TEXT_HIT_SCORES.get(rank, TEXT_HIT_DEFAULT), hit))
            more += max(0, len(blocks) - MAX_HITS)

        hits.sort(key=lambda pair: -pair[0])
        more += max(0, len(hits) - MAX_HITS)
        shown = []
        for score, hit in hits[:MAX_HITS]:
            hit["score"] = round(score, 2)
            if self.items[hit["id"]].policy == "tutor":
                hit["policy"] = "tutor"
            shown.append(hit)
        return {"hits": shown, "hits_shown": len(shown), "more": more}

    def _ranked_hit(self, payload, query: str, slide_url) -> dict:
        _, item_id, number, where = payload
        item = self.items[item_id]
        part = item.parts[number]
        hit = {"id": item.id, "kind": item.kind, "format": part.format, "path": part.path}
        if part.format in PAGED_FORMATS:
            paged = self.paged(part)
            page = paged.pages[where - 1]
            hit.update({"page": where, "title": page.get("title", ""),
                        "snippet": snippet([page.get("text", ""), page.get("notes", ""),
                                            page.get("description", "")], query)})
            if page.get("image"):
                url = page_url(self, part, paged, where, slide_url)
                if url:
                    hit["view_url"] = url
            return hit
        source = self.text(part)
        start, end = source.first_line + where["start"], source.first_line + where["end"]
        hit.update({"title": source.title, "start_line": start, "end_line": end,
                    "snippet": snippet([where["text"]], query)})
        if where["heading"]:
            hit["heading"] = where["heading"]
        links = self.links_for(part)
        if links is not None:
            hit.update(links(part.path, start, end, where["anchor"]))
        return hit


def page_url(catalog: Catalog, part: Part, paged: Paged, n: int, slide_url) -> str | None:
    """A link the student can open to see one page: the portal's slide route
    for a package deck, the file on GitHub for a mirrored PDF."""
    if paged.deck is not None:
        return slide_url(paged.deck, n)
    if catalog.snapshot is not None:
        return catalog.snapshot.source_url(part.path) + f"#page={n}"
    return None


def _sections(source) -> list[dict]:
    """A Markdown page cut at its headings: ``{"heading", "anchor", "start",
    "end", "text"}``, line indexes into ``source.lines``."""
    headings = source.headings or (None,) * len(source.lines)
    sections, start = [], 0
    for i in range(1, len(source.lines) + 1):
        if i == len(source.lines) or (headings[i] is not None and headings[i] != headings[i - 1]):
            text = "\n".join(source.lines[start:i]).strip()
            if text:
                heading = headings[start]
                sections.append({"heading": heading[0] if heading else "",
                                 "anchor": heading[1] if heading else None,
                                 "start": start, "end": i - 1, "text": text})
            start = i
    return sections


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def _nav_key(snapshot: CodeSnapshot, path: str):
    source = snapshot.files.get(path)
    try:
        order = float(source.meta.get("nav_order", "")) if source else float("inf")
    except ValueError:
        order = float("inf")
    title = source.title.lower() if source else path
    return (posixpath.basename(path) != "index.md", order, title, path)


def _mirror_parts(snapshot: CodeSnapshot, roots: list[tuple[str, bool]]) -> list[Part]:
    """The files under each ``(path, docs)``: docs pages first, in their
    navigation order, then the rest by path."""
    pages, others = [], []
    for root, docs in roots:
        for path in snapshot.under(root):
            source = snapshot.files.get(path)
            if source is not None and source.format == PAGE:
                if path not in pages:
                    pages.append(path)
            elif not docs and path not in others:
                others.append(path)
    pages.sort(key=lambda p: _nav_key(snapshot, p))
    parts = [Part(p, PAGE, "mirror") for p in pages]
    for path in sorted(others):
        parts.append(Part(path, PDF if path in snapshot.pdf_paths else TEXT, "mirror"))
    return parts


def _title_and_description(snapshot: CodeSnapshot, docs_dir: str | None,
                           code_dir: str | None, fallback: str) -> tuple[str, str]:
    """What an item a pattern made is called: its docs folder's index.md (or
    first page), else the README in its folder, else the folder's name."""
    if docs_dir:
        pages = [p for p in snapshot.under(docs_dir)
                 if p in snapshot.files and snapshot.files[p].format == PAGE]
        if pages:
            page = snapshot.files.get(f"{docs_dir}/index.md") or snapshot.files[
                min(pages, key=lambda p: _nav_key(snapshot, p))]
            return page.title, page.first_paragraph()
    if code_dir:
        readmes = [p for p in snapshot.under(code_dir)
                   if posixpath.basename(p).lower() == "readme.md" and p in snapshot.files]
        if readmes:
            readme = snapshot.files[min(readmes, key=lambda p: (p.count("/"), p))]
            return readme.title, readme.first_paragraph()
    return fallback, ""


def pattern_matches(snapshot: CodeSnapshot, pattern: str | None) -> dict[str, str]:
    """``{name: folder}`` for each folder *pattern* matches in the snapshot."""
    if not pattern:
        return {}
    head, _, glob = pattern.rpartition("/")
    names = {}
    for path in [*snapshot.files, *snapshot.pdf_paths]:
        if head and not path.startswith(head + "/"):
            continue
        rest = path[len(head) + 1:] if head else path
        if "/" not in rest:
            continue                    # a file beside the folders is not an item
        name = rest.split("/", 1)[0]
        if fnmatch.fnmatchcase(name, glob):
            names[name] = f"{head}/{name}" if head else name
    return names


def build_catalog(materials: Materials | None, snapshot: CodeSnapshot | None,
                  resolver: UnitResolver) -> Catalog:
    """The index for one package and one copy of the mirror (None: no mirror,
    or none fetched yet -- the package items are served regardless)."""
    catalog = Catalog(materials, snapshot, resolver)
    if materials is None:
        return catalog
    items = catalog.items

    for entry in materials.items:
        item = Material(entry["id"], entry["kind"], "package", entry.get("title", ""),
                        entry.get("description", ""))
        for unit in entry.get("units", []):
            item.add_unit(unit, "config")
        for part in entry.get("parts", []):
            if part.get("deck"):
                item.parts.append(Part(part["path"], part["format"], "package", deck=part["deck"]))
            elif part.get("format") == TEXT:
                item.parts.append(Part(part["path"], TEXT, "package", stored=part))
            else:
                item.listed_parts += 1     # a private item: never built
        items[item.id] = item

    explicit_slides: list[tuple[Material, dict]] = []
    for entry in materials.items:
        explicit_slides.append((items[entry["id"]], entry))

    if snapshot is not None:
        claimed: list[str] = []
        for entry in materials.mirror_items:
            item = Material(entry["id"], entry["kind"], "mirror", entry.get("title", ""),
                            entry.get("description", ""))
            for unit in entry.get("units", []):
                item.add_unit(unit, "config")
            roots = [(p["path"], bool(p.get("docs"))) for p in entry.get("parts", [])]
            for path, _ in roots:
                if not snapshot.served(path) and path not in snapshot.served_dirs:
                    catalog.report.append(f"item {item.id!r}: {path} is not in the mirror")
            item.roots = [path for path, _ in roots]
            item.parts = _mirror_parts(snapshot, roots)
            if not item.title:
                docs = next((p for p, d in roots if d), None)
                code_dir = next((p for p, d in roots if not d), None)
                item.title, found = _title_and_description(snapshot, docs, code_dir, item.id)
                item.description = item.description or found
            claimed += item.roots
            items[item.id] = item
            explicit_slides.append((item, entry))

        for pattern in materials.patterns:
            by_path = pattern_matches(snapshot, pattern["path"])
            by_docs = pattern_matches(snapshot, pattern.get("docs"))
            for name in sorted(set(by_path) | set(by_docs)):
                folders = [f for f in (by_path.get(name), by_docs.get(name)) if f]
                if any(f == c or f.startswith(c + "/") for f in folders for c in claimed):
                    continue        # an explicit item serves it
                # A name another item has (a deck named like its demo) gets
                # the kind after it: fsm-demo beside the fsm slides.
                item_id = name.lower() if name.lower() not in items else f"{name.lower()}-{pattern['kind']}"
                if item_id in items:
                    catalog.report.append(f"<items path={pattern['path']!r}>: {name} would be "
                                          f"{item_id!r}, which is taken; left out")
                    continue
                title, description = _title_and_description(
                    snapshot, by_docs.get(name), by_path.get(name), name)
                item = Material(item_id, pattern["kind"], "mirror", title, description)
                for unit in pattern.get("units", []):
                    item.add_unit(unit, f"<items path={pattern['path']!r}>")
                roots = [(f, f == by_docs.get(name)) for f in folders]
                item.roots = folders
                item.parts = _mirror_parts(snapshot, roots)
                items[item.id] = item
    elif catalog.mirror_configured:
        catalog.report.append("the mirror has not been fetched: its items are not listed yet")

    # Derived links: which slides cite an item, and the units that gives it.
    slides = _slide_refs(materials, items)
    deck_units = {s.deck: s.units for s in slides}
    links = link_items(snapshot, slides,
                       {i.id: i.roots for i in items.values() if i.source == "mirror"})
    catalog.doc_cites = links.doc_cites
    catalog.report += links.report.lines()
    for item_id, found in links.items.items():
        item = items[item_id]
        item.slides = list(found.slides)
        item.related = list(found.related)
        for unit in found.units:
            item.add_unit(unit["unit"], unit["via"], unit.get("deck"))

    # The config's own slide entries, then its refinements, then the repo's.
    for item, entry in explicit_slides:
        _apply_slides(item, entry.get("slides", []), entry.get("not_slides", []),
                      deck_units, catalog.report, "config")
    for refinement in materials.refinements:
        _refine(catalog, refinement, deck_units, "config")
    if snapshot is not None:
        try:
            root = parse_overrides(snapshot.overrides_text)
        except OverridesError as exc:       # a sync never serves one; a local check might
            catalog.report.append(f"{snapshot.config.overrides_path}: {exc}")
            root = None
        for elem in root if root is not None else []:
            refinement = refinement_of(elem)
            refinement["units"] = _resolve_units(catalog, refinement, snapshot.config.overrides_path)
            _refine(catalog, refinement, deck_units, snapshot.config.overrides_path)

    for item in items.values():
        item.policy = catalog.kinds.get(item.kind, {}).get("policy", "open")
        for unit in item.units:
            unit.pop("deck", None)
    return catalog


def _resolve_units(catalog: Catalog, refinement: dict, where: str) -> list[str]:
    names = []
    for ref in refinement["units"]:
        name = catalog.resolver.resolve(ref)
        if name is None:
            catalog.report.append(f"{where}: item {refinement['id']!r}: unknown unit {ref!r}")
            name = ref
        names.append(name)
    return names


def _slide_refs(materials: Materials, items: dict[str, Material]) -> list[SlideRef]:
    """Every page of the package's paged items, with its item's units."""
    refs = []
    for meta in materials.decks:
        deck = materials.deck(meta["id"])
        item = items.get(meta.get("item", ""))
        if not deck or item is None:
            continue
        units = tuple(item.unit_names)
        for slide in deck["slides"]:
            text = "\n".join([slide.get("title", ""), slide.get("text", ""),
                              slide.get("notes", ""), slide.get("description", "")])
            refs.append(SlideRef(meta["id"], units, slide["n"], text,
                                 tuple(slide.get("links") or ())))
    return refs


def _apply_slides(item: Material, slides: list[dict], not_slides: list[str],
                  deck_units: dict, report: list[str], where: str) -> None:
    for deck in not_slides:
        item.slides = [s for s in item.slides if s["deck"] != deck]
        item.units = [u for u in item.units if u.get("deck") != deck]
    for entry in slides:
        deck = entry["deck"]
        if deck not in deck_units:
            report.append(f"{where}: item {item.id!r}: unknown deck {deck!r}; decks are: "
                          + ", ".join(sorted(deck_units)))
            continue
        for unit in deck_units[deck]:
            item.add_unit(unit, f"{where}: deck {deck}", deck)
        if entry.get("first"):
            first = entry["first"]
            last = entry.get("last") or first
            for n in range(first, min(last, first + MAX_OVERRIDE_SLIDES - 1) + 1):
                if not any(s["deck"] == deck and s["slide"] == n for s in item.slides):
                    item.slides.append({"deck": deck, "slide": n, "via": where})
    item.slides.sort(key=lambda s: (s["deck"], s["slide"]))


def _refine(catalog: Catalog, refinement: dict, deck_units: dict, where: str) -> None:
    item = catalog.items.get(refinement["id"])
    if item is None:
        catalog.report.append(f"{where}: <item id={refinement['id']!r}> matches no item; "
                              "items are: " + ", ".join(sorted(catalog.items)))
        return
    if refinement.get("kind"):
        if refinement["kind"] in catalog.kinds:
            item.kind = refinement["kind"]
        else:
            catalog.report.append(f"{where}: item {item.id!r}: unknown kind {refinement['kind']!r}")
    item.title = refinement.get("title") or item.title
    item.description = refinement.get("description") or item.description
    for unit in refinement.get("units", []):
        item.add_unit(unit, where)
    _apply_slides(item, refinement.get("slides", []), refinement.get("not_slides", []),
                  deck_units, catalog.report, where)


def unitless(catalog: Catalog) -> list[str]:
    return [i.id for i in catalog.items.values() if not i.units]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def catalog_for(materials: Materials | None, snapshot: CodeSnapshot | None,
                resolver: UnitResolver) -> Catalog:
    """The catalog for this package and snapshot, built once.  Keyed by the
    objects themselves, which live until the package or the mirror changes;
    the cache holds them, so their ids are not reused while it does."""
    key = (id(materials), id(snapshot), tuple(resolver.all_names()))
    with _CACHE_LOCK:
        found = _CACHE.get(key)
        if found is not None:
            return found[0]
    catalog = build_catalog(materials, snapshot, resolver)
    with _CACHE_LOCK:
        if len(_CACHE) > 16:
            _CACHE.clear()
        _CACHE[key] = (catalog, materials, snapshot)
    return catalog


# ---------------------------------------------------------------------------
# The build's check: the same index, from a local checkout
# ---------------------------------------------------------------------------


def local_catalog(code_config: dict | None, local_root, package_dir,
                  unit_names: list[str]) -> Catalog:
    """The catalog the portal will build once it syncs, built on the
    instructor's machine from a local checkout of the mirrored repo and the
    package just built into *package_dir*.

    Only tracked files are read when *local_root* is a git checkout, so
    untracked build output does not turn into items.  PDFs are noted, not
    rendered: the check needs their paths, not their pages.
    """
    from pathlib import Path

    from llmgrader.coursemcp.code import CodeConfig, GitError, build_snapshot, run_git
    from llmgrader.coursemcp.materials import load_materials

    snapshot = None
    if code_config and local_root is not None:
        local_root = Path(local_root)
        try:
            only = set(run_git(["ls-files"], cwd=local_root, timeout=30).splitlines())
        except GitError:
            only = None
        snapshot = build_snapshot(local_root, CodeConfig.from_dict(code_config), "local",
                                  only=only)
    materials = load_materials(str(package_dir))
    resolver = UnitResolver(unit_names, materials.material_units if materials else [])
    return build_catalog(materials, snapshot, resolver)


def catalog_problems(catalog: Catalog) -> list[str]:
    """What fails the build: a refinement that matches nothing, an unknown
    unit or kind, a mirror path that is not there, an item with no unit."""
    problems = [line for line in catalog.report
                if "matches no item" in line or "unknown unit" in line
                or "unknown kind" in line or "unknown deck" in line
                or "is not in the mirror" in line]
    missing = unitless(catalog)
    if missing:
        problems.append("every item needs a unit; these have none (give each one in the "
                        "config or the repo's materials.xml, or cite it from a slide): "
                        + ", ".join(missing))
    return problems


def catalog_lines(catalog: Catalog) -> list[str]:
    """The index, for ``llmgrader_mcp_build --materials``: every item, its
    units and where each came from, and its parts and their formats."""
    out = [f"{len(catalog.items)} item(s) in {len(catalog.kinds)} kind(s):"]
    for kind_id, kind in catalog.kinds.items():
        items = [i for i in catalog.items.values() if i.kind == kind_id]
        policy = kind.get("policy", "open")
        out.append(f"  {kind_id} ({len(items)})" + (f", {policy}" if policy != "open" else "")
                   + f": {kind['description']}")
        for item in items:
            out.append(f"    [{item.id}] {item.title}  ({item.source})")
            for unit in item.units:
                out.append(f"        unit  {unit['unit']}    <- {unit['via']}")
            if not item.units:
                out.append("        unit  NONE")
            formats: dict[str, int] = {}
            for part in item.parts:
                formats[part.format] = formats.get(part.format, 0) + 1
            parts = ", ".join(f"{n} {fmt}" for fmt, n in formats.items())
            if item.listed_parts:
                parts = f"{item.listed_parts} listed, not built"
            out.append(f"        parts {parts or 'none'}")
            for part in item.parts[:6]:
                out.append(f"              {part.format:<6} {part.path}")
            if len(item.parts) > 6:
                out.append(f"              ... {len(item.parts) - 6} more")
            if item.slides:
                out.append("        slides " + ", ".join(f"{s['deck']} {s['slide']}"
                                                         for s in item.slides))
    return out + catalog.report
