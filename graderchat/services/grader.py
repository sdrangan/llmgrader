import textwrap
from graderchat.services.parselatex import parse_latex_soln
import os
import shutil
from pathlib import Path
import json
import os
import json
import pandas as pd
from openai import OpenAI

def strip_code_fences(text):
    text = text.strip()
    if text.startswith("```"):
        # remove first fence
        text = text.split("```", 1)[1].strip()
        # remove closing fence if present
        if "```" in text:
            text = text.rsplit("```", 1)[0].strip()
    return text


class Grader:
    def __init__(self, questions_root="questions", scratch_dir="scratch"):
        self.questions_root = questions_root
        self.scratch_dir = scratch_dir

        # Remove old scratch directory if it exists
        if os.path.exists(self.scratch_dir):
            shutil.rmtree(self.scratch_dir)

        # Recreate it fresh
        os.makedirs(self.scratch_dir, exist_ok=True)

        # Discover units
        self.units = self._discover_units() 

        # Create the OpenAI LLM client
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key is None:
            raise RuntimeError("Missing OPENAI_API_KEY environment variable")
        self.client = self.client = OpenAI(api_key=api_key)

    def _discover_units(self):
        units = {}

        # Log the search process
        log = open(os.path.join(self.scratch_dir, "discovery_log.txt"), "w")

        # List everything inside the root directory
        for name in os.listdir(self.questions_root):
            folder = os.path.join(self.questions_root, name)

            # Only consider subdirectories
            if not os.path.isdir(folder):
                continue

            # Find .tex and .json files inside this folder
            tex_files = [
                f for f in os.listdir(folder)
                if f.endswith(".tex")
            ]
            json_files = [
                f for f in os.listdir(folder)
                if f.endswith(".json")
            ]

            log.write(f'Checking folder: {folder}\n')
            log.write(f'  Found .tex files: {tex_files}\n')
            log.write(f'  Found .json files: {json_files}\n')

            # Require exactly one of each
            if len(tex_files) != 1 or len(json_files) != 1:
                log.write(f"Skipping folder {folder}: expected exactly one .tex and one .json file, found {len(tex_files)} .tex and {len(json_files)} .json files.\n")
                continue

            tex_path = os.path.join(folder, tex_files[0])
            json_path = os.path.join(folder, json_files[0])

            # Load JSON (plain‑text questions)
            with open(json_path, "r", encoding="utf-8") as f:
                questions_text = json.load(f)

            # Load LaTeX (original source)
            with open(tex_path, "r", encoding="utf-8") as f:
                latex_text = f.read()

            # Parse the latex solution 
            parsed_items = parse_latex_soln(latex_text)
            questions_latex = []
            ref_soln = []
            grading = []
            for item in parsed_items:
                questions_latex.append(item["question"])
                ref_soln.append(item["solution"])
                grading.append(item["grading"])

            log.write(f'  Parsed items: {len(parsed_items)}\n')

            # Check if questions_text length matches parsed items
            if len(questions_text) != len(parsed_items):
                err_msg = f"Warning: In unit '{name}', number of questions in JSON ({len(questions_text)})"\
                    + f" does not match number of parsed items in LaTeX ({len(parsed_items)})."
                log.write(err_msg + "\n")
                continue

            # Try to read the grade_schema.csv file
            grade_schema_path = os.path.join(folder, "grade_schema.csv")
            if os.path.exists(grade_schema_path):
                log.write(f'  Found grade_schema.csv file.\n')
                part_labels = self.parse_schema(grade_schema_path)
                log.write(f'  Parsed {len(part_labels)} graded parts from schema.\n')
                log.write(f'    Part labels: {part_labels}\n')
            else:
                log.write(f'  No grade_schema.csv file found.\n')
                part_labels = [[] for _ in range(len(questions_text))]

            # Resize parts with empty lists if missing
            if len(part_labels) < len(questions_text):
                log.write(f'  Warning:  Extending part_labels from {len(part_labels)} to {len(questions_text)} with empty lists.\n')
                part_labels += [[] for _ in range(len(questions_text) - len(part_labels))]
            if len(part_labels) > len(questions_text):
                log.write(f'  Warning:  Truncating part_labels from {len(part_labels)} to {len(questions_text)}.\n')
                part_labels = part_labels[:len(questions_text)]



            # Save unit info
            units[name] = {
                "folder": folder,
                "tex_path": tex_path,
                "json_path": json_path,
                "latex": latex_text,
                "questions_text": questions_text,
                "questions_latex": questions_latex,
                "solutions": ref_soln,
                "grading": grading,
                "part_labels": part_labels,
            }

        if len(units) == 0:
            log.write("No valid directories units found.\n")    
            log.close() 
            raise ValueError("No valid directories units found in '%s'." % self.questions_root)
        
        log.close()
        return units
    
    def parse_schema(self, 
                     grade_schema_path : str) -> list[list[str]]:
        """
        Parses the grading schema CSV file.  Right now, we only extract part labels for graded parts.
        Expected CSV columns:
        - question_name: identifier for the question
        - part_label: label for the part (can be empty)

        Parameters
        ----------
        grade_schema_path : str
            Path to the grade_schema.csv file.
        
        Returns:
        --------
        - List of lists of part labels for each question.

        """

        # Read the grade_schema.csv file
        df = pd.read_csv(grade_schema_path)

        # Clean up part_label column
        df["part_label"] = (
            df["part_label"]
            .astype(str)          # convert NaN → "nan"
            .str.strip()          # remove whitespace
            .replace({"nan": None, "": None})
        )

        # Assign question numbers based on row order
        df["qnum"] = (df["question_name"] != df["question_name"].shift()).cumsum()

        # Determine total number of questions
        num_questions = df["qnum"].max()

        # Initialize list-of-lists
        part_labels = [[] for _ in range(num_questions)]

        # Fill in part labels
        for _, row in df.iterrows():
            q = row["qnum"] - 1          # convert 1-based → 0-based index
            label = row["part_label"]
            if label is not None:
                part_labels[q].append(label)

        return part_labels
    
    def build_task_prompt(self, question_latex, ref_solution, grading_notes, student_soln, part_label="all"):

        if part_label == "all":
            # Whole-question grading
            task_top = textwrap.dedent("""
                Your task is to grade a student's solution to an engineering problem.

                You must always return a single JSON object with the fields:
                - "result": "pass", "fail", or "error"
                - "full_explanation": a detailed explanation
                - "summary": a concise 2–3 sentence summary

                Follow these steps exactly:

                1. Read the question, reference solution, grading notes, and student solution.

                2. Compare the student solution to the reference solution to determine correctness.
                - Use the grading notes as guidance.
                - Provide a detailed step-by-step reasoning in "full_explanation".
                - Provide a concise 2–3 sentence summary in "summary".
            """)
        else:
            # Part-specific grading
            task_top = textwrap.dedent("""
                Your task is to grade **part ({part_label})** of a multi-part engineering problem.
                You will be given the entire question, the entire reference solution, and the entire
                student solution. Students may mix parts together or refer to earlier parts. Ignore
                all parts except the one you are asked to grade.

                You must always return a single JSON object with the fields:
                - "result": "pass", "fail", or "error"
                - "full_explanation": a detailed explanation
                - "summary": a concise 2–3 sentence summary

                Follow these steps exactly:

                1. Extract the student's answer for part ({part_label}) from the student solution.
                Students may write answers out of order or embed multiple parts together. Use your
                judgment to isolate the portion corresponding to part ({part_label}).

                2. Compare the student's solution for part ({part_label}) to the corresponding part in the
                reference solution to determine correctness.
                - Use the grading notes as guidance.
                - Provide a detailed step-by-step reasoning in "full_explanation".
                - Provide a concise 2–3 sentence summary in "summary".
            """).format(part_label=part_label)

        task_end = textwrap.dedent("""
            3. If correct:
                {{
                    "result": "pass",
                    "full_explanation": "<explanation>",
                    "summary": "The solution is correct. All required reasoning steps match the reference."
                }}

            4. If incorrect:
                {{
                    "result": "fail",
                    "full_explanation": "<explanation of what is correct and what is wrong>",
                    "summary": "The solution contains errors. The main issues are summarized concisely here."
                }}

            No additional text is allowed outside the JSON object.

            -------------------------
            QUESTION (LaTeX):
            {question_latex}

            REFERENCE SOLUTION:
            {ref_solution}

            GRADING NOTES:
            {grading_notes}

            STUDENT SOLUTION:
            {student_soln}
        """)

        task = task_top + task_end.format(
            question_latex=question_latex,
            ref_solution=ref_solution,
            grading_notes=grading_notes,
            student_soln=student_soln
        )

        return task

    def grade(self, question_latex, ref_solution, grading_notes, student_soln, part_label="all"):
        # ---------------------------------------------------------
        # 1. Build the task prompt
        # ---------------------------------------------------------
        task = self.build_task_prompt(question_latex, ref_solution, grading_notes, student_soln, part_label=part_label)

        # ---------------------------------------------------------
        # 2. Write task prompt to scratch/task.txt
        # ---------------------------------------------------------
        task_path = os.path.join(self.scratch_dir, "task.txt")
        with open(task_path, "w") as f:
            f.write(task)

        # ---------------------------------------------------------
        # 3. Call OpenAI
        # ---------------------------------------------------------
        print('Calling OpenAI for grading...')
        response = self.client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0,
            messages=[{"role": "user", "content": task}]
        )
        content = response.choices[0].message.content
        
        # Remove code fences if present
        content = strip_code_fences(content)

        # ---------------------------------------------------------
        # 4. Save raw response to scratch/resp.json
        # ---------------------------------------------------------
        resp_path = os.path.join(self.scratch_dir, "resp.json")
        with open(resp_path, "w") as f:
            f.write(content)
        print(f'OAI Grader response written to {resp_path}')

        # ---------------------------------------------------------
        # 5. Return parsed JSON to the caller
        # ---------------------------------------------------------
        try:
            return json.loads(content)
        except Exception:
            return {
                "result": "error",
                "full_explanation": "Model returned invalid JSON.",
                "summary": "The model output could not be parsed."
            }
    
    def load_solution_file(self, text):

        # Parse the latex solution file
        items = parse_latex_soln(text)

        quest_list = [item.get("question", "") for item in items]
        soln_list = [item.get("solution", "") for item in items]
        grading_notes_list = [item.get("grading", "") for item in items]
        resp = {
            "num_questions": len(items),
            "questions": quest_list,
            "solutions": soln_list,
            "grading_notes": grading_notes_list
        }
        print("Loaded solution file with %d items." % len(items))
    
    
        # You don’t need to return anything yet
        return resp
