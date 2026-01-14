import textwrap
import os
import shutil
from pathlib import Path
import json
import os
import pandas as pd
from openai import OpenAI
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from llmgrader.services.parselatex import parse_latex_soln

from llmgrader.services.repo import load_from_repo


from pydantic import BaseModel

class GradeResult(BaseModel):
    """
    Data model for the grading result.
    """
    result: str
    full_explanation: str
    feedback: str



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
                 remote_repo : str | None = None
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

    def get_local_repo_parent_path(self) -> str:
        """
        Returns the parent directory path for the local repository.
        The repo will be cloned or manually uploaded into this directory.
        So if local_repo is "soln_repo", this function returns the parent directory,
        and the git repo is "hwdesign-soln.git", the full path will be "soln_repo/hwdesign-soln".

        Returns
        -------
        str
            Parent directory path for the local repository.
        """
        # Get the parent directory for the local repo
        env_path = os.environ.get("SOLN_REPO_PATH")
        if env_path:
            parent_repo = env_path
        else:
            parent_repo = os.path.join(os.getcwd(), 'soln_repos')
        
        # If the directory doesn't exist, create it
        os.makedirs(parent_repo, exist_ok=True)
        return parent_repo

    def save_uploaded_file(self, file_storage):
        # file_storage is a Werkzeug FileStorage object
        save_path = os.path.join(self.scratch_dir, file_storage.filename)
        file_storage.save(save_path)
        print(f"Saved uploaded file to {save_path}")

        # Get the parent directory for the local repo
        parent_repo = self.get_local_repo_parent_path()

        # Ensure the repo directory exists (or clear it)
        if os.path.exists(parent_repo):
            shutil.rmtree(parent_repo)
        os.makedirs(parent_repo, exist_ok=True)

        # 3. Unzip into local_repo
        try:
            with zipfile.ZipFile(save_path, "r") as z:
                z.extractall(parent_repo)
            print(f"Extracted uploaded file into {parent_repo}")
        except zipfile.BadZipFile:
            print("Uploaded file is not a valid zip file.")
            return {"error": "Uploaded file is not a valid zip file."}, 400
        
        except Exception as e:
            # Catch-all for unexpected issues
            print(f"Unexpected error while extracting ZIP: {e}")
            return {"error": "Failed to extract ZIP file."}, 500
        
        return {"status": "ok"}


    def discover_units(self):
        """
        Discovers question units in the local_repo directory.
        """
        self.units = {}

        # Log the search process
        log = open(os.path.join(self.scratch_dir, "discovery_log.txt"), "w")
        
        # Write the time and date

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.write(f'Discovery started at {now}\n')

        # Get the parent repo paths
        parent_repo = self.get_local_repo_parent_path()

        # Load the git repo if specified
        if self.remote_repo is not None:
            log.write('Loading questions repository from: ' + self.remote_repo + '\n')
            local_repo = os.path.join(parent_repo, "soln_repo")
            try:
                load_from_repo(self.remote_repo, target_dir=local_repo)
            except Exception as e:
                log.write('Failed to load git repository: ' + str(e) + '\n')
                local_repo = None
            log.write('Git repository loaded into: ' + local_repo + '\n')
        else:
            log.write('No remote repository specified. Using local files only.\n')
            local_repo = None

        # If local_repo is not set, set the candidates to all subdirectories of parent_repo
        if local_repo is None:
            candidates = [
                os.path.join(parent_repo, d)
                for d in os.listdir(parent_repo)
                if os.path.isdir(os.path.join(parent_repo, d))
            ]
        else:
            # Otherwise, just use the local_repo directory
            candidates = [local_repo]

        # Look for the units.csv file in the local_repo directory
        local_repo = None
        for c in candidates:
            units_csv_path = os.path.join(c, "units.csv")
            if os.path.exists(units_csv_path):
                local_repo = c
                log.write(f'Found units.csv in candidate directory: {c}\n')
                break
        
        if local_repo is None:
            log.write('No local repository with units.csv found in ' + parent_repo + '\n')
            self.units = {}
            log.close()
            return
        
        # Check if has required columns
        units_df = pd.read_csv(units_csv_path)
        required = {"unit_name", "json_path"}
        if not required.issubset(units_df.columns):
            missing = required - set(units_df.columns)
            log.write(f"units.csv is missing required columns: {missing}\n")
            self.units = {}
            log.close()
            return
        
        # Get the columns as lists        
        self.units_list = units_df['unit_name'].tolist()
        self.json_path_list = units_df['json_path'].tolist()

        units = {}

        # Loop over each unit and specified solution file
        for name, json_path in zip(self.units_list, self.json_path_list):


            json_path = os.path.normpath(json_path)
            json_path = os.path.join(local_repo, json_path)

            log.write(f'Processing unit: {name}\n')
            log.write(f'  JSON file: {json_path}\n')

            # Check that the path exists
            if not os.path.exists(json_path):
                log.write(f"Skipping unit {name}: file {json_path} does not exist.\n")
                continue

            with open(json_path, "r", encoding="utf-8") as f:
                unit_dict = json.load(f)    

            # Validate the unit_dict has required fields
            required_fields = [
                "question_latex",
                "question_text",
                "solution",
                "grading_notes",
                "parts",
                "id",
                "grade",
            ]

            if not isinstance(unit_dict, dict):
                log.write(f"Skipping unit {name}: JSON content is not a dictionary.\n")
                continue
            
            # Check that every question has the required fields
            for qtag in unit_dict:
                qdict = unit_dict[qtag]
                missing_fields = [field for field in required_fields if field not in qdict]
                if missing_fields:
                    log.write(f"Skipping unit {name}, question {qtag}: missing required fields: {missing_fields}\n")
                    continue
                
            # Log questions found
            log.write(f"Unit {name} successfully loaded with questions:\n")
            for qtag in unit_dict:
                log.write(f"  qtag={qtag} \n")

            units[name] = unit_dict


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
        """
        Parse a student solution file or reference solution file.
        Return a dict keyed by qtag, matching the new JSON structure.
        """

        # Parse the LaTeX solution file
        items = parse_latex_soln(text)   # now returns dict: qtag -> {question, solution, grading}

        if not isinstance(items, dict):
            print("ERROR: parse_latex_soln did not return a dict keyed by qtag.")
            return {"error": "Invalid solution file format"}

        resp = {}
        for qtag, entry in items.items():
            resp[qtag] = {
                "question_latex": entry.get("question_latex", ""),
                "solution": entry.get("solution", ""),
                "grading_notes": entry.get("grading", "")
            }

        print(f"Loaded solution file with {len(resp)} qtags.")
        return resp
    