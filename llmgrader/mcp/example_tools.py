from __future__ import annotations

from pathlib import Path
import re
from xml.etree import ElementTree as ET


QUESTION_EXAMPLES: dict[str, dict[str, str]] = {
    "calculus_exponential_derivative": {
        "id": "calculus_exponential_derivative",
        "filename": "calculus.xml",
        "qtag": "Exponential derivative",
        "description": "Differentiate a^x and justify the result using logarithms or exponential form.",
        "features": ['binary_grading', 'rubric_groups', 'single_part'],
    },
    "calculus_integration_by_parts": {
        "id": "calculus_integration_by_parts",
        "filename": "calculus.xml",
        "qtag": "Integration by parts",
        "description": "Evaluate a definite integral with integration by parts and partial-credit rubric steps.",
        "features": ['partial_credit', 'single_part'],
    },
    "calculus_exponential_graphing": {
        "id": "calculus_exponential_graphing",
        "filename": "calculus.xml",
        "qtag": "Exponential graphing",
        "description": "Analyze critical points and sketch the graph of x e^{-x} on x >= 0.",
        "features": ['partial_credit', 'question_include_image', 'multi_part'],
    },
}


def list_question_examples() -> dict:
    examples = [
        {
            "id": metadata["id"],
            "description": metadata["description"],
            "features": metadata["features"],
        }
        for metadata in QUESTION_EXAMPLES.values()
    ]
    return {
        "summary": "Curated question XML examples available from llmgrader.mcp.examples. Inspect these before drafting nontrivial unit XML questions with partial credit, multiple parts, images, or rubric logic.",
        "examples": sorted(examples, key=lambda example: example["id"]),
    }


def get_question_example(example_id: str) -> dict:
    metadata = QUESTION_EXAMPLES.get(example_id)
    if metadata is None:
        raise ValueError(f"Unknown question example id: {example_id}")

    xml_path = _resolve_examples_dir() / metadata["filename"]
    xml_text = _read_xml_text(xml_path)
    root = _parse_xml_file(xml_path)
    _find_question_by_qtag(root, metadata["qtag"])

    return {
        "id": metadata["id"],
        "description": metadata["description"],
        "filename": metadata["filename"],
        "qtag": metadata["qtag"],
        "question_xml": _extract_question_xml(xml_text, metadata["qtag"]),
    }


def _resolve_examples_dir() -> Path:
    return Path(__file__).resolve().parent / "examples"


def _read_xml_text(xml_path: Path) -> str:
    try:
        return xml_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read example XML file {xml_path.name}: {exc}") from exc


def _parse_xml_file(xml_path: Path) -> ET.Element:
    if not xml_path.exists():
        raise ValueError(f"Example XML file does not exist: {xml_path.name}")

    try:
        return ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Failed to parse example XML file {xml_path.name}: {exc}") from exc


def _find_question_by_qtag(root: ET.Element, qtag: str) -> ET.Element:
    for question in root.findall("question"):
        if (question.get("qtag") or "").strip() == qtag:
            return question
    raise ValueError(f"Could not find <question> with qtag '{qtag}'.")


def _extract_question_xml(xml_text: str, qtag: str) -> str:
    qtag_pattern = re.escape(qtag)
    match = re.search(
        rf"<question\b[^>]*\bqtag=\"{qtag_pattern}\"[^>]*>.*?</question>",
        xml_text,
        flags=re.DOTALL,
    )
    if match is None:
        raise ValueError(f"Could not extract raw <question> XML for qtag '{qtag}'.")
    return match.group(0)
