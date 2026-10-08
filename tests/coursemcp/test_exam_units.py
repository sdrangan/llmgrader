"""Typed units, and units published to the course MCP alone (plans/exam_units.md).

The properties that would fail silently:

* an MCP-only unit must stay off the portal -- an old exam in the unit menu
  next to the homework is the confusion the second list exists to avoid;
* one in both configs would be served twice, so the build refuses it;
* its figures must resolve, though they are built somewhere else in the
  package than a portal unit's;
* list_questions(unit_type=...) must return that type's questions only.
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

from llmgrader.coursemcp.materials import (
    MaterialsError,
    build_materials,
    read_config,
    read_unit_types,
    read_units,
)
from llmgrader.services.unit_parser import DEFAULT_UNIT_TYPE, UnitParser

from test_course_content import TOKEN, UNIT, build_app, call, payload  # noqa: E402

EXAM = "Midterm, Spring 2026"
PNG = b"\x89PNG\r\n\x1a\n" + b"exam-figure"
EXAM_SOLUTION = "EXAM-SOLUTION-SENTINEL"

EXAM_XML = f"""<unit id="midterm_s2026" title="{EXAM}" version="1.0"
      unit_type="midterm" semester="Spring 2026">
  <question qtag="Counter">
    <question_text><![CDATA[<p>Draw the counter.</p>
<img src="/pkg_assets/midterm_s2026_images/counter.png">]]></question_text>
    <solution><![CDATA[<p>{EXAM_SOLUTION}</p>]]></solution>
    <grading_notes><![CDATA[Reset must be synchronous.]]></grading_notes>
    <partial_credit>true</partial_credit>
    <rubric_total>sum_positive</rubric_total>
    <parts><part><part_label>all</part_label><points>4</points></part></parts>
    <rubrics>
      <item id="reset" part="all" point_adjustment="4">
        <display_text>Synchronous reset</display_text>
        <condition>Reset is sampled on the clock edge.</condition>
      </item>
    </rubrics>
  </question>
  <question qtag="Signed types">
    <question_text><![CDATA[<p>What width is needed?</p>]]></question_text>
    <solution><![CDATA[<p>Ten bits.</p>]]></solution>
    <grading_notes><![CDATA[None.]]></grading_notes>
    <parts><part><part_label>all</part_label><points>2</points></part></parts>
  </question>
</unit>
"""

MCP_CONFIG = """<llmgrader_mcp>
  <units>
    <unit section="Past exams">exams/midterm_s2026.xml</unit>
  </units>
  <unit_types>
    <unit_type id="midterm" title="Midterm exam">
      Pen and paper, closed book.
      About five minutes a problem.
    </unit_type>
    <unit_type id="final" title="Final exam">Cumulative.</unit_type>
  </unit_types>
</llmgrader_mcp>
"""

PORTAL_CONFIG = f"""<llmgrader>
  <course><course_id>alpha</course_id><name>Alpha Course</name><semester>Fall 2026</semester></course>
  <units>
    <unit><name>{UNIT}</name><source>unit.xml</source><destination>unit.xml</destination></unit>
  </units>
</llmgrader>
"""


def write_source(src: Path, mcp_config: str = MCP_CONFIG) -> Path:
    """A course repository with one portal unit and one MCP-only exam."""
    (src / "exams" / "images").mkdir(parents=True)
    (src / "exams" / "midterm_s2026.xml").write_text(EXAM_XML, encoding="utf-8")
    (src / "exams" / "images" / "counter.png").write_bytes(PNG)
    (src / "llmgrader_config.xml").write_text(PORTAL_CONFIG, encoding="utf-8")
    (src / "unit.xml").write_text("""<unit id="u" title="U" version="1.0">
  <question qtag="Q"><question_text>Q?</question_text><solution>A.</solution>
    <parts><part><part_label>all</part_label><points>1</points></part></parts></question>
