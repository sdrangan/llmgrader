"""create_qfile --print: a unit's <print> block (plans/exam_units.md, decision 5).

The properties that would fail silently:

* <print> must be invisible to the grader and the MCP -- they read question
  dicts, so a unit with and without it must parse to the same ones;
* an answer page must name the problem it follows, after a reorder too;
* a qtag the unit does not have must fail validation, not drop a question
  from the printed exam.
"""

import re
import sys
from pathlib import Path

import pytest

from llmgrader.scripts import create_qfile
from llmgrader.services.unit_parser import UnitParser

QUESTIONS = """
  <question qtag="Counter">
    <question_text><![CDATA[<p>Design the counter.</p>]]></question_text>
    <solution><![CDATA[<p>COUNTER-SOLUTION</p>]]></solution>
    <parts>
      <part><part_label>a</part_label><points>4</points></part>
      <part><part_label>b</part_label><points>6</points></part>
    </parts>
  </question>
  <question qtag="Widths">
    <question_text><![CDATA[<p><strong>Widths.</strong> How many bits?</p>]]></question_text>
    <solution><![CDATA[<p>WIDTHS-SOLUTION</p>]]></solution>
    <parts><part><part_label>all</part_label><points>2.5</points></part></parts>
  </question>
  <question qtag="FIFO">
    <question_text><![CDATA[<p>Fill in the timing table.</p>]]></question_text>
    <solution><![CDATA[<p>FIFO-SOLUTION</p>]]></solution>
    <parts><part><part_label>all</part_label><points>12</points></part></parts>
  </question>
"""

EXAM_BLOCK = """
  <print id="exam">
    <title_page>
      <title>Midterm, Fall 2026</title>
      <course>ECE-GY 6463: Advanced Hardware Design</course>
      <instructors>Profs. Rangan and Garg</instructors>
      <date>October 28, 2026</date>
      <duration>75 minutes</duration>
      <fields><field>Name</field><field>NetID</field></fields>
      <instructions>
        <item>Closed book; <code>no</code> calculators.</item>
        <item>Write in the space provided.</item>
      </instructions>
    </title_page>
    <question qtag="FIFO" answer_pages="2"/>
    <question qtag="Counter"/>
  </print>
  <print id="handout" answer_pages="0" page_per_question="false"/>
"""


def unit_xml(blocks: str = "") -> str:
    return f'<unit id="mid" title="Midterm" version="1.0" unit_type="midterm">{QUESTIONS}{blocks}</unit>'


def run(tmp_path, monkeypatch, blocks: str, *args: str) -> tuple[int, str]:
    unit = tmp_path / "mid.xml"
    unit.write_text(unit_xml(blocks), encoding="utf-8")
    out = tmp_path / "out.html"
    monkeypatch.setattr(sys, "argv", ["create_qfile", "--input", str(unit),
                                      "--output", str(out), *args])
    code = create_qfile.main()
    return code, out.read_text(encoding="utf-8") if out.exists() else ""


def body_text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.split("<body>", 1)[1]).split())


def test_print_is_invisible_to_the_parser(tmp_path) -> None:
    parsed = []
    for name, blocks in (("plain", ""), ("printed", EXAM_BLOCK)):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "u.xml").write_text(unit_xml(blocks), encoding="utf-8")
        parser = UnitParser(scratch_dir=str(folder), soln_pkg=str(folder))
        units, metadata, errors = parser.parse_unit_files([("U", "u.xml")])
        assert errors == []
        parsed.append((units, metadata))
    assert parsed[0] == parsed[1]


def test_exam_title_page_points_and_total(tmp_path, monkeypatch) -> None:
    code, html = run(tmp_path, monkeypatch, EXAM_BLOCK, "--print", "exam")
    assert code == 0
    text = body_text(html)
    for expected in ("Midterm, Fall 2026", "ECE-GY 6463: Advanced Hardware Design",
                     "Profs. Rangan and Garg", "October 28, 2026, 75 minutes",
                     "Name:", "NetID:", "Write in the space provided."):
        assert expected in text
    assert "<code>no</code>" in html  # inline markup in an instruction is kept
    # Printed subset: FIFO (12) and Counter (10); Widths is left out.
    assert "Total 22" in text
    assert "Problem 1. FIFO (12 points)" in text
    assert "Problem 2. Counter (10 points)" in text
    assert "How many bits" not in text


