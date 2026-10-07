"""Lecture slides for the course MCP: built into the package, served from it.

**Build** (instructor's machine, ``llmgrader_mcp_build`` or ``create_soln_pkg``):
``llmgrader_mcp_config.xml`` lists the decks; each ``.pptx`` gives every
slide's title, text and speaker notes, and the deck's PDF export, when its
page count matches, gives each slide's image.  Everything is written under
``<package>/mcp_materials/``, so the course package -- one upload -- carries it.
python-pptx and PyMuPDF are needed here only, and are imported lazily.

**Serve** (the portal): plain JSON and JPEGs read from the loaded package, and
a small BM25 index over them for ``search_slides``.  No new dependencies on
the server, and no embeddings: the whole course is ~500 slides, and the AI
calling the tool rephrases and searches again on its own -- the synonym work
embeddings would otherwise do (``plans/course_mcp.md``, decision 2).

Most of a lecture slide's content is in its figures, not its text, which is
why a slide is served as its image as well.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

MATERIALS_DIR = "mcp_materials"
MANIFEST = "manifest.json"
FORMAT_VERSION = 1
IMAGE_WIDTH_PX = 1280
JPEG_QUALITY = 80
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "llmgrader_mcp_config.xsd"


class MaterialsError(Exception):
    """A configuration or build problem, with a message for the instructor."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class DeckSpec:
    id: str
    unit: str
    title: str
    pptx: Path
    pdf: Path | None


def read_config(config_path: str | Path, root_overrides: dict[str, str] | None = None) -> list[DeckSpec]:
    """The decks *config_path* lists, with every path resolved and checked."""
    import xmlschema

    config_path = Path(config_path).resolve()
    schema = xmlschema.XMLSchema(str(SCHEMA_PATH))
    errors = [str(e.reason or e) for e in schema.iter_errors(str(config_path))]
    if errors:
        raise MaterialsError(f"{config_path.name} is not valid: " + "; ".join(errors))

    import xml.etree.ElementTree as ET
    root_elem = ET.parse(config_path).getroot()
    base = config_path.parent
    roots = {"": base}
    for elem in root_elem.findall("roots/root"):
        roots[elem.get("id")] = (base / elem.get("path")).resolve()
    for root_id, path in (root_overrides or {}).items():
        if root_id not in roots:
            raise MaterialsError(f"--root {root_id}=...: no <root id={root_id!r}> in {config_path.name}")
        roots[root_id] = Path(path).resolve()

    specs, problems = [], []
    for elem in root_elem.findall("slides/deck"):
        root_id = elem.get("root") or ""
        if root_id not in roots:
            problems.append(f"deck {elem.get('id')!r}: unknown root {root_id!r}")
            continue
        base_dir = roots[root_id]
        pptx = base_dir / (elem.text or "").strip()
        pdf = base_dir / elem.get("pdf") if elem.get("pdf") else None
        if not pptx.is_file():
            problems.append(f"deck {elem.get('id')!r}: {pptx} not found")
            continue
        if pdf is not None and not pdf.is_file():
            problems.append(f"deck {elem.get('id')!r}: pdf {pdf} not found")
            continue
        specs.append(DeckSpec(elem.get("id"), elem.get("unit"), elem.get("title") or "", pptx, pdf))
    if problems:
        raise MaterialsError("; ".join(problems))
    return specs


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _shape_texts(shape) -> list[str]:
    """Every piece of text in *shape*: text frames, tables, grouped shapes."""
    texts = []
    if getattr(shape, "shape_type", None) == 6:  # MSO_SHAPE_TYPE.GROUP
        for child in shape.shapes:
            texts.extend(_shape_texts(child))
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = shape.text_frame.text.strip()
        if text:
            texts.append(text)
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                texts.append(" | ".join(cells))
    return texts


def _clean(text: str) -> str:
    # PowerPoint writes a soft line break inside a paragraph as a vertical tab.
    return text.replace("\x0b", " ").strip()


