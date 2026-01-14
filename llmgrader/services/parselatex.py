# Parses LaTeX documents and grading_schema 
# to extract information from all the environments
import re
import textwrap
import xml.etree.ElementTree as ET

def find_duplicates(seq):
    """
    Finds duplicate items in a sequence.

    Parameters
    ----------
    seq:  iterable
        Sequence to check for duplicates.
    Returns
    -------
    dupes:  set
        Set of duplicate items found in the sequence.
    """
    seen = set()
    dupes = set()
    for x in seq:
        if x in seen:
            dupes.add(x)
        else:
            seen.add(x)
    return dupes

def extract_enumerate_body(latex: str) -> str | None:
    """
    Extract the content inside the first *top-level* enumerate environment.
    Correctly handles nested enumerate/itemize environments.
    """
    # Find the first \begin{enumerate}
    m = re.search(r'\\begin{enumerate}', latex)
    if not m:
        return None

    start = m.end()  # position right after \begin{enumerate}
    i = start
    n = len(latex)
    depth = 1  # we've seen one \begin{enumerate}

    while i < n:
        # Look for any \begin{...} or \end{...}
        if latex.startswith(r'\begin{', i):
            m2 = re.match(r'\\begin\{([^\}]*)\}', latex[i:])
            if m2:
                env = m2.group(1)
                if env == 'enumerate':
                    depth += 1
                i += len(m2.group(0))
                continue

        if latex.startswith(r'\end{', i):
            m2 = re.match(r'\\end\{([^\}]*)\}', latex[i:])
            if m2:
                env = m2.group(1)
                if env == 'enumerate':
                    depth -= 1
                    if depth == 0:
                        # i is at the backslash of the matching \end{enumerate}
                        end = i
                        return latex[start:end]
                i += len(m2.group(0))
                continue

        i += 1

    # If we get here, the enumerate wasn't properly closed
    return None

def split_top_level_items(body: str) -> list[str]:
    items = []
    i = 0
    n = len(body)

    current = []
    depth_env = 0
    seen_first_item = False

    while i < n:
        # Detect environment begin
        if body.startswith(r'\begin{', i):
            m = re.match(r'\\begin\{([^\}]*)\}', body[i:])
            if m:
                env = m.group(1)
                if env in ('enumerate', 'itemize'):
                    depth_env += 1
                current.append(body[i:i+len(m.group(0))])
                i += len(m.group(0))
                continue

        # Detect environment end
        if body.startswith(r'\end{', i):
            m = re.match(r'\\end\{([^\}]*)\}', body[i:])
            if m:
                env = m.group(1)
                if env in ('enumerate', 'itemize'):
                    depth_env -= 1
                current.append(body[i:i+len(m.group(0))])
                i += len(m.group(0))
                continue

        # Detect top-level \item
        if body.startswith(r'\item', i) and depth_env == 0:
            if seen_first_item:
                # flush previous item
                item_text = ''.join(current).strip()
                if item_text:
                    items.append(item_text)
                current = []
            else:
                seen_first_item = True

            # consume \item
            current.append(r'\item')
            i += len(r'\item')
            continue

        # Default: accumulate characters
        current.append(body[i])
        i += 1

    # Only flush the final item if we actually saw an \item
    if seen_first_item:
        item_text = ''.join(current).strip()
        if item_text:
            items.append(item_text)

    # Remove leading \item from each item
    cleaned = [
        re.sub(r'^\\item\s*', '', it, flags=re.S)
        for it in items
    ]

    return cleaned

def extract_qtag_and_text(item: str) -> dict:
    """
    Extract qtag, question text, and solution text from a LaTeX item.

    Expected structure:

        \qtag{...}  question text
        \begin{solution}
            solution text
        \end{solution}

    Returns:
        {
            "qtag": str | None,
            "latex": str,        # question text only
            "solution": str | None
        }
    """

    # --- 1. Extract qtag if present ---
    qtag = None
    m = re.match(r'\\qtag\{([^}]*)\}\s*(.*)', item, re.S)
    if m:
        qtag = m.group(1).strip()
        body = m.group(2)
    else:
        body = item

    # --- 2. Extract solution environment if present ---
    sol_pattern = r'\\begin{solution}(.*?)\\end{solution}'
    sol_match = re.search(sol_pattern, body, re.S)

    if sol_match:
        solution_text = sol_match.group(1).strip()
        # Remove the entire solution environment from the question text
        question_text = re.sub(sol_pattern, '', body, flags=re.S).strip()
    else:
        solution_text = None
        question_text = body.strip()

    return {
        "qtag": qtag,
        "latex": question_text,
        "solution": solution_text,
    }


