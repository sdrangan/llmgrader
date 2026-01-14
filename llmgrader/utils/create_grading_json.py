import argparse
from pathlib import Path
import textwrap
from pydantic import BaseModel
import re
from openai import OpenAI
import json
import xml.etree.ElementTree as ET
from llmgrader.services.parselatex import parse_latex_soln, parse_grade_schema


def compare_qtags(
        schema_items : dict[str, dict], 
        latex_items : dict[str, dict]) -> None:
    """
    Raises errors if:
    
    -- Missing qtags in either schema or LaTeX
    """
    
    schema_qtags = set( schema_items.keys() )
    latex_qtags = set( latex_items.keys() )
    missing_in_schema = latex_qtags - schema_qtags
    missing_in_latex = schema_qtags - latex_qtags

    error = False
    if missing_in_schema:
        print("\ngrade_schema.xml is missing qtags:")
        for tag in sorted(missing_in_schema):
            print(f"  - {tag}")
        error = True
 
    if missing_in_latex:
        print("\nlatex.tex is missing qtags:")
        for tag in sorted(missing_in_latex):
            print(f"  - {tag}")
        error = True
  
    if error:
        raise ValueError("Qtag mismatches found; please resolve before proceeding.")
    
    return

class PlainText(BaseModel):
    text: str

def openai_convert(model: str, latex: str) -> str:
    client = OpenAI()

    system_prompt = textwrap.dedent("""
    You are a LaTeX-to-plain-text converter.

    Your job is to convert LaTeX describing an engineering question
    into clean, readable ASCII text.

    Requirements:
    - Remove LaTeX commands.
    - Preserve mathematical meaning using plain text (e.g., "x^2 + y^2").
    - Keep paragraph breaks using newline characters.
    - Omit figures, images, and environments that cannot be represented in text.
    - Do NOT add commentary, explanations, or JSON.
    - Output ONLY the converted ASCII text.
                                    
    Latex to convert:
    -------
    {latex}
    """).format(latex=latex)

    response = client.responses.parse(
        model=model,
        input=system_prompt,
        text_format=PlainText,
        temperature=0.0,
    )


    return response.output_parsed.text

def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert a LaTeX file into plain text using an LLM."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the input LaTeX file (e.g., soln.tex)"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output text file path (default: same name with .json extension)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4.1-mini",
        help="OpenAI model to use (default: gpt-4.1-mini)"
    )

    return parser.parse_args()

def main():
    args = parse_args()

    input_path: Path = args.input
    schema_path = input_path.parent / "grade_schema.xml"
    if not schema_path.exists():
        raise FileNotFoundError(f"grade_schema.xml not found at: {schema_path}")
    
    # Determine default output path
    if args.output is None:
        if input_path.suffix:
            output_path = input_path.with_suffix(".json")
        else:
            output_path = Path(str(input_path) + ".json")
    else:
        output_path = args.output

    # Read LaTeX
    latex_text = input_path.read_text(encoding="utf-8")

    # Parse LaTeX questions
    latex_items = parse_latex_soln(latex_text)

    # Parse grade_schema.xml
    schema_items = parse_grade_schema(str(schema_path))

    # Compare the tags to ensure they are consistent
    compare_qtags(schema_items, latex_items)

    # Merge LaTeX text into schema items
    merged = {}
    for qtag in latex_items:
        merged[qtag] = {
            **latex_items[qtag],     # latex, solution, etc.
            **schema_items[qtag],    # grading_notes, parts, model, etc.
        }

    # Convert latex to plain text with OpenAI
    for qtag  in merged:
        item = merged[qtag]
        print(f'Converting question (qtag={qtag}) with OpenAI...')
        converted_text = openai_convert(args.model, item["question_latex"])
        item["question_text"] = converted_text   

    # Write output
    print(f'Writing output to {output_path}...')
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()