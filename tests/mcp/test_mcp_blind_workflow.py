from pathlib import Path
import shutil

from llmgrader.mcp.config_xml_tools import (
    create_config_skeleton,
    get_llmgrader_config_structure,
    scan_repo_for_config_inputs,
    validate_config_xml,
)


FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def _copy_fixture_repo(tmp_path: Path, fixture_name: str) -> Path:
    fixture_root = FIXTURES_ROOT / fixture_name
    destination = tmp_path / fixture_name
    shutil.copytree(fixture_root, destination)
    return destination


def test_blind_empty_repo_guidance(tmp_path: Path) -> None:
    _copy_fixture_repo(tmp_path, "empty_course_repo")

    result = get_llmgrader_config_structure()

    assert "llmgrader_config.xml" in result["summary"]
    assert result["structure"]["llmgrader"]["children"]["course"]["required"] is True
    assert result["structure"]["llmgrader"]["children"]["units"]["children"]["unit"]["multiple"] is True
    assert result["structure"]["llmgrader"]["children"]["assets"]["required"] is False
    assert any(rule == "At least one <unit> is required under <units>." for rule in result["semantic_rules"])


def test_blind_probability_repo_scan(tmp_path: Path) -> None:
    repo_root = _copy_fixture_repo(tmp_path, "probability_repo")

    result = scan_repo_for_config_inputs(workspace_root=str(repo_root))

    assert result["unit_xml_candidates"] == [
        "units/combinatorics.xml",
        "units/random_variables.xml",
    ]
    assert "figures" in result["asset_directories"]


def test_blind_probability_repo_create_and_validate(tmp_path: Path) -> None:
    repo_root = _copy_fixture_repo(tmp_path, "probability_repo")
    scan_result = scan_repo_for_config_inputs(workspace_root=str(repo_root))

    units = [
        {
            "name": Path(relative_path).stem,
            "source": relative_path,
            "destination": Path(relative_path).name,
        }
        for relative_path in scan_result["unit_xml_candidates"]
    ]
    assets = [{"source": "figures", "destination": "probability_assets"}]

    xml_text = create_config_skeleton(
        course_name="Probability",
        term="Fall 2026",
        units=units,
        assets=assets,
    )
    validation_result = validate_config_xml(
        config_xml=xml_text,
        workspace_root=str(repo_root),
    )

    assert "<name>Probability</name>" in xml_text
    assert "<term>Fall 2026</term>" in xml_text
    assert validation_result == {"valid": True, "errors": [], "warnings": []}


def test_blind_invalid_destination_rejected(tmp_path: Path) -> None:
    _copy_fixture_repo(tmp_path, "probability_repo")
    xml_text = """\
<llmgrader>
  <course>
    <name>Probability</name>
    <term>Fall 2026</term>
  </course>
  <units>
    <unit>
      <name>random_variables</name>
      <source>units/random_variables.xml</source>
      <destination>../badpath.xml</destination>
    </unit>
  </units>
</llmgrader>
"""

    result = validate_config_xml(config_xml=xml_text)

    assert result["valid"] is False
    assert any("must not contain '..'" in error for error in result["errors"])


def test_blind_missing_source_warning(tmp_path: Path) -> None:
    repo_root = _copy_fixture_repo(tmp_path, "empty_course_repo")
    xml_text = """\
<llmgrader>
  <course>
    <name>Probability</name>
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

    result = validate_config_xml(config_xml=xml_text, workspace_root=str(repo_root))

    assert result["valid"] is True
    assert result["errors"] == []
    assert any("source path does not exist" in warning for warning in result["warnings"])
