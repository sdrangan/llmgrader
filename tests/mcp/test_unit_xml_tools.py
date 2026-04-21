from xml.etree import ElementTree as ET

from llmgrader.mcp.unit_xml_tools import (
    create_unit_xml_skeleton,
    explain_rubric_rules,
    explain_unit_xml,
    scan_repo_for_unit_inputs,
    validate_unit_xml,
)


def test_explain_unit_xml_returns_expected_shape() -> None:
    result = explain_unit_xml()

    assert "summary" in result
    assert "required_sections" in result
    assert "optional_sections" in result
    assert "validation_rules" in result
    assert "follow_up_questions" in result
    assert "minimal_example_xml" in result
    assert "common_authoring_mistakes" in result


def test_explain_rubric_rules_returns_expected_shape() -> None:
    result = explain_rubric_rules()

    assert "summary" in result
    assert "binary_grading_fields" in result
    assert "partial_credit_fields" in result
    assert "common_mistakes" in result
    assert "minimal_examples" in result


def test_create_unit_xml_skeleton_produces_parseable_xml() -> None:
    xml_text = create_unit_xml_skeleton(
        unit_id="probability_intro",
        title="Probability Intro",
        questions=[
            {
                "qtag": "q1",
                "question_text": "State the sample space for a fair coin toss.",
                "solution": "{H, T}",
                "required": True,
                "partial_credit": False,
                "parts": [{"part_label": "all", "points": 1}],
            }
        ],
    )

    root = ET.fromstring(xml_text)

    assert root.tag == "unit"
    assert root.get("id") == "probability_intro"
    assert root.find("question") is not None


def test_validate_unit_xml_accepts_minimal_valid_example() -> None:
    xml_text = create_unit_xml_skeleton(
        unit_id="probability_intro",
        title="Probability Intro",
        questions=[
            {
                "qtag": "q1",
                "question_text": "State the sample space for a fair coin toss.",
                "solution": "{H, T}",
                "required": True,
                "partial_credit": False,
                "parts": [{"part_label": "all", "points": 1}],
            }
        ],
    )

    result = validate_unit_xml(unit_xml=xml_text)

    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_unit_xml_rejects_missing_unit_id_and_solution() -> None:
    xml_text = """\
<unit>
  <question qtag="q1">
    <question_text>Prompt only</question_text>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>1</points>
      </part>
    </parts>
  </question>
</unit>
"""

    result = validate_unit_xml(unit_xml=xml_text)

    assert result["valid"] is False
    assert any("unit id" in error for error in result["errors"])
    assert any("<solution>" in error for error in result["errors"])


def test_validate_unit_xml_rejects_partial_credit_rubric_without_point_adjustment() -> None:
    xml_text = """\
<unit id="probability_intro">
  <question qtag="q1">
    <question_text>Find the probability.</question_text>
    <solution>1/2</solution>
    <required>true</required>
    <partial_credit>true</partial_credit>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>2</points>
      </part>
    </parts>
    <rubrics>
      <item id="setup">
        <display_text>Correct setup</display_text>
        <condition>Student sets up the event correctly.</condition>
      </item>
    </rubrics>
  </question>
</unit>
"""

    result = validate_unit_xml(unit_xml=xml_text)

    assert result["valid"] is False
    assert any("point_adjustment" in error for error in result["errors"])


def test_validate_unit_xml_surfaces_multipart_rubric_semantic_error() -> None:
    xml_text = """\
<unit id="probability_intro">
  <question qtag="q1">
    <question_text>Two-part question</question_text>
    <solution>Reference solution</solution>
    <required>true</required>
    <partial_credit>true</partial_credit>
    <parts>
      <part><part_label>a</part_label><points>2</points></part>
      <part><part_label>b</part_label><points>2</points></part>
    </parts>
    <rubrics>
      <item id="global_step" part="all" point_adjustment="+4">
        <display_text>Global step</display_text>
        <condition>Student does the whole task correctly.</condition>
      </item>
    </rubrics>
    <rubric_total>sum_positive</rubric_total>
  </question>
</unit>
"""

    result = validate_unit_xml(unit_xml=xml_text)

    assert result["valid"] is False
    assert any("does not allow rubric item" in error for error in result["errors"])


def test_scan_repo_for_unit_inputs_finds_xml_rubrics_assets_and_authoring_files(tmp_path) -> None:
    (tmp_path / "units").mkdir()
    (tmp_path / "units" / "intro.xml").write_text("<unit><question qtag='q1'><rubrics></rubrics><parts><part><part_label>all</part_label><points>1</points></part></parts></question></unit>", encoding="utf-8")
    (tmp_path / "figures").mkdir()
    (tmp_path / "notes.md").write_text("authoring notes", encoding="utf-8")

    result = scan_repo_for_unit_inputs(workspace_root=str(tmp_path))

    assert "units/intro.xml" in result["unit_xml_candidates"]
    assert "units/intro.xml" in result["rubric_example_candidates"]
    assert "figures" in result["asset_directories"]
    assert "notes.md" in result["authoring_files"]