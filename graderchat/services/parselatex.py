# parselatex.py:  module for parsing latex solution files

import json
import re
from pathlib import Path
import pandas as pd
from openai import OpenAI
import textwrap
import json 

def extract_json_block(text, left_char="{") -> str | None:
    """
    Extracts the first JSON block from the given text.  This is useful
    for extracting JSON embedded in text in OpenAI responses.
    
    """
    if left_char not in ["{", "["]:
        raise ValueError("left_char must be '{' or '['")
    if left_char == "{":
        right_char = "}"
    else:
        right_char = "]"

    # Find the first '{'
    start = text.find(left_char)
    if start == -1:
        return None

    brace_count = 0
    for i in range(start, len(text)):
        if text[i] == left_char:
            brace_count += 1
        elif text[i] == right_char:
            brace_count -= 1
            if brace_count == 0:
                return text[start:i+1]

    # Unbalanced braces
    return None

def split_top_level_items(enum_body: str) -> list[str]:
    lines = enum_body.splitlines()
    items = []
    current = []
    stack = []
    seen_first_item = False

    for line in lines:
        # Track environment starts
        if "\\begin{" in line:
            env = re.findall(r"\\begin{([^}]+)}", line)
            if env:
                stack.append(env[0])

        # Detect top-level \item
        if line.strip().startswith("\\item") and stack == ["enumerate"]:
            seen_first_item = True
            # Start a new item
            if current:
                items.append("\n".join(current).strip())
                current = []
            current.append(line)
        else:
            if seen_first_item:
                current.append(line)

        # Track environment ends
        if "\\end{" in line:
            env = re.findall(r"\\end{([^}]+)}", line)
            if env and stack and stack[-1] == env[0]:
                stack.pop()

    # Add the last item
    if current:
        items.append("\n".join(current).strip())

    return items

def extract_outer_enumerate(text: str) -> str:
    lines = text.splitlines()
    stack = []
    captured = []
    recording = False

    for line in lines:
        if "\\begin{enumerate}" in line:
            stack.append("enumerate")
            if not recording:
                # This is the OUTER enumerate
                recording = True
                captured.append(line)
                continue

        if "\\end{enumerate}" in line:
            if recording:
                captured.append(line)
            if stack:
                stack.pop()
            if recording and len(stack) == 0:
                # Finished capturing the OUTER enumerate
                return "\n".join(captured)
            continue

        if recording:
            captured.append(line)

    return ""

def parse_latex_soln(text : str) -> list[dict]:
    r"""
    Parse the LaTeX solution file and return a list of items.

    The solution file is expected to have an enumerate environment
    with items that may contain question, solution, and grading notes.

    \begin{enumerate}
    \item Question text
        \begin{solution}
        Solution text
        \end{solution}
        \begin{gradingnotes}
        Grading notes text
        \end{gradingnotes}
    \item Another question...
    \end{enumerate}

    Parameters:
    -----------
    text : str
        Text of the LaTeX solution file.  This should be performed with a file read.
    Returns:
    --------
    List[dict]
        List of items, each item is a dict with keys: question, solution, grading.
        Missing fields are set to None.
    """

    # Extract everything inside the enumerate
    enum_body = extract_outer_enumerate(text)

    # Split into items
    raw_items = split_top_level_items(enum_body)

    # Remove leading empty entry if present
    if raw_items and raw_items[0].strip() == "":
        raw_items = raw_items[1:]

    items = []

    for raw in raw_items:
        raw = raw.strip()

        # Extract question = text before first environment
        # (solution or gradingnotes)
        q_match = re.split(r"\\begin{solution}|\\begin{gradingnotes}", raw, maxsplit=1)
        question = q_match[0].strip() if q_match else None
        if question == "":
            question = None

        # Extract solution
        sol_match = re.search(
            r"\\begin{solution}(.*?)\\end{solution}", raw, re.S
        )
        solution = sol_match.group(1).strip() if sol_match else None

        # Extract grading notes
        grade_match = re.search(
            r"\\begin{gradingnotes}(.*?)\\end{gradingnotes}", raw, re.S
        )
        grading = grade_match.group(1).strip() if grade_match else None

        items.append({
            "question": question,
            "solution": solution,
            "grading": grading
        })

    return items


def load_schema(path: str) -> list[dict]:
    df = pd.read_csv(path)

    # Strip whitespace from all *string* columns except question_name
    for col in df.columns:
        if col != "question_name" and df[col].dtype == object:
            df[col] = df[col].map(lambda x: x.strip() if isinstance(x, str) else x)

    # Normalize booleans
    df['grade'] = df['grade'].str.lower().isin(['1', 'true', 'yes'])

    # Normalize points
    df['points'] = df['points'].astype(int)

    return df.to_dict(orient='records')


def check_soln_core(schema, parsed_items, output_path):
    lines = []
    lines.append("Parsed Solution Summary")
    lines.append("=" * 60)
    lines.append("")

    max_len = max(len(schema), len(parsed_items))

    for i in range(max_len):
        if i < len(schema):
            row = schema[i]
            qname = row["question_name"]
            reqd = row["grade"]
            pts = row["points"]
        else:
            qname = f"Extra item {i+1}"
            reqd = False
            pts = 0

        soln = parsed_items[i].get("solution") if i < len(parsed_items) else None

        lines.append(f"Question {i+1}: {qname}")
        lines.append(f"Required: {'Yes' if reqd else 'No'}")
        lines.append(f"Points: {pts}")

        if soln is None or soln.strip() == "":
            lines.append("Solution: None present")
        else:
            lines.append("Solution:")
            for line in soln.splitlines():
                lines.append(f"    {line}")

        lines.append("-" * 60)
        lines.append("")

        if reqd is True and (soln is None or soln.strip() == ""):
            line = f"WARNING: Required solution for question {i+1} is missing!"
            print(line)
            lines.append(line)

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")

def get_text_soln(
        latex_path: str,
        model : str = "gpt-4.1-mini") -> list[str]:
    r"""
    Given a LaTeX solution file path, extract the text-only versions.

    The latex file is assumed to have the form:

        <front matter>
        \begin{enumerate}
            \item <question 1 text>
            \item <question 2 text>
            ...
        \end{enumerate}

    Before processing, the solution and gradingnotes environments
    are stripped out.

    Parameters:
    -----------
    latex_path : str
        Path to the LaTeX solution file.
    Returns:
    -------- 
    data, list[str]
        List of question texts in plain text.
    """ 
 

    # Read LaTeX
    latex_text = Path(latex_path).read_text(encoding="utf-8")

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
    print('Calling OpenAI to convert LaTeX to text...')
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": task},
            {"role": "user", "content": latex_text},
        ],
        temperature=0,
    )
    print('Finished calling OpenAI to convert LaTeX to text.')

    raw = response.choices[0].message.content.strip()

    # Extract JSON block
    json_block = extract_json_block(raw, left_char="[")
    if json_block is None:
        raise RuntimeError(
            f"Failed to find JSON output.\nModel returned:\n{raw}"
        )
    
    # Parse JSON
    try:
        data = json.loads(json_block)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON list")
    except Exception as e:
        raise RuntimeError(
            f"Failed to parse JSON output.\nModel returned:\n{raw}"
        ) from e

    return data
