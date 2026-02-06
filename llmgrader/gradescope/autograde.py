import argparse
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import sys


if Path("/autograder").exists():
    # If running in Gradescope environment, we use /autograder paths
    SUBMISSION_DIR = Path("/autograder/submission")
    RESULTS_PATH = Path("/autograder/results/results.json")
    SCHEMA_PATH = Path("/autograder/source/grade_schema.xml")
else:
    # Local testing fallback
    SUBMISSION_DIR = Path.cwd() / "submission"
    RESULTS_PATH = Path.cwd() / "results" / "results.json"
    SCHEMA_PATH = Path.cwd() / "grade_schema.xml"

def find_submission_json(submission_dir: Path, verbose: bool = False) -> Path:
    """
    Locate submission_<unit>.json.
    Supports:
      - a zip containing submission_*.json
      - a raw submission_*.json file
    """
    # Look for a zip file
    zips = list(submission_dir.glob("*.zip"))
    if zips:
        zip_path = zips[0]
        if verbose:
            print(f"[debug] Found zip submission: {zip_path}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            candidates = [
                name for name in zf.namelist()
                if re.match(r"submission_.*\.json$", os.path.basename(name))
            ]
            if not candidates:
                raise FileNotFoundError("No submission_*.json found inside zip.")
            target = candidates[0]
            zf.extract(target, submission_dir)
            if verbose:
                print(f"[debug] Extracted submission JSON: {submission_dir / target}")
            return submission_dir / target

    # Otherwise look directly
    json_files = list(submission_dir.glob("submission_*.json"))
    if not json_files:
        raise FileNotFoundError("No submission_*.json found in submission directory.")
    if verbose:
        print(f"[debug] Found submission JSON: {json_files[0]}")
    return json_files[0]


def load_grade_schema(schema_path: Path):
    """
    Parse grade_schema.xml into a list of question dicts:
    [
      {
        "id": "1",
        "qtag": "Sequential updates",
        "grade": True/False,
        "parts": [
          {"label": "all", "points": 10},
          ...
        ]
      },
      ...
    ]
    
    Schema format:
    <unit>
      <question qtag="..." preferred_model="...">
        <question_text>...</question_text>
        <solution>...</solution>
        <grading_notes>...</grading_notes>
        <grade>true/false</grade>
        <parts>
          <part id="all" points="10" />
          OR
          <part>
            <part_label>a</part_label>
            <points>5</points>
          </part>
        </parts>
      </question>
    </unit>
    """
    tree = ET.parse(schema_path)
    root = tree.getroot()

    questions = []
    for idx, q in enumerate(root.findall("question"), start=1):
        qtag = q.get("qtag", f"Question {idx}")

        grade_el = q.find("grade")
        parts_el = q.find("parts")

        grade_flag = (
            grade_el.text.strip().lower() == "true"
            if grade_el is not None and grade_el.text
            else True
        )

        parts = []
        if parts_el is not None:
            for p in parts_el.findall("part"):
                # Support both formats:
                # 1. Attribute-based: <part id="all" points="10" />
                # 2. Element-based: <part><part_label>a</part_label><points>5</points></part>
                part_id = p.get("id")
                part_points = p.get("points")
                
                if part_id and part_points:
                    # Attribute-based format
                    try:
                        points = float(part_points)
                    except Exception:
                        points = 0.0
                    parts.append({"label": part_id, "points": points})
                else:
                    # Element-based format
                    label_el = p.find("part_label")
                    points_el = p.find("points")
                    if label_el is not None and points_el is not None:
                        label = label_el.text.strip() if label_el.text else ""
                        try:
                            points = float(points_el.text.strip())
                        except Exception:
                            points = 0.0
                        parts.append({"label": label, "points": points})

        questions.append(
            {
                "id": str(idx),
                "qtag": qtag,
                "grade": grade_flag,
                "parts": parts,
            }
        )

    return questions


