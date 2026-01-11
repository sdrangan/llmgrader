import textwrap
from graderchat.services.parselatex import parse_latex_soln, get_text_soln, extract_json_block
import os
import shutil
from pathlib import Path
import json
import os
import json
import pandas as pd
from openai import OpenAI
import xml.etree.ElementTree as ET


from pydantic import BaseModel

class GradeResult(BaseModel):
    """
    Data model for the grading result.
    """
    result: str
    full_explanation: str
    feedback: str

def parse_grading_schema(path : str) -> list[dict]:
    """
    Parses the grading schema XML file.

    Parameters
    ----------
    path: str
        Path to the grading_schema.xml file.
    Returns
    -------
    List of question grading schema dictionaries.
    Each dictionary contains:
    - id: Question ID
    - grading_notes: Grading notes text
    - grade: Boolean indicating if the question should be graded
    - preferred_model: Preferred OpenAI model for grading
    - part_labels: List of part labels
    - points: List of points corresponding to each part
    """
    tree = ET.parse(path)
    root = tree.getroot()

    questions = []

    for question in root.findall("question"):
        qid = question.get("id")

        # Extract and clean grading notes (CDATA or plain text)
        raw_notes = question.findtext("grading_notes", default="")
        grading = textwrap.dedent(raw_notes).strip()

        # Boolean field
        grade_flag = question.findtext("grade", default="false").strip().lower() == "true"

        # Preferred model
        preferred_model = question.findtext("preferred_model", default="gpt-4.1-mini").strip()

        # Parts
        part_labels = []
        points = []
        for part in question.find("parts").findall("part"):
            label = part.findtext("part_label").strip()
            points0 = float(part.findtext("points"))    
            part_labels.append(label)
            points.append(points0)

        questions.append({
            "id": qid,
            "grading": grading,
            "grade": grade_flag,
            "preferred_model": preferred_model,
            "part_labels": part_labels,
            "points": points
        })

    return questions


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
    def __init__(self, 
                 questions_root : str ="questions", 
                 scratch_dir : str ="scratch",
                 qtext_reload: bool =True):
        """
        Main Grader service class.

        Parameters
        ----------
        questions_root: str
            Path to the root directory containing question units.
        scratch_dir: str
            Path to the scratch directory for temporary files.
        qtext_reload: bool
            Whether to enable question text reloading.
            This will save time as each reload requires
            reading/parsing LaTeX files.
        """
        self.questions_root = questions_root
        self.scratch_dir = scratch_dir
        self.qtext_reload = qtext_reload

        # Initialize units dictionary
        self.units = {}

        # Remove old scratch directory if it exists
        if os.path.exists(self.scratch_dir):
            shutil.rmtree(self.scratch_dir)

        # Recreate it fresh
        os.makedirs(self.scratch_dir, exist_ok=True)

        # Discover units
        self.discover_units() 


    def discover_units(self):
        """
        Discovers question units in the questions_root directory.
        Each subdirectory is expected to contain exactly one .tex file
        with question and solutions formatted in LaTeX.
        Optionally, a grading_schema.xml file can be included to specify
        grading schema for the questions.
        """
        units = {}

        # Log the search process
        log = open(os.path.join(self.scratch_dir, "discovery_log.txt"), "w")

        # List everything inside the root directory
        for name in os.listdir(self.questions_root):
            folder = os.path.join(self.questions_root, name)

            # Only consider subdirectories
            if not os.path.isdir(folder):
                continue

            # Find .tex files in the folder
            tex_files = [
                f for f in os.listdir(folder)
                if f.endswith(".tex")
            ]
    
            log.write(f'Checking folder: {folder}\n')
            log.write(f'  Found .tex files: {tex_files}\n')

            # Require exactly one latex file
            if len(tex_files) != 1:
                log.write(f"Skipping folder {folder}: expected exactly one .tex file, found {len(tex_files)} .tex files.\n")
                continue
            tex_path = os.path.join(folder, tex_files[0])

            # Check if we need to reload question text
            need_new = False
            questions_path = os.path.join(folder, f"{name}_questions.json")
            if os.path.exists(questions_path):
                log.write(f'  Found existing question text JSON file: {questions_path}\n')
                try:
                    with open(questions_path, "r", encoding="utf-8") as f:
                        questions_text = json.load(f)
                except Exception:
                    log.write(f'  Failed to load existing question text file. Will regenerate.\n')  
                    need_new = True
            else:
                need_new = True


            if need_new:
                log.write(f'  Generating question text JSON using OpenAI...\n')
                # Call the OpenAI to convert LaTeX to text
                questions_text = get_text_soln(tex_path,  model="gpt-4.1-mini")

                # Save the question text for future use
                with open(questions_path, "w", encoding="utf-8") as f:
                    json.dump(questions_text, f)

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

            log.write(f'  Parsed items: {len(parsed_items)}\n')

            # Write parsed question text for debugging
            qtext_fn = os.path.join(self.scratch_dir, f"{name}_questions.txt")
            with open(qtext_fn, "w", encoding="utf-8") as f:
                for i, qtext in enumerate(questions_text):
                    f.write(f"Question {i+1}:\n")
                    f.write(f"---------------\n")
                    f.write(qtext + "\n")
                    f.write("\n")
            log.write(f'  Wrote question text to {qtext_fn}\n')

            # Parse the grade_schema.xml file to get the grading notes and part labels
            grade_schema_path = os.path.join(folder, f"grade_schema.xml")
            if not os.path.exists(grade_schema_path):
                log.write(f'  No grading_schema.xml file found in {folder}. Using empty grading notes.\n')
                # Create empty grading notes and part labels
                grading = [""] * len(questions_latex)
                part_labels = [["all"] for _ in range(len(questions_latex))]
            else:
                questions = parse_grading_schema(grade_schema_path)
                grading = [q["grading"] for q in questions]
                part_labels = [q["part_labels"] for q in questions]
                log.write(f'  Parsed grading notes and part labels from {grade_schema_path}\n')

            # Save unit info
            units[name] = {
                "folder": folder,
                "tex_path": tex_path,
                "latex": latex_text,
                "questions_text": questions_text,
                "questions_latex": questions_latex,
                "solutions": ref_soln,
                "grading": grading,
                "part_labels": part_labels,
            }

        self.units = units

        if len(self.units) == 0:
            log.write("No valid directories units found.\n")    
            log.close() 
            raise ValueError("No valid directories units found in '%s'." % self.questions_root)
        
        log.close()
    
    

    
    def build_task_prompt(self, question_latex, ref_solution, grading_notes, student_soln, part_label="all"):

        if part_label == "all":
            # Whole-question grading
            task_top = textwrap.dedent("""
                Your task is to grade a student's solution to an engineering problem.
                                       
                You will be given a Latex-version of the question, a reference solution that is correct,
                grading notes, and the student solution.  
                                       
                You are to provide the following fields in the response:
                                       
                - "result": "pass", "fail", or "error"
                - "full_explanation": a detailed explanation of your grading reasoning
                - "feedback": concise (up to 5 sentences), student-facing guidance that helps the student improve,
                    without revealing the reference solution or grading notes.
                                       
                Follow these steps exactly:

                1. Read the question, reference solution, grading notes, and student solution.
                2. Carefully compare the student solution to the reference solution, 
                   using the grading notes as guidance.
                
                """)
        else:
            # Part-specific grading
            task_top = textwrap.dedent("""
                Your task is to grade **part ({part_label})** of a multi-part engineering problem.
                You will be given the entire question, the entire reference solution, and the entire
                student solution. Students may mix parts together or refer to earlier parts. Ignore
                all parts except the one you are asked to grade.
                                       
                You are to provide the following fields in the response:
                - "result": "pass", "fail", or "error" (applies to part ({part_label}) only)
                - "full_explanation": a detailed explanation of your grading reasoning
                - "feedback": concise (up to 5 sentences), student-facing guidance that helps the student improve,
                   without revealing the reference solution or grading notes.
                        
                Follow these steps exactly:

                1. Extract the student's answer for part ({part_label}) from the student solution.
                Students may write answers out of order or embed multiple parts together. Use your
                judgment to isolate the portion corresponding to part ({part_label}).

                2. Compare the student's solution for part ({part_label}) to the corresponding part in the
                reference solution to determine correctness, using the grading notes as guidance.
            """).format(part_label=part_label)

        task_end = textwrap.dedent("""
            3. In "full_explanation", first work through your reasoning step by step, explaining what is correct and what is incorrect.
            4. After you have completed your reasoning, decide the overall correctness:
            - If the solution is correct, set "result" to "pass".
            - If the solution is incorrect, set "result" to "fail".
            - If you cannot grade due to missing or inconsistent information, set "result" to "error".
            5. In "feedback", provide concise (up to 5 sentences), student-facing guidance that helps the student improve,
                without revealing the reference solution or grading notes.

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

    def grade(
            self, 
            question_latex: str, 
            ref_solution : str, 
            grading_notes: str, 
            student_soln : str, 
            part_label: str="all", 
            model: str="gpt-4.1-mini",
            api_key: str | None = None) -> GradeResult:
        """
        Grades a student's solution using the OpenAI API.
        
        Parameters
        ----------
        question_latex: str
            The LaTeX text of the question.
        ref_solution: str
            The reference solution text.
        grading_notes: str
            The grading notes text.
        student_soln: str
            The student's solution text.
        part_label: str
            The part label to grade (or "all" for whole question).
        model: str
            The OpenAI model to use for grading.
        api_key: str | None
            The OpenAI API key to use for authentication.

        Returns
        -------
        grade: dictionary corresponding to GradeResult
            The grading dictionary result containing 'result', 'full_explanation', and 'feedback'.
            Note the pydantic GradeResult model is converted to a dict before returning.
        """
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
        if model.startswith("gpt-5-mini"):
            temperature = 1  # gpt-5-mini only allow temperature = 1
        else:
            temperature = 0
        

        # Create the OpenAI LLM client
        if api_key is None:
            grade = {
                'result': 'error', 
                'full_explanation': 'Missing API key.', 
                'feedback': 'Cannot grade without an API key.'}
            return grade 
        try:
            client = OpenAI(api_key=api_key)
        except Exception as e:
            grade = {
                'result': 'error', 
                'full_explanation': f'Failed to create OpenAI client: {str(e)}', 
                'feedback': 'Cannot grade without a valid API key.'}
            return grade

        print('Calling OpenAI for grading...')
        try:
            response = client.responses.parse(
                model=model,
                input=task,
                text_format=GradeResult,
                temperature=temperature
            )   
            print('Received response from OpenAI.')
            grade = response.output_parsed.model_dump()
        except Exception as e:
            grade = {
                'result': 'error', 
                'full_explanation': f'OpenAI API call failed: {str(e)}', 
                'feedback': 'There was an error while trying to grade the solution.'}

        # ---------------------------------------------------------
        # 4. Save raw response to scratch/resp.json
        # ---------------------------------------------------------
        resp_path = os.path.join(self.scratch_dir, "resp.json")
        with open(resp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(grade, indent=2))
        return grade
        
    
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
