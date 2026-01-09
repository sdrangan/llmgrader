import argparse
from pathlib import Path
import textwrap

import re
from openai import OpenAI
import json

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

    # Strip the
    envs = [
        "solution",
        "gradingnotes",
    ]
    for env in envs:
        # Build a pattern like r"\\begin{solution}.*?\\end{solution}"
        pattern = rf"\\begin{{{env}}}.*?\\end{{{env}}}"
        latex_text = re.sub(pattern, "", latex_text, flags=re.DOTALL)

    # Prepare task
    task = textwrap.dedent(r"""
    You are a LaTeX‑to‑plain‑text converter.

    You will be given the full contents of a LaTeX file. The file has the structure:

        <front matter>
        \begin{enumerate}
            \item <question 1 text>
            \item <question 2 text>
            ...
        \end{enumerate}

    Your task:

    1. Ignore all front matter before \begin{enumerate}.
    2. Extract each \item as a separate question.
    3. Convert each question’s LaTeX into clean, readable ASCII text.
    - Remove LaTeX commands.
    - Preserve mathematical meaning using plain text (e.g., "x^2 + y^2").
    - Omit figures, images, and environments that cannot be represented in text.
    4. Return the result as a JSON array of strings, in order.

    Your output must be ONLY valid JSON of the form:

        ["question 1 text", "question 2 text", ...]

    """)

    # Create OpenAI client
    client = OpenAI()

    # Get response
    print('Calling OAI to convert LaTeX to text...')
    response = client.chat.completions.create(
        model=args.model,
        messages=[
            {"role": "system", "content": task},
            {"role": "user", "content": latex_text},
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    # Parse JSON
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON list")
    except Exception as e:
        raise RuntimeError(
            f"Failed to parse JSON output.\nModel returned:\n{raw}"
        ) from e

    # Write output
    print(f'Writing output to {output_path}...')
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()