from xml.etree import ElementTree as ET

from llmgrader.mcp.unit_xml_tools import (
    create_unit_xml_skeleton,
    explain_rubric_rules,
    get_unit_xml_structure,
  plan_question_draft,
    scan_repo_for_unit_inputs,
    validate_unit_xml,
)
from llmgrader.mcp.server import llmgrader_plan_question_draft


def test_get_unit_xml_structure_returns_expected_shape() -> None:
    result = get_unit_xml_structure()

    assert "summary" in result
    assert "authoring_workflow" in result
    assert "recommended_examples" in result
    assert "example_lookup_tools" in result
    assert "structure" in result
    assert "semantic_rules" in result
    assert "examples" in result
    assert result["example_lookup_tools"] == {
      "list_examples": "llmgrader_list_question_examples",
      "get_example": "llmgrader_get_question_example",
    }
    assert result["recommended_examples"][0]["id"] == "calculus_exponential_graphing"
    assert any("inspect a curated example" in step for step in result["authoring_workflow"])
    unit_schema = result["structure"]["unit"]
    assert unit_schema["required"] is True
    assert unit_schema["multiple"] is False
    assert unit_schema["attributes"]["id"]["required"] is True
    question_schema = unit_schema["children"]["question"]
    assert question_schema["multiple"] is True
    assert question_schema["attributes"]["qtag"]["required"] is True
    assert question_schema["children"]["question_text"]["text_content"]["type"] == "html_or_text"
    assert "CDATA" in question_schema["children"]["question_text"]["description"]
    assert "<![CDATA[" in question_schema["children"]["question_text"]["text_content"]["example"]
    assert "CDATA" in question_schema["children"]["solution"]["description"]
    assert "<![CDATA[" in question_schema["children"]["solution"]["text_content"]["example"]
    assert any("condition_type='llm_judge'" in rule for rule in result["semantic_rules"])
    assert any("sum_part_max" in rule for rule in result["semantic_rules"])
    assert question_schema["children"]["rubrics"]["related_tools"] == [
      {
        "name": "llmgrader_explain_rubric_rules",
        "when_to_use": (
          "Use this tool for more detailed rubric authoring guidance, including binary "
          "versus partial-credit rubric rules and rubric_total behavior."
        ),
      }
    ]
    assert question_schema["children"]["parts"]["children"]["part"]["children"]["points"]["text_content"]["type"] == "number"
    assert "one_of" in question_schema["children"]["rubrics"]["children"]["group"]["description"]


def test_explain_rubric_rules_returns_expected_shape() -> None:
    result = explain_rubric_rules()

    assert "summary" in result
    assert "binary_grading_fields" in result
    assert "partial_credit_fields" in result
    assert "common_mistakes" in result
    assert "minimal_examples" in result


def test_plan_question_draft_returns_structured_workflow() -> None:
    result = plan_question_draft(
        task="Draft a multipart partial-credit probability question.",
        workspace_root="tests/fixtures/probability_repo",
    )

    assert "summary" in result
    assert result["task"] == "Draft a multipart partial-credit probability question."
    assert result["workspace_root"] == "tests/fixtures/probability_repo"
    assert len(result["steps"]) == 6
    assert result["steps"][0]["recommended_tool"] == "llmgrader_list_question_examples"
    assert result["steps"][1]["recommended_tool"] == "llmgrader_scan_repo_for_unit_inputs"
    assert result["steps"][2]["recommended_tool"] == "llmgrader_get_question_example"
    assert result["steps"][3]["recommended_tool"] == "llmgrader_get_unit_xml_structure"
    assert result["steps"][4]["recommended_tool"] == "llmgrader_create_unit_xml_skeleton"
    assert result["steps"][5]["recommended_tool"] == "llmgrader_validate_unit_xml"
    assert all("goal" in step for step in result["steps"])
    assert all("reason" in step for step in result["steps"])
    assert all("expected_output" in step for step in result["steps"])


def test_server_wrapper_exposes_plan_question_draft() -> None:
    result = llmgrader_plan_question_draft(
        task="Draft a multipart partial-credit probability question.",
        workspace_root="tests/fixtures/probability_repo",
    )

    assert result["task"] == "Draft a multipart partial-credit probability question."
    assert result["steps"][0]["recommended_tool"] == "llmgrader_list_question_examples"
    assert any(step["recommended_tool"] == "llmgrader_create_unit_xml_skeleton" for step in result["steps"])


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