</unit>""", encoding="utf-8")
    config = src / "llmgrader_mcp_config.xml"
    config.write_text(mcp_config, encoding="utf-8")
    return config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app = build_app(tmp_path, monkeypatch, token=TOKEN)
    config = write_source(tmp_path / "src")
    pkg = tmp_path / "storage" / "courses" / "alpha" / "soln_pkg"
    build_materials(read_config(config), pkg, log=lambda *_: None,
                    units=read_units(config), unit_types=read_unit_types(config))
    return app.test_client()


def items(result: dict) -> list:
    assert not result.get("isError"), result
    return result["structuredContent"]["result"]


# ---------------------------------------------------------------------------
# Unit attributes (phase 1)
# ---------------------------------------------------------------------------


def parse_one(tmp_path: Path, unit_xml: str) -> dict:
    (tmp_path / "u.xml").write_text(unit_xml, encoding="utf-8")
    parser = UnitParser(scratch_dir=str(tmp_path), soln_pkg=str(tmp_path))
    units, metadata, errors = parser.parse_unit_files([("U", "u.xml")])
    assert not errors and "U" in units
    return metadata["U"]


def test_a_unit_without_the_attributes_is_a_problem_set(tmp_path) -> None:
    meta = parse_one(tmp_path, EXAM_XML.replace('unit_type="midterm" semester="Spring 2026"', ""))
    assert meta == {"digitalsign": False, "unit_type": DEFAULT_UNIT_TYPE, "semester": ""}


def test_the_attributes_are_parsed(tmp_path) -> None:
    meta = parse_one(tmp_path, EXAM_XML)
    assert meta["unit_type"] == "midterm" and meta["semester"] == "Spring 2026"


def test_a_unit_type_is_a_key_not_free_text(tmp_path) -> None:
    (tmp_path / "u.xml").write_text(EXAM_XML.replace('"midterm"', '"Mid Term"'), encoding="utf-8")
    assert UnitParser.validate_unit_file(str(tmp_path / "u.xml"))


# ---------------------------------------------------------------------------
# The build (phase 2)
# ---------------------------------------------------------------------------


def test_a_unit_in_both_configs_fails_the_build(tmp_path) -> None:
    config = write_source(tmp_path, MCP_CONFIG.replace("exams/midterm_s2026.xml", "unit.xml"))
    with pytest.raises(MaterialsError, match="also in llmgrader_config.xml"):
        read_units(config)


def test_a_name_the_portal_uses_fails_the_build(tmp_path) -> None:
    config = write_source(tmp_path, MCP_CONFIG.replace(
        '<unit section="Past exams">', f'<unit section="Past exams" name="{UNIT}">'))
    with pytest.raises(MaterialsError, match="portal already has a unit named"):
        read_units(config)


def test_an_invalid_unit_fails_the_build(tmp_path) -> None:
    config = write_source(tmp_path)
    exam = tmp_path / "exams" / "midterm_s2026.xml"
    exam.write_text(EXAM_XML.replace("<parts>", "<nonsense/><parts>", 1), encoding="utf-8")
    with pytest.raises(MaterialsError, match="not valid"):
        read_units(config)


def test_the_unit_is_named_by_its_title_and_carries_its_section(tmp_path) -> None:
    [spec] = read_units(write_source(tmp_path))
    assert (spec.name, spec.section) == (EXAM, "Past exams")


def test_unit_type_descriptions_are_read_with_whitespace_collapsed(tmp_path) -> None:
    types = read_unit_types(write_source(tmp_path))
    assert types[0] == {"id": "midterm", "title": "Midterm exam",
                        "description": "Pen and paper, closed book. About five minutes a problem."}


def test_create_soln_pkg_builds_the_unit_into_the_zip(tmp_path, monkeypatch) -> None:
    from llmgrader.scripts import create_soln_pkg

    src = tmp_path / "src"
    write_source(src)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    monkeypatch.setattr(sys, "argv", ["create_soln_pkg", "--config", str(src / "llmgrader_config.xml")])
    assert create_soln_pkg.main() == 0

    archive = zipfile.ZipFile(out / "soln_package.zip")
    names = set(archive.namelist())
    assert "mcp_materials/units/midterm_s2026.xml" in names
    assert "mcp_materials/units/midterm_s2026_images/counter.png" in names
    manifest = json.loads(archive.read("mcp_materials/manifest.json"))
    assert manifest["units"] == [{"name": EXAM, "section": "Past exams",
                                  "file": "units/midterm_s2026.xml"}]
    assert [t["id"] for t in manifest["unit_types"]] == ["midterm", "final"]
    # The portal's config is untouched: it never lists the exam.
    assert "midterm" not in archive.read("llmgrader_config.xml").decode()


# ---------------------------------------------------------------------------
# Serving (phases 2 and 3)
# ---------------------------------------------------------------------------


def test_list_units_adds_the_exam_under_its_section(client) -> None:
    units = items(call(client, "list_units", {"course_id": "alpha"}))
    assert units[-2:] == [
        {"type": "section", "name": "Past exams"},
        {"type": "unit", "name": EXAM, "questions": 2, "unit_type": "midterm",
         "semester": "Spring 2026"},
    ]
    assert {"type": "unit", "name": UNIT, "questions": 3, "unit_type": "problem_set"} in units


def test_the_portal_does_not_list_the_exam(client) -> None:
    response = client.get("/c/alpha/units")
    assert response.status_code == 200
    assert EXAM not in response.get_data(as_text=True)


def test_every_unit_tool_serves_the_exam(client) -> None:
    args = {"course_id": "alpha", "unit": EXAM, "qtag": "Counter"}
    question = call(client, "get_question", args)
    assert "Draw the counter" in payload(question)["question"]
    # The figure resolves through /pkg_assets, as a portal unit's does.
    images = [b for b in question["content"] if b["type"] == "image"]
    assert len(images) == 1 and "figure_notes" not in payload(question)
    assert payload(call(client, "get_rubric", args))["rubric"][0]["id"] == "reset"
    assert EXAM_SOLUTION in payload(call(client, "get_solution", args))["solution"]


def test_unit_lookup_is_forgiving_for_the_exam_too(client) -> None:
    result = call(client, "list_questions", {"course_id": "alpha", "unit": "midterm,  spring 2026"})
    assert {q["unit"] for q in items(result)} == {EXAM}


def test_list_questions_filters_by_unit_type(client) -> None:
    exam = items(call(client, "list_questions", {"course_id": "alpha", "unit_type": "midterm"}))
    assert [(q["unit"], q["qtag"]) for q in exam] == [(EXAM, "Counter"), (EXAM, "Signed types")]
    every = items(call(client, "list_questions", {"course_id": "alpha"}))
    assert {q["unit"] for q in every} == {UNIT, EXAM}
    homework = items(call(client, "list_questions", {"course_id": "alpha", "unit_type": "problem_set"}))
    assert {q["unit"] for q in homework} == {UNIT}


def test_list_unit_types(client) -> None:
    types = items(call(client, "list_unit_types", {"course_id": "alpha"}))
    assert types == [
        {"unit_type": "problem_set", "units": [UNIT]},  # undescribed: its id alone
        {"unit_type": "midterm", "title": "Midterm exam",
         "description": "Pen and paper, closed book. About five minutes a problem.",
         "units": [EXAM]},
        # Described but no past unit yet: still says what this term's will be.
        {"unit_type": "final", "title": "Final exam", "description": "Cumulative.", "units": []},
    ]


def test_a_course_without_mcp_units_is_unchanged(tmp_path, monkeypatch) -> None:
    client = build_app(tmp_path, monkeypatch, token=TOKEN).test_client()
    units = items(call(client, "list_units", {"course_id": "alpha"}))
    assert [u["name"] for u in units if u["type"] == "unit"] == [UNIT]
    assert items(call(client, "list_unit_types", {"course_id": "alpha"})) == [
        {"unit_type": "problem_set", "units": [UNIT]}]


def test_the_instructions_point_at_list_unit_types(client) -> None:
    from test_course_content import rpc
    response = rpc(client, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "t", "version": "1"}})
    assert "list_unit_types" in response.get_json()["result"]["instructions"]