def parse_latex_soln(
        latex: str) -> dict[str, dict]:
    r"""
    This method parses a LateX document of the form:

    <front matter>
    \begin{enumerate}
        \item \qtag{...} 
        Question 1 text
        \begin{solution}
        Solution 1 text
        \end{solution}
         ...
        \item \qtag{...} 
        Question 2 text
        \begin{solution}
        Solution 2 text
        \end{solution}
        ...
    \end{enumerate}


    Full pipeline:
    - find enumerate
    - split items
    - extract qtags

    Parameters
    ----------
    latex:  str
        Full LaTeX document text.
    
    Returns
    -------
    soln_dict:  dict[str, dict]
        A dictionary with key of the qtags with each value
         being a dictionary with "question" and "solution" keys.
    """
    body = extract_enumerate_body(latex)
    if body is None:
        return {}

    raw_items = split_top_level_items(body)

    soln_dict = {}
    for it in raw_items:
        d = extract_qtag_and_text(it)
        qtag = d["qtag"]
        if qtag is None:
            raise ValueError("Some questions in LaTeX are missing qtags.")
        if qtag in soln_dict:
            err_msg = f"Duplicate qtags {qtag} found in LaTeX:\n"
            raise ValueError(err_msg)
        soln_dict[qtag] = {
            "question_latex": d["latex"],
            "solution": d["solution"],
        }
    
    return soln_dict


class SchemaError(Exception):
    """Custom exception for schema validation errors."""
    pass


def parse_grade_schema(schema_path: str) -> dict:
    """
    Parse grade_schema.xml, extract qtags, validate uniqueness,
    and return a dictionary keyed by qtag.

    Parameters
    ----------
    schema_path: str
        Path to grade_schema.xml file.
    
    Returns
    -------
    schema_dict: dict[str,dict]
        Dictionary keyed by qtag, with each value being a dictionary:
            {
                qtag: {
                    "id": str,
                    "grading_notes": str | None,
                    "grade": bool,
                    "parts": [...],
                    "preferred_model": str | None
                },
                ...
            }
    """

    tree = ET.parse(schema_path)
    root = tree.getroot()

    schema_dict = {}
    seen_qtags = set()

    for qnode in root.findall("question"):
        qtag_node = qnode.find("qtag")

        # --- 1. Missing qtag ---
        if qtag_node is None or not (qtag_node.text and qtag_node.text.strip()):
            qid = qnode.get("id", "<no id>")
            raise SchemaError(f"Missing <qtag> in question id={qid}")

        qtag = qtag_node.text.strip()

        # --- 2. Duplicate qtag ---
        if qtag in seen_qtags:
            raise SchemaError(f"Duplicate qtag found in schema: '{qtag}'")
        seen_qtags.add(qtag)

        # --- 3. Extract other fields (optional but useful) ---
        grading_notes_node = qnode.find("grading_notes")
        grade_node = qnode.find("grade")
        preferred_model_node = qnode.find("preferred_model")

        if grading_notes_node is None:
            grading_notes = ""
        else:
            grading_notes = grading_notes_node.text or ""
            grading_notes = textwrap.dedent(grading_notes).strip()

        # Extract parts
        parts_list = []
        parts_node = qnode.find("parts")
        if parts_node is not None:
            for p in parts_node.findall("part"):
                part_label = p.findtext("part_label", "").strip()
                points = p.findtext("points", "").strip()
                parts_list.append({
                    "part_label": part_label,
                    "points": points,
                })

        # Build dictionary entry
        schema_dict[qtag] = {
            "id": qnode.get("id"),
            "grading_notes": grading_notes,
            "grade": (grade_node.text.strip().lower() == "true") if grade_node is not None else False,
            "parts": parts_list,
            "preferred_model": preferred_model_node.text.strip() if preferred_model_node is not None else None
            #"xml_node": qnode,   # keep original node for future updates
        }

    return schema_dict
    