def test_answer_pages_follow_each_problem_and_name_it(tmp_path, monkeypatch) -> None:
    _, html = run(tmp_path, monkeypatch, EXAM_BLOCK, "--print", "exam")
    sequence = re.findall(r"Problem (\d)\.|Use this page for Problem (\d)", html)
    assert [a or f"page{b}" for a, b in sequence] == ["1", "page1", "page1", "2", "page2"]
    # Every problem and every answer page starts a new page.
    assert html.count('class="question newpage"') == 2
    assert html.count('class="answer-page newpage"') == 3


def test_a_minimal_handout_block(tmp_path, monkeypatch) -> None:
    _, html = run(tmp_path, monkeypatch, EXAM_BLOCK, "--print", "handout")
    text = body_text(html)
    assert "Use this page" not in text and " newpage\"" not in html
    assert 'class="title-page"' not in html
    # Every question, in document order; a text that opens with its own
    # title is not titled twice.
    assert re.findall(r"Problem \d", text) == ["Problem 1", "Problem 2", "Problem 3"]
    assert "Problem 2 (2.5 points) Widths." in text


def test_soln_adds_the_solutions_and_drops_the_answer_pages(tmp_path, monkeypatch) -> None:
    _, html = run(tmp_path, monkeypatch, EXAM_BLOCK, "--print", "exam", "--soln")
    assert "Midterm, Fall 2026 (Solutions)" in html
    assert "FIFO-SOLUTION" in html and "COUNTER-SOLUTION" in html
    assert "Use this page" not in html


def test_an_unknown_qtag_fails_validation(tmp_path, monkeypatch, capsys) -> None:
    code, _ = run(tmp_path, monkeypatch, '<print id="exam"><question qtag="Nope"/></print>',
                  "--print")
    assert code == 1
    assert "question 'Nope' is not a question in this unit" in capsys.readouterr().out


def test_a_qtag_listed_twice_fails_validation(tmp_path, monkeypatch, capsys) -> None:
    block = '<print id="exam"><question qtag="FIFO"/><question qtag="FIFO"/></print>'
    assert run(tmp_path, monkeypatch, block, "--print")[0] == 1
    assert "listed twice" in capsys.readouterr().out


def test_print_must_come_after_the_questions(tmp_path) -> None:
    unit = tmp_path / "u.xml"
    unit.write_text(unit_xml().replace('<question qtag="Widths">',
                                       '<print id="x"/><question qtag="Widths">'), encoding="utf-8")
    assert UnitParser.validate_unit_file(str(unit))


@pytest.mark.parametrize("args, message", [
    (("--print",), "several <print> blocks (exam, handout)"),
    (("--print", "makeup"), 'No <print id="makeup">'),
])
def test_which_block_is_unambiguous(tmp_path, monkeypatch, capsys, args, message) -> None:
    assert run(tmp_path, monkeypatch, EXAM_BLOCK, *args)[0] == 1
    assert message in capsys.readouterr().out


def test_the_only_block_needs_no_id_and_no_block_prints_every_question(tmp_path, monkeypatch) -> None:
    code, html = run(tmp_path, monkeypatch, '<print id="exam"><title_page/></print>', "--print")
    assert code == 0 and "<h1>Midterm</h1>" in html  # the unit's title on the title page
    assert html.count("Use this page") == 3          # an exam block: one answer page each
    code, html = run(tmp_path, monkeypatch, "", "--print")
    assert code == 0 and len(re.findall(r"Problem \d", body_text(html))) == 3


def test_default_output_name_carries_the_block_id(tmp_path, monkeypatch) -> None:
    unit = tmp_path / "mid.xml"
    unit.write_text(unit_xml(EXAM_BLOCK), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["create_qfile", "--input", str(unit), "--print", "exam", "--soln"])
    assert create_qfile.main() == 0
    assert (tmp_path / "mid_exam_soln.html").exists()