def compute_scores(schema_questions, submission_json, verbose: bool = False):
    """
    Compute total score and per-question breakdown.
    JSON structure:
      {
        "<qtag>": {
          "parts": {
            "<label>": { "grade_status": "pass"/"fail", ... }
          },
          ...
        }
      }
    """
    if not isinstance(submission_json, dict) or not submission_json:
        raise ValueError("Submission JSON is empty or malformed.")

    # Set the unit data
    unit_data = submission_json
    if verbose:
        print(f"[debug] Loaded submission with {len(unit_data)} top-level question entries.")


    total_score = 0.0
    max_score = 0.0
    tests = []
    overall_feedback = []

    for q in schema_questions:
        if not q["grade"]:
            continue  # skip ungraded questions

        qtag = q["qtag"]
        parts = q["parts"]

        q_max = sum(p["points"] for p in parts)
        max_score += q_max

        score_all = 0.0
        score_parts = 0.0
        q_feedback_parts = []
        q_feedback_all = []

        q_json = unit_data.get(qtag)
        if verbose:
            print(f"[debug] Parsing question '{qtag}': parts={len(parts)} present={'yes' if q_json is not None else 'no'}")

        if q_json is None:
            tests.append({
                "name": qtag,
                "score": 0,
                "max_score": q_max,
                "output": "No submission for this question."
            })
            continue

        q_parts_json = q_json.get("parts", {})
        if verbose:
            print(f"[debug] Found parts in submission: {list(q_parts_json.keys())}")

        part_points = {p["label"]: p["points"] for p in parts}

        # Loop over submitted parts to compute scores and gather feedback
        for label, p_json in q_parts_json.items():
            status = (p_json.get("grade_status") or "").strip().lower()
            feedback = p_json.get("feedback") or ""
            explanation = p_json.get("explanation") or ""

            if label == "all":
                score_all = q_max if status == "pass" else 0.0
                if verbose:
                    print(f"[debug] Part '{label}' status='{status}' score={score_all}/{q_max}.")

                if feedback:
                    q_feedback_all.append(f"[{label}] Feedback: {feedback}")
                if explanation:
                    q_feedback_all.append(f"[{label}] Explanation: {explanation}")
                continue

            points = part_points.get(label, 0.0)
            p_score = points if status == "pass" else 0.0
            score_parts += p_score

            if verbose:
                print(f"[debug] Part '{label}' status='{status}' score={p_score}/{points}.")

            if feedback:
                q_feedback_parts.append(f"[{label}] Feedback: {feedback}")
            if explanation:
                q_feedback_parts.append(f"[{label}] Explanation: {explanation}")

        if score_all > score_parts:
            if verbose:
                print(f"[debug] Using 'all' part score {score_all} over parts score {score_parts}.")
            q_feedback = q_feedback_all
            q_score = score_all
        else:
            if verbose:
                print(f"[debug] Using parts score {score_parts} over 'all' part score {score_all}.")
            q_feedback = q_feedback_parts
            q_score = score_parts

            
        # Accumulate total score
        total_score += q_score

        tests.append({
            "name": qtag,
            "score": q_score,
            "max_score": q_max,
            "output": "\n".join(q_feedback) if q_feedback else ""
        })

        if verbose:
            print(f"[debug] Question '{qtag}' score: {q_score}/{q_max}")

        if q_feedback:
            overall_feedback.append(f"Question: {qtag}\n" + "\n".join(q_feedback))

    return {
        "score": total_score,
        "max_score": max_score,
        "tests": tests,
        "output": "\n\n".join(overall_feedback) if overall_feedback else ""
    }


def write_results(results):
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "score": results["score"],
        "output": results["output"],
        "tests": results["tests"],
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(payload, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Autograde submission JSON against schema.")
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print debugging output during grading.",
    )
    parser.add_argument(
        "--submission",
        default=None,
        help="Submission directory (defaults to environment-based SUBMISSION_DIR).",
    )
    args = parser.parse_args()

    try:
        submission_dir = Path(args.submission) if args.submission else SUBMISSION_DIR
        submission_json_path = find_submission_json(submission_dir, verbose=args.verbose)
        with open(submission_json_path, "r") as f:
            submission_json = json.load(f)

        if args.verbose:
            print(f"[debug] Using submission file: {submission_json_path}")
            print(f"[debug] Using schema file: {SCHEMA_PATH}")

        schema_questions = load_grade_schema(SCHEMA_PATH)
        results = compute_scores(schema_questions, submission_json, verbose=args.verbose)
        write_results(results)

    except Exception as e:
        if "args" in locals() and args.verbose:
            print(f"[debug] Autograder error: {e}")
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_PATH, "w") as f:
            json.dump(
                {
                    "score": 0,
                    "output": f"Autograder error: {e}",
                    "tests": [],
                },
                f,
                indent=2,
            )


if __name__ == "__main__":
    main()