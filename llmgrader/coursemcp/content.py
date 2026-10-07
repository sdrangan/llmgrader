"""Course content shaped for a student's AI: lookups, text and figures.

Plain functions over a ``Grader``'s loaded units, kept apart from the MCP
tool definitions so they can be tested without a server.

Every result here is bounded by construction (``plans/course_mcp.md``
decision 3): an index entry carries a short label rather than the question
text, and figures travel only with a single question, never with a list.
"""

from __future__ import annotations

import base64
import binascii
import html
import os
import re
from dataclasses import dataclass

from mcp.server.mcpserver.exceptions import ToolError

# A figure larger than this is described rather than sent.  Tool results are
# context: one oversized image can exhaust a client's window on its own.
MAX_FIGURE_BYTES = 2_000_000
LABEL_CHARS = 100

_IMG_RE = re.compile(r"<img\b[^>]*>", re.I | re.S)
_SRC_RE = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n\s*\n+")
_DATA_URI_RE = re.compile(r"^data:(image/[\w.+-]+);base64,(.*)$", re.S)


@dataclass
class Figure:
    data: bytes
    mime: str


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def unit_names(grader) -> list[str]:
    """The course's unit names in teaching order."""
    names = [item["name"] for item in grader.units_order if item["type"] == "unit"]
    return names or list(grader.units)


def resolve_unit(grader, unit: str) -> str:
    """The unit name *unit* refers to, or a ToolError listing the valid ones.

    Exact match first, then case- and whitespace-insensitive -- unit names
    carry double spaces ("Unit 2:  Sequential Logic"), which an AI will not
    reproduce reliably.
    """
    if unit in grader.units:
        return unit
    wanted = _WS_RE.sub(" ", unit).strip().lower()
    for name in grader.units:
        if _WS_RE.sub(" ", name).strip().lower() == wanted:
            return name
    raise ToolError(
        f"Unknown unit {unit!r}. Valid units, from list_units: "
        + "; ".join(repr(n) for n in unit_names(grader))
    )


def resolve_question(grader, unit: str, qtag: str) -> tuple[str, str, dict]:
    """``(unit_name, qtag, question)``, or a ToolError listing valid qtags."""
    unit_name = resolve_unit(grader, unit)
    questions = grader.units[unit_name]
    if qtag in questions:
        return unit_name, qtag, questions[qtag]
    wanted = qtag.strip().lower()
    for tag, question in questions.items():
        if tag.strip().lower() == wanted:
            return unit_name, tag, question
    raise ToolError(
        f"Unknown question {qtag!r} in {unit_name!r}. Valid qtags, from "
        "list_questions: " + "; ".join(repr(t) for t in questions)
    )


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def plain_text(fragment: str) -> str:
    """An HTML fragment as one line of plain text."""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", fragment or ""))).strip()


def question_label(question: dict) -> str:
    """A short, plain-text label for the question index."""
    text = plain_text(question.get("question_text", ""))
    if len(text) <= LABEL_CHARS:
        return text
    return text[: LABEL_CHARS - 1].rsplit(" ", 1)[0] + "…"


def tidy_html(fragment: str) -> str:
    """The fragment with figures replaced by numbered placeholders.

    The HTML is otherwise kept: an AI reads it fine, and it carries the
    structure -- code blocks, lists, \\( math \\) -- that plain text would
    flatten.  ``[Figure n]`` matches the n-th image sent with the result.
    """
    counter = iter(range(1, 1000))
    text = _IMG_RE.sub(lambda _m: f"[Figure {next(counter)}]", fragment or "")
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def parts_summary(question: dict) -> list[dict]:
    return [
        {"part": part.get("part_label", ""), "points": part.get("points", 0)}
        for part in question.get("parts") or []
    ]


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def _decode_data_uri(uri: str) -> Figure | None:
    match = _DATA_URI_RE.match(uri.strip())
    if not match:
        return None
    try:
        return Figure(base64.b64decode(match.group(2)), match.group(1))
    except (binascii.Error, ValueError):
        return None


def _read_package_asset(soln_pkg: str, src: str) -> Figure | None:
    """``/pkg_assets/<path>`` (course-prefixed or not) read from the package.

    Confined to the package directory, as ``send_from_directory`` confines
    the portal's own /pkg_assets route.
    """
    if not soln_pkg or "/pkg_assets/" not in src:
        return None
    relative = src.split("/pkg_assets/", 1)[1].split("?", 1)[0]
    root = os.path.realpath(soln_pkg)
    path = os.path.realpath(os.path.join(root, relative))
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(
        ext, f"image/{ext or 'png'}")
    with open(path, "rb") as fh:
        return Figure(fh.read(), mime)


def figures_in(fragment: str, soln_pkg: str) -> list[Figure | None]:
    """One entry per ``<img>`` in *fragment*, in order; None if unresolvable."""
    figures: list[Figure | None] = []
    for tag in _IMG_RE.findall(fragment or ""):
        match = _SRC_RE.search(tag)
        src = match.group(1) if match else ""
        figures.append(_decode_data_uri(src) or _read_package_asset(soln_pkg, src))
    return figures


def solution_figures(question: dict, soln_pkg: str) -> list[Figure | None]:
    """The solution's figures, preferring the parser's resolved data URIs."""
    resolved = [_decode_data_uri(uri) for uri in question.get("solution_images") or []]
    in_html = figures_in(question.get("solution", ""), soln_pkg)
    if resolved and len(resolved) == len(in_html):
        return resolved
    return in_html


def figure_notes(figures: list[Figure | None]) -> list[str]:
    """What the text should say about figures that are not attached."""
    notes = []
    for number, figure in enumerate(figures, start=1):
        if figure is None:
            notes.append(f"Figure {number} could not be loaded from the course package.")
        elif len(figure.data) > MAX_FIGURE_BYTES:
            notes.append(f"Figure {number} is too large to send "
                         f"({len(figure.data) // 1000} kB); view it on the course portal.")
    return notes


def sendable(figures: list[Figure | None]) -> list[Figure]:
    return [f for f in figures if f is not None and len(f.data) <= MAX_FIGURE_BYTES]
