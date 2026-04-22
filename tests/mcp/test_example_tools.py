import pytest

from llmgrader.mcp.example_tools import get_question_example, list_question_examples
from llmgrader.mcp.server import (
    llmgrader_get_question_example,
    llmgrader_list_question_examples,
)


def test_list_question_examples_returns_curated_catalog() -> None:
    result = list_question_examples()

    assert "summary" in result
    assert "Inspect these before drafting nontrivial unit XML questions" in result["summary"]
    assert result["examples"] == [
        {
            "id": "calculus_exponential_derivative",
            "description": "Differentiate a^x and justify the result using logarithms or exponential form.",
            "features": ["binary_grading", "rubric_groups", "single_part"],
        },
        {
            "id": "calculus_exponential_graphing",
            "description": "Analyze critical points and sketch the graph of x e^{-x} on x >= 0.",
            "features": ["partial_credit", "question_include_image", "multi_part"],
        },
        {
            "id": "calculus_integration_by_parts",
            "description": "Evaluate a definite integral with integration by parts and partial-credit rubric steps.",
            "features": ["partial_credit", "single_part"],
        },
    ]


def test_get_question_example_returns_serialized_question_xml() -> None:
    result = get_question_example("calculus_integration_by_parts")

    assert result["id"] == "calculus_integration_by_parts"
    assert result["filename"] == "calculus.xml"
    assert result["qtag"] == "Integration by parts"
    assert "<question qtag=\"Integration by parts\"" in result["question_xml"]
    assert "<![CDATA[" in result["question_xml"]
    assert "<question_text><![CDATA[" in result["question_xml"]
    assert "<rubric_total>sum_positive</rubric_total>" in result["question_xml"]


def test_get_question_example_raises_for_unknown_id() -> None:
    with pytest.raises(ValueError, match="Unknown question example id"):
        get_question_example("missing_example")


def test_server_wrappers_expose_question_examples() -> None:
    result = llmgrader_list_question_examples()

    assert any(example["id"] == "calculus_exponential_derivative" for example in result["examples"])

    example = llmgrader_get_question_example("calculus_exponential_graphing")

    assert example["qtag"] == "Exponential graphing"
    assert "<question qtag=\"Exponential graphing\"" in example["question_xml"]
    assert "<solution><![CDATA[" in example["question_xml"]