def extract_slides(pptx_path: Path) -> list[dict]:
    """Title, body text and speaker notes of every slide, in order."""
    from pptx import Presentation

    slides = []
    for number, slide in enumerate(Presentation(str(pptx_path)).slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None and title_shape.has_text_frame else ""
        body = []
        for shape in slide.shapes:
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            body.extend(_shape_texts(shape))
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        if not title and body:
            title = body[0].splitlines()[0][:80]
        slides.append({"n": number, "title": " ".join(_clean(title).split()),
                       "text": _clean("\n".join(body)), "notes": _clean(notes)})
    return slides


def render_pages(pdf_path: Path, out_dir: Path) -> list[str]:
    """Each PDF page as a JPEG in *out_dir*; returns the file names, in order."""
    import pymupdf

    names = []
    with pymupdf.open(str(pdf_path)) as doc:
        for index, page in enumerate(doc, start=1):
            zoom = IMAGE_WIDTH_PX / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            name = f"slide-{index:03d}.jpg"
            (out_dir / name).write_bytes(pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY))
            names.append(name)
    return names


def pdf_page_count(pdf_path: Path) -> int:
    import pymupdf

    with pymupdf.open(str(pdf_path)) as doc:
        return doc.page_count


def image_key(data: bytes) -> str:
    """A slide image's identity for the description cache: its content hash.

    Content, not deck and number: inserting a slide renumbers every one after
    it, and re-exporting an unchanged deck must not pay to describe it again.
    """
    import hashlib
    return hashlib.sha256(data).hexdigest()


