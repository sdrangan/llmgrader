print("LOADING api.py FROM:", __file__)

import os
from flask import Blueprint, request, jsonify
from flask import render_template


class APIController:
    def __init__(self, grader):
        self.grader = grader

    def register(self, app):
        bp = Blueprint("api", __name__)

        @bp.get("/")
        def home():
            return render_template("index.html")

        @bp.post("/chat")
        def chat():
            data = request.json
            msg = data.get("message", "")
            reply = self.llm_client.chat(msg)
            return jsonify({"reply": reply})

        @bp.post("/load_file")
        def load_file():
            # Loads the student solution file
            file = request.files.get("file")
            if not file:
                return jsonify({"error": "No file uploaded"}), 400

            text = file.read().decode("utf-8")

            # Call your grader (which will print something)
            parsed = self.grader.load_solution_file(text)

            # For now, just return a simple response
            return jsonify(parsed)
        
        @bp.get("/units")
        def units():
            # Return the list of unit folder names
            return jsonify(list(self.grader.units.keys()))


        @bp.get("/unit/<unit_name>")
        def unit(unit_name):
            units = self.grader.units

            if unit_name not in units:
                return jsonify({"error": "Unknown unit"}), 404

            u = units[unit_name]

            return jsonify({
                "unit": unit_name,
                "count": len(u["questions_text"]),
                "questions_text": u["questions_text"],
                "questions_latex": u["questions_latex"],
                "solutions": u["solutions"],
                "grading": u["grading"],
                "part_labels": u["part_labels"]
            })
        
        @bp.post("/grade")
        def grade():
            data = request.json 
            unit = data["unit"]
            idx = int(data["question_idx"])
            student_soln = data["student_solution"]
            part_label = data.get("part_label", "all")
            model = data.get("model", "gpt-4.1-mini")
            api_key = data.get("api_key", None)

            u = self.grader.units[unit]

            ref_problem = u["questions_latex"][idx]
            ref_solution = u["solutions"][idx]
            grading_notes = u["grading"][idx]

            # Save the grader inputs for debugging
            fn = os.path.join(self.grader.scratch_dir, f"grade_input_{unit}_{idx}.txt")

            with open(fn, "w") as f:
                f.write(f"Unit: {unit}\n")
                f.write(f"Question Index: {idx}\n\n")
                f.write("=== Reference Problem (LaTeX) ===\n")
                f.write(ref_problem + "\n\n")

                f.write("=== Reference Solution ===\n")
                f.write(ref_solution + "\n\n")

                f.write("=== Grading Notes ===\n")
                f.write(grading_notes + "\n\n")

                f.write("=== Student Solution ===\n")
                f.write(student_soln + "\n")

                f.write(f"\n=== Grading Part Label ===\n")
                f.write(part_label + "\n")

                f.write(f"\n=== Model ===\n")
                f.write(model + "\n")

            print(f'Sent grader input {fn}')

            # Call the grader with relevant data
            grade = self.grader.grade(
                question_latex=ref_problem, 
                ref_solution=ref_solution, 
                grading_notes=grading_notes, 
                student_soln=student_soln,
                part_label=part_label,
                model=model,
                api_key=api_key)

            return jsonify(grade)
        
        @bp.post("/reload")
        def reload_units():

            print("In /reload endpoint")
   
            # Re-run discovery
            self.grader.discover_units()
            return jsonify({"status": "ok"})

                
        app.register_blueprint(bp)

        print("=== ROUTES REGISTERED ===")
        for rule in app.url_map.iter_rules():
            print(rule)
        print("==========================")
