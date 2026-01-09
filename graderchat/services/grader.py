from graderchat.services.parselatex import parse_latex_soln
import os
from pathlib import Path
import json
import os
import json

class Grader:
    def __init__(self, questions_root="questions"):
        self.questions_root = questions_root
        self.units = self._discover_units()

    def _discover_units(self):
        units = {}

        # List everything inside the root directory
        for name in os.listdir(self.questions_root):
            folder = os.path.join(self.questions_root, name)

            print(f'Checking folder: {folder}')

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

            # Require exactly one of each
            if len(tex_files) != 1 or len(json_files) != 1:
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

            

            # Check if questions_text length matches parsed items
            if len(questions_text) != len(parsed_items):
                err_msg = f"Warning: In unit '{name}', number of questions in JSON ({len(questions_text)})"\
                    + f" does not match number of parsed items in LaTeX ({len(parsed_items)})."
                print(err_msg)
                continue

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
            }
        if len(units) == 0:
            raise ValueError("No valid directories units found in '%s'." % self.questions_root)
        return units

    def grade(self, question, solution):
        return {
            "status": "correct",   # dummy
            "explanation": "This is a placeholder."
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
