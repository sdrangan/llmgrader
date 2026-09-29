"""Column widths for the tables the command-line tools print.

The tables used fixed widths, so a qtag or case id longer than its column ran
straight into the next one ("...and FIFO deptha=5 [5-]").  A column is now as
wide as its longest entry plus a gap, and never narrower than the old fixed
width, so a table of short entries prints exactly as it always did.

A streamed line is printed before the rest of its table exists, so its widths
come from the plan -- the case ids and qtags are known before any call goes
out.  :func:`pad` still guarantees the gap when an entry outgrows the width it
was given, so the worst case is a ragged column, never two columns fused.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

#: Spaces kept between one column's longest entry and the next column.
GAP = 2


def column_widths(rows: Iterable[Sequence[object]], minimums: Sequence[int]) -> list[int]:
    """The width of each column: its longest entry plus :data:`GAP`, at least its minimum."""
    widths = list(minimums)
    for row in rows:
        for index, cell in enumerate(row[: len(widths)]):
            widths[index] = max(widths[index], len(str(cell)) + GAP)
    return widths


def pad(text: object, width: int) -> str:
    """``text`` left-justified to ``width``, always followed by at least :data:`GAP` spaces."""
    text = str(text)
    return text.ljust(max(width, len(text) + GAP))
