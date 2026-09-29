"""Console tables keep their columns apart however long a qtag or case id is.

The tables used fixed widths, so a long qtag ran straight into the next
column ("Accelerator throughput and FIFO deptha=5 [5-]").  These pin the
helper, both tools' line printers, and one real ``llmgrader_answer -v`` run.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from llmgrader.scripts._columns import GAP, column_widths, pad
from llmgrader.scripts.llmgrader_answer import _AnswerPrinter
from llmgrader.scripts.llmgrader_answer import main as llmgrader_answer_main
from llmgrader.scripts.llmgrader_test import _CasePrinter

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_UNIT = REPO_ROOT / "example_repo" / "unit1" / "calculus.xml"

LONG_QTAG = "Accelerator throughput and FIFO depth under bursty load"


def _column_starts(lines: list[str], token: str) -> set[int]:
    return {line.index(token) for line in lines}


def test_pad_keeps_the_minimum_width_for_short_text() -> None:
    assert pad("ok", 8) == "ok      "


def test_pad_always_leaves_a_gap_after_long_text() -> None:
    assert pad("x" * 30, 10) == "x" * 30 + " " * GAP


def test_column_widths_grow_to_the_longest_entry_but_not_below_the_minimum() -> None:
    rows = [("a", "short"), ("b", "a considerably longer entry")]
    assert column_widths(rows, (6, 10)) == [6, len("a considerably longer entry") + GAP]


def test_answer_lines_align_on_a_long_qtag_once_the_plan_is_known(capsys) -> None:
    planned = [
        SimpleNamespace(case_id="ai_short_1", qtag="Short"),
        SimpleNamespace(case_id="ai_long_1", qtag=LONG_QTAG),
    ]
    printer = _AnswerPrinter()
    printer.plan([SimpleNamespace(planned=planned)])
    for item in planned:
        printer(SimpleNamespace(
            error=None, is_empty=False, is_refusal=False,
            case_id=item.case_id, qtag=item.qtag, model="gpt-test",
        ))

    lines = capsys.readouterr().out.splitlines()
    assert len(_column_starts(lines, "gpt-test")) == 1
    assert f"{LONG_QTAG}  " in lines[1]


def test_case_lines_align_on_a_long_qtag_once_the_plan_is_known(capsys) -> None:
    cases = [
        SimpleNamespace(case_id="short_correct", qtag="Short"),
        SimpleNamespace(case_id="a_long_case_id_for_the_accelerator", qtag=LONG_QTAG),
    ]
    printer = _CasePrinter()
    printer.plan([SimpleNamespace(case=case) for case in cases])
    for case in cases:
        printer(SimpleNamespace(
            verdict="PASS", case_id=case.case_id, qtag=case.qtag, attempts=[],
            partial_credit=True, model="gpt-test",
        ))

    lines = capsys.readouterr().out.splitlines()
    assert len(_column_starts(lines, "gpt-test")) == 1
    assert "a_long_case_id_for_the_accelerator  " in lines[1]
    assert f"{LONG_QTAG}  " in lines[1]


def test_answer_cli_streams_aligned_lines_for_a_long_qtag(tmp_path, monkeypatch, capsys) -> None:
    unit = tmp_path / "calculus.xml"
    unit.write_text(
        EXAMPLE_UNIT.read_text(encoding="utf-8").replace(
            'qtag="Exponential derivative"', f'qtag="{LONG_QTAG}"'
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "llmgrader.scripts.llmgrader_answer._caller_factory",
        lambda: lambda **_: (lambda: ("An answer.", 11, 7)),
    )

    code = llmgrader_answer_main([str(unit), "--api-key", "k", "-v", "--jobs", "1"])

    assert code == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  ok")]
    assert len(lines) == 3
    long_line = next(line for line in lines if LONG_QTAG in line)
    assert f"{LONG_QTAG}  " in long_line
    # The model column starts at the same offset on every line.
    assert len({len(line) - len(line.split()[-1]) for line in lines}) == 1