def build_materials(specs: list[DeckSpec], package_dir: str | Path, *, log=print,
                    descriptions: dict | None = None) -> dict:
    """Write every deck under ``<package_dir>/mcp_materials``; return the manifest.

    A PDF whose page count differs from the deck's slide count is stale --
    its images would sit beside the wrong slides' text -- so it is skipped,
    loudly, and that deck is served as text alone.

    *descriptions* is the cache ``describe_slides`` writes, keyed by
    ``image_key``; a slide whose image is in it gets its description.  Reading
    it costs nothing, so every build uses whatever has been described.
    """
    descriptions = descriptions or {}
    out_root = Path(package_dir) / MATERIALS_DIR
    if out_root.exists():
        import shutil
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    manifest = {"version": FORMAT_VERSION, "decks": []}
    for spec in specs:
        deck_dir = out_root / "slides" / spec.id
        deck_dir.mkdir(parents=True)
        slides = extract_slides(spec.pptx)
        warning = ""
        images = []
        if spec.pdf is None:
            warning = "no PDF given; slides are served as text only"
        else:
            pages = pdf_page_count(spec.pdf)
            if pages != len(slides):
                warning = (f"{spec.pdf.name} has {pages} pages but {spec.pptx.name} has "
                           f"{len(slides)} slides -- re-export the PDF; slides are served as text only")
            else:
                images = render_pages(spec.pdf, deck_dir)
        described = 0
        for slide, image in zip(slides, images or [None] * len(slides)):
            slide["image"] = image
            slide["description"] = ""
            if image:
                entry = descriptions.get(image_key((deck_dir / image).read_bytes()))
                if entry:
                    slide["description"] = entry.get("description", "")
                    described += 1
        # The deck's own title slide names it better than its file name does.
        title = spec.title or (slides[0]["title"] if slides and slides[0]["title"] else spec.pptx.stem)
        (deck_dir / "deck.json").write_text(json.dumps({
            "id": spec.id, "unit": spec.unit, "title": title,
            "source": spec.pptx.name, "slides": slides,
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        manifest["decks"].append({
            "id": spec.id, "unit": spec.unit, "title": title,
            "slides": len(slides), "images": bool(images), "warning": warning,
        })
        log(f"  [{spec.id}] {len(slides)} slides, "
            f"{'with images' if images else 'text only'}"
            + (f", {described} described" if images else "")
            + (f"  WARNING: {warning}" if warning else ""))
    (out_root / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# Describe (the one step that costs money)
# ---------------------------------------------------------------------------

DESCRIPTIONS_FILE = "llmgrader_mcp_descriptions.json"
# Rough per-slide token use, for the estimate --dry-run prints before anything
# is spent: a 1280-px slide image plus its text in, a few sentences out.
EST_TOKENS_IN = 1500
EST_TOKENS_OUT = 200
TEXT_ONLY = "TEXT ONLY"

DESCRIBE_PROMPT = """\
This is slide {n} of the lecture deck "{title}", from the course unit "{unit}".
The slide's own text is below the image.

Describe what the slide shows that its text alone does not: diagrams, block
diagrams, timing waveforms, state diagrams, plots, equations, code and tables
-- what each depicts, its labels and values, and the point it makes.  Use the
technical terms a student would search for (for example "Moore machine",
"handshake", "two's complement").  2 to 5 sentences of plain text, no preamble.

If the slide has no figure and its text says everything, reply with exactly:
{text_only}

Slide text:
{text}
"""


def descriptions_path(config_path: str | Path) -> Path:
    """The description cache: beside the MCP config, and meant to be committed."""
    return Path(config_path).resolve().parent / DESCRIPTIONS_FILE


def load_descriptions(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("slides", {})
    except (OSError, ValueError):
        return {}


def _save_descriptions(path: Path, slides: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "slides": slides}, indent=1,
                              ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


@dataclass
class DescribePlan:
    todo: list            # (deck_meta, slide, image_bytes, key) to describe
    cached: int           # slides with an image already in the cache
    text_only_decks: list  # deck ids with no usable images, so nothing to describe


def plan_descriptions(specs: list[DeckSpec], cache: dict, work_dir: Path) -> DescribePlan:
    """Render every deck into *work_dir* and work out which slides need a call."""
    build_materials(specs, work_dir, log=lambda *_: None, descriptions=cache)
    todo, cached, text_only = [], 0, []
    root = Path(work_dir) / MATERIALS_DIR
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    for meta in manifest["decks"]:
        if not meta["images"]:
            text_only.append(meta["id"])
            continue
        deck_dir = root / "slides" / meta["id"]
        deck = json.loads((deck_dir / "deck.json").read_text(encoding="utf-8"))
        for slide in deck["slides"]:
            data = (deck_dir / slide["image"]).read_bytes()
            key = image_key(data)
            if key in cache:
                cached += 1
            else:
                todo.append((meta, slide, data, key))
    return DescribePlan(todo, cached, text_only)


def estimate_cost(model_spec, slides: int) -> float:
    return slides * (EST_TOKENS_IN * model_spec.usd_per_mtok_in
                     + EST_TOKENS_OUT * model_spec.usd_per_mtok_out) / 1e6


def describe_slides(plan: DescribePlan, cache_path: Path, *, model_spec, api_key: str,
                    workers: int = 8, timeout: float = 120, log=print) -> tuple[int, float]:
    """Describe every slide in *plan*; returns ``(described, usd_spent)``.

    The cache is saved after every slide, so an interruption -- or a failed
    call -- loses nothing already paid for, and re-running picks up where it
    stopped.
    """
    import base64
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from llmgrader.services.answers import make_openai_answer_caller

    cache = load_descriptions(cache_path)
    lock = threading.Lock()
    spent = [0.0]
    done = [0]

    def describe(item):
        meta, slide, data, key = item
        prompt = DESCRIBE_PROMPT.format(
            n=slide["n"], title=meta["title"], unit=meta["unit"],
            text=slide["text"] or "(none)", text_only=TEXT_ONLY)
        uri = "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
        call = make_openai_answer_caller(model=model_spec.id, api_key=api_key,
                                         prompt=prompt, timeout=timeout, images=[uri])
        text, tokens_in, tokens_out = call()
        text = " ".join(text.split())
        description = "" if text.upper().startswith(TEXT_ONLY) else text
        cost = (tokens_in * model_spec.usd_per_mtok_in + tokens_out * model_spec.usd_per_mtok_out) / 1e6
        with lock:
            cache[key] = {"description": description, "model": model_spec.id,
                          "deck": meta["id"], "slide": slide["n"]}
            spent[0] += cost
            done[0] += 1
            _save_descriptions(cache_path, cache)
            if done[0] % 25 == 0 or done[0] == len(plan.todo):
                log(f"  {done[0]}/{len(plan.todo)} described, ${spent[0]:.2f} so far")

    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(describe, item): item for item in plan.todo}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # one bad call must not cost the rest
                failures += 1
                meta, slide, _, _ = futures[future]
                log(f"  failed: {meta['id']} slide {slide['n']}: {exc}")
    if failures:
        log(f"  {failures} slide(s) failed; re-run to retry them -- the rest are saved.")
    return done[0], spent[0]


# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Materials:
    """One package's slide material, loaded once and indexed for search."""

    root: Path
    decks: list[dict]
    _deck_cache: dict = field(default_factory=dict)
    _index: list | None = None

    def deck_ids(self) -> list[str]:
        return [d["id"] for d in self.decks]

    def deck(self, deck_id: str) -> dict | None:
        if not any(d["id"] == deck_id for d in self.decks):
            return None
        if deck_id not in self._deck_cache:
            path = self.root / "slides" / deck_id / "deck.json"
            self._deck_cache[deck_id] = json.loads(path.read_text(encoding="utf-8"))
        return self._deck_cache[deck_id]

    def image_path(self, deck_id: str, name: str) -> Path | None:
        path = (self.root / "slides" / deck_id / name).resolve()
        slides_root = (self.root / "slides").resolve()
        if not str(path).startswith(str(slides_root) + os.sep) or not path.is_file():
            return None
        return path

    # BM25 over title (counted twice), text, notes and figure description.
    K1, B = 1.5, 0.75

    def _build_index(self) -> list:
        docs = []
        for meta in self.decks:
            deck = self.deck(meta["id"])
            for slide in deck["slides"]:
                terms = (tokenize(slide["title"]) * 2 + tokenize(slide["text"])
                         + tokenize(slide["notes"]) + tokenize(slide.get("description", "")))
                docs.append((meta, slide, Counter(terms), len(terms)))
        return docs

    def search(self, query: str, *, unit: str | None = None, limit: int = 10) -> list[dict]:
        if self._index is None:
            self._index = self._build_index()
        docs = self._index
        terms = tokenize(query)
        if not docs or not terms:
            return []
        avg_len = sum(d[3] for d in docs) / len(docs) or 1
        df = Counter(t for d in docs for t in set(d[2]) if t in terms)
        wanted_unit = " ".join(unit.lower().split()) if unit else None
        scored = []
        for meta, slide, counts, length in docs:
            if wanted_unit and " ".join(meta["unit"].lower().split()) != wanted_unit:
                continue
            score = 0.0
            for term in set(terms):
                tf = counts.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * length / avg_len))
            if score > 0:
                scored.append((score, meta, slide))
        scored.sort(key=lambda item: -item[0])
        return [
            {"deck": meta["id"], "unit": meta["unit"], "slide": slide["n"],
             "title": slide["title"], "snippet": _snippet(slide, terms),
             "score": round(score, 2)}
            for score, meta, slide in scored[:limit]
        ]


def _snippet(slide: dict, terms: list[str], width: int = 160) -> str:
    text = " ".join(" ".join([slide["text"], slide["notes"], slide.get("description", "")]).split())
    lower = text.lower()
    hits = [lower.find(t) for t in terms if lower.find(t) >= 0]
    start = max(0, min(hits) - 40) if hits else 0
    piece = text[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(text) else "")


_CACHE: dict[str, tuple[float, Materials | None]] = {}
_CACHE_LOCK = threading.Lock()


def load_materials(soln_pkg: str | None) -> Materials | None:
    """The package's slide material, or None if it has none.

    Cached per package directory and reloaded when the manifest changes --
    an upload replaces the package, and with it the manifest.
    """
    if not soln_pkg:
        return None
    root = Path(soln_pkg) / MATERIALS_DIR
    manifest_path = root / MANIFEST
    try:
        mtime = manifest_path.stat().st_mtime
    except OSError:
        return None
    key = str(root.resolve())
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        materials = Materials(root=root, decks=manifest.get("decks", []))
        _CACHE[key] = (mtime, materials)
        return materials
