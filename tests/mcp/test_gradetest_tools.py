import os
from xml.etree import ElementTree as ET

from llmgrader.mcp.config_xml_tools import (
    create_config_skeleton,
    get_llmgrader_config_structure,
    validate_config_xml,
)
from llmgrader.mcp.gradetest_tools import (
    get_unit_test_structure,
    validate_unit_test_xml,
)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE_UNIT = os.path.join(REPO_ROOT, "example_repo", "unit1", "calculus.xml")
EXAMPLE_TESTS = os.path.join(REPO_ROOT, "example_repo", "unit1", "tests", "calculus_tests.xml")


def _semester_config(term_tag: str) -> str:
    return (
        "<llmgrader>"
        "  <course>"
        "    <name>Demo</name>"
        f"    <{term_tag}>Spring 2026</{term_tag}>"
        "  </course>"
        "  <units>"
        "    <unit>"
        "      <name>u1</name>"
        "      <source>unit1/u1.xml</source>"
        "      <destination>u1.xml</destination>"
        "    </unit>"
        "  </units>"
        "</llmgrader>"
    )


# ---------------------------------------------------------------------------
# Course metadata
# ---------------------------------------------------------------------------


def test_validate_config_accepts_semester_as_well_as_term() -> None:
    """The schema allows either spelling; the validator used to demand <term>."""
    for tag in ("term", "semester"):
        result = validate_config_xml(config_xml=_semester_config(tag))
        assert result["valid"], f"<{tag}> should be accepted: {result['errors']}"


def test_validate_config_still_requires_one_of_them() -> None:
    config = (
        "<llmgrader>"
        "  <course><name>Demo</name></course>"
        "  <units>"
        "    <unit>"
        "      <name>u1</name>"
        "      <source>unit1/u1.xml</source>"
        "      <destination>u1.xml</destination>"
        "    </unit>"
        "  </units>"
        "</llmgrader>"
    )
    result = validate_config_xml(config_xml=config)

    assert not result["valid"]
    assert any("semester" in error for error in result["errors"])


def test_config_structure_describes_banner_and_section_elements() -> None:
    course = get_llmgrader_config_structure()["structure"]["llmgrader"]["children"]["course"]
    units = get_llmgrader_config_structure()["structure"]["llmgrader"]["children"]["units"]

    assert set(course["children"]) == {"name", "semester", "term", "title", "instructors"}
    assert course["children"]["title"]["required"] is False
    assert course["children"]["instructors"]["required"] is False
    assert "section" in units["children"]


def test_create_config_skeleton_emits_banner_only_when_asked() -> None:
    units = [{"name": "u1", "source": "unit1/u1.xml", "destination": "u1.xml"}]

    without = ET.fromstring(create_config_skeleton(course_name="Demo", term="Spring 2026", units=units))
    assert without.find("course/title") is None
    assert without.find("course/instructors") is None

    with_banner = ET.fromstring(
        create_config_skeleton(
            course_name="Demo",
            term="Spring 2026",
            units=units,
            title="LLM Grader for Demo",
            instructors="Prof. Ada Lovelace",
        )
    )
    assert with_banner.findtext("course/title") == "LLM Grader for Demo"
    assert with_banner.findtext("course/instructors") == "Prof. Ada Lovelace"


# ---------------------------------------------------------------------------
# Grading tests
# ---------------------------------------------------------------------------


def test_unit_test_structure_returns_expected_shape() -> None:
    result = get_unit_test_structure()

    assert set(result) == {
        "summary",
        "authoring_workflow",
        "structure",
        "semantic_rules",
        "examples",
    }

    case = result["structure"]["unit_test"]["children"]["case"]
    assert set(case["attributes"]) == {"id", "qtag"}
    assert {"description", "solution"} <= set(case["children"])
    assert case["children"]["expected_result"]["text_content"]["allowed_values"] == [
        "pass",
        "fail",
        "partial",
        "error",
    ]


def test_validate_unit_test_accepts_the_example_suite() -> None:
    with open(EXAMPLE_TESTS, encoding="utf-8") as handle:
        xml = handle.read()

    result = validate_unit_test_xml(unit_test_xml=xml, unit_path=EXAMPLE_UNIT)

    assert result["valid"], result["errors"]
    assert result["checked_against_unit"] is True


def test_validate_unit_test_without_unit_path_warns_and_skips_cross_checks() -> None:
    with open(EXAMPLE_TESTS, encoding="utf-8") as handle:
        xml = handle.read()

    result = validate_unit_test_xml(unit_test_xml=xml)

    assert result["valid"]
    assert result["checked_against_unit"] is False
    assert any("only the schema" in warning for warning in result["warnings"])


def test_validate_unit_test_rejects_unknown_qtag() -> None:
    xml = (
        '<unit_test><case id="c1" qtag="No Such Question">'
        "<description>d</description><solution>s</solution>"
        "<expected_result>pass</expected_result>"
        "</case></unit_test>"
    )

    result = validate_unit_test_xml(unit_test_xml=xml, unit_path=EXAMPLE_UNIT)

    assert not result["valid"]
    assert any("does not exist" in error for error in result["errors"])


def test_validate_unit_test_reports_schema_errors_without_leaking_temp_path() -> None:
    xml = '<unit_test><case id="c1"><solution>s</solution></case></unit_test>'

    result = validate_unit_test_xml(unit_test_xml=xml)

    assert not result["valid"]
    assert any("qtag" in error for error in result["errors"])
    # The document is written to a scratch file to be validated; that path is an
    # implementation detail and must not surface in the messages.
    assert not any("tmp" in error.lower() for error in result["errors"])
