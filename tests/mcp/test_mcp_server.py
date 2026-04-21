from pathlib import Path

from llmgrader.mcp.server import (
    create_config_skeleton,
    scan_repo_for_config_inputs,
    validate_config_xml,
)


def test_create_config_skeleton_generates_required_sections() -> None:
    xml_text = create_config_skeleton(
        course_name="Probability I",
        term="Fall 2026",
        units=[
            {"name": "random_variables", "source": "units/random_variables.xml", "destination": "random_variables.xml"}
        ],
        assets=[{"source": "images", "destination": "prob_assets"}],
    )

    assert "<llmgrader>" in xml_text
    assert "<course>" in xml_text
    assert "<name>Probability I</name>" in xml_text
    assert "<term>Fall 2026</term>" in xml_text
    assert "<units>" in xml_text
    assert "<destination>random_variables.xml</destination>" in xml_text
    assert "<assets>" in xml_text


def test_validate_config_xml_reports_destination_errors() -> None:
    xml_text = """\
<llmgrader>
  <course>
    <name>Probability I</name>
    <term>Fall 2026</term>
  </course>
  <units>
    <unit>
      <name>random_variables</name>
      <source>units/random_variables.xml</source>
      <destination>../escape.xml</destination>
    </unit>
  </units>
</llmgrader>
"""
    result = validate_config_xml(config_xml=xml_text)

    assert result["valid"] is False
    assert any("must not contain '..'" in err for err in result["errors"])


def test_validate_config_xml_uses_schema_for_missing_destination() -> None:
    xml_text = """\
<llmgrader>
  <course>
    <name>Probability I</name>
    <term>Fall 2026</term>
  </course>
  <units>
    <unit>
      <name>random_variables</name>
      <source>units/random_variables.xml</source>
    </unit>
  </units>
</llmgrader>
"""
    result = validate_config_xml(config_xml=xml_text)

    assert result["valid"] is False
    assert any("destination" in err.lower() for err in result["errors"])


def test_validate_config_xml_warns_when_sources_missing(tmp_path: Path) -> None:
    xml_text = """\
<llmgrader>
  <course>
    <name>Probability I</name>
    <term>Fall 2026</term>
  </course>
  <units>
    <unit>
      <name>random_variables</name>
      <source>units/random_variables.xml</source>
      <destination>random_variables.xml</destination>
    </unit>
  </units>
</llmgrader>
"""
    result = validate_config_xml(config_xml=xml_text, workspace_root=str(tmp_path))

    assert result["valid"] is True
    assert any("source path does not exist" in warning for warning in result["warnings"])


def test_scan_repo_for_config_inputs_finds_xml_and_asset_dirs(tmp_path: Path) -> None:
    (tmp_path / "units").mkdir()
    (tmp_path / "units" / "intro.xml").write_text("<unit></unit>", encoding="utf-8")
    (tmp_path / "images").mkdir()

    result = scan_repo_for_config_inputs(workspace_root=str(tmp_path))

    assert "units/intro.xml" in result["unit_xml_candidates"]
    assert "images" in result["asset_directories"]

