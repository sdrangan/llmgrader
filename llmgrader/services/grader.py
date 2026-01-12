import textwrap
from llmgrader.services.parselatex import parse_latex_soln, get_text_soln, extract_json_block
import os
import shutil
from pathlib import Path
import json
import os
import json
import pandas as pd
from openai import OpenAI
import xml.etree.ElementTree as ET
import pandas as pd

from llmgrader.services.repo import load_from_repo


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
                 remote_repo : str | None = "https://github.com/sdrangan/hwdesign-soln.git"
                 ):
        """
        Main Grader service class.

        Parameters
        ----------
        questions_root: str
            Path to the root directory containing question units.
        scratch_dir: str
            Path to the scratch directory for temporary files.
        remote_repo: str | None
            URL of the remote git repository containing questions.
            If None, no repository is loaded.
        """
        self.questions_root = questions_root
        self.scratch_dir = scratch_dir
        self.remote_repo = remote_repo

    
    
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
        Discovers question units in the local_repo directory.
        """

        # Load the git repo if specified
        self.local_repo = os.path.join(os.getcwd(), 'soln_repo')
        if self.remote_repo is not None:
            print('Loading questions repository from:', self.remote_repo)
            load_from_repo(self.remote_repo, target_dir=self.local_repo)
            print('Git repository loaded into:', self.local_repo)

        # Log the search process
        log = open(os.path.join(self.scratch_dir, "discovery_log.txt"), "w")

        # Look for the units.csv file in the local_repo directory
        units_csv_path = os.path.join(self.local_repo, "units.csv")

        # Check if units.csv exists
        if not os.path.exists(units_csv_path):
            log.write(f'No units.csv file found in {self.local_repo}.\n')
            self.units = {}
            log.close()
            return
        
        # Check if has required columns
        units_df = pd.read_csv(units_csv_path)
        required = {"unit_name", "soln_fn"}
        if not required.issubset(units_df.columns):
            missing = required - set(units_df.columns)
            log.write(f"units.csv is missing required columns: {missing}\n")
            self.units = {}
            log.close()
            return
        
        # Get the columns as lists        
        self.units_list = units_df['unit_name'].tolist()
        self.soln_fn_list = units_df['soln_fn'].tolist()

        units = {}

    
        # Loop over each unit and specified solution file
        for name, soln_fn in zip(self.units_list, self.soln_fn_list):
            soln_fn = os.path.normpath(soln_fn)
            tex_path = os.path.join(self.local_repo, soln_fn)
            soln_folder = os.path.dirname(tex_path)

            log.write(f'Processing unit: {name}\n')
            log.write(f'  Solution file: {soln_fn}\n')

            # Check that the path exists
            if not os.path.exists(tex_path):
                log.write(f"Skipping unit {name}: file {tex_path} does not exist.\n")
                continue

            # Load LaTeX (original source)
            with open(tex_path, "r", encoding="utf-8") as f:
                latex_text = f.read()

            # Parse the latex solution 
            parsed_items = parse_latex_soln(latex_text)

            questions_latex = []
            ref_soln = []
            grading = []
            for item in parsed_items:
                q = item["question"]
                if q is None:
                    q = "No question found"
                questions_latex.append(q)
                s = item["solution"]
                if s is None:
                    s = "No solution provided"
                ref_soln.append(s)

            log.write(f'  Parsed items: {len(parsed_items)}\n')

            # Get the question text JSON, either by loading existing or generating new
            base = os.path.basename(soln_fn)      # "soln.tex"
            stem, _ = os.path.splitext(base)      # ("soln", ".tex")
            question_fn = stem + ".json"          # "soln.json"
            question_fn = os.path.join(soln_folder, question_fn)


            # Check if an ASCII version of the question text exists
            if os.path.exists(question_fn):
                log.write(f'  Found existing question text JSON file: {question_fn}\n')
                try:
                    with open(question_fn, "r", encoding="utf-8") as f:
                        questions_text = json.load(f)
                except Exception:
                    log.write(f'  Failed to load existing question text file.\n')  
                    questions_text = None
            else:
                log.write(f'  No existing question text JSON file found: {question_fn}\n')
                questions_text = None

            # Check if questions_text is valid
            if not (questions_text is None):
                if (len(questions_text) != len(parsed_items)):
                    log.write(f'  Existing question text has {len(questions_text)} items, expected {len(parsed_items)}.\n')
                    questions_text = None 

            # If not valid, use the LaTeX version
            if questions_text is None:
                questions_text = questions_latex
                log.write(f'  Using LaTeX question text as fallback.\n')

            # Parse the grade_schema.xml file to get the grading notes and part labels
            grade_schema_path = os.path.join(soln_folder, f"grade_schema.xml")
            if not os.path.exists(grade_schema_path):
                log.write(f'  No grading_schema.xml file found in {soln_folder}. Using empty grading notes.\n')
                # Create empty grading notes and part labels
                grading = [""] * len(questions_latex)
                part_labels = [["all"] for _ in range(len(questions_latex))]
            else:
                log.write(f'  Found grading_schema.xml file: {grade_schema_path}\n')
                questions = parse_grading_schema(grade_schema_path)
                grading = [q["grading"] for q in questions]
                part_labels = [q["part_labels"] for q in questions]
                log.write(f'  Parsed grading notes and part labels from {grade_schema_path}\n')

            # Save unit info
            units[name] = {
                "folder": soln_folder,
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
