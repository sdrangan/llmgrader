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
            file = request.files.get("file")
            if not file:
                return jsonify({"error": "No file uploaded"}), 400

            text = file.read().decode("utf-8")
            parsed = self.grader.load_solution_file(text)
            return jsonify(parsed)

        @bp.get("/units")
        def units():
            return jsonify(list(self.grader.units.keys()))

        @bp.get("/unit/<unit_name>")
        def unit(unit_name):
            units = self.grader.units

            if unit_name not in units:
                return jsonify({"error": "Unknown unit"}), 404

            u = units[unit_name]   # dict keyed by qtag

            return jsonify({
                "unit": unit_name,
                "qtags": list(u.keys()),
                "items": u
            })

        @bp.post("/grade")
        def grade():
            data = request.json

            unit = data["unit"]
            qtag = data["qtag"]                     # NEW: qtag instead of index
            student_soln = data["student_solution"]
            part_label = data.get("part_label", "all")
            model = data.get("model", "gpt-4.1-mini")
            api_key = data.get("api_key", None)

            # Retrieve the question data
            u = self.grader.units[unit]

            if qtag not in u:
                return jsonify({"error": f"Unknown qtag '{qtag}'"}), 400

            qdata = u[qtag]

            ref_problem = qdata["question_latex"]
            ref_solution = qdata["solution"]
            grading_notes = qdata["grading_notes"]

            # Save grader inputs for debugging
            safe_qtag = qtag.replace(" ", "_").replace("/", "_")
            fn = os.path.join(
                self.grader.scratch_dir,
                f"grade_input_{unit}_{safe_qtag}.txt"
            )

            with open(fn, "w") as f:
                f.write(f"Unit: {unit}\n")
                f.write(f"Qtag: {qtag}\n\n")

                f.write("=== Reference Problem (LaTeX) ===\n")
                f.write(ref_problem + "\n\n")

                f.write("=== Reference Solution ===\n")
                f.write(ref_solution + "\n\n")

                f.write("=== Grading Notes ===\n")
                f.write(grading_notes + "\n\n")

                f.write("=== Student Solution ===\n")
                f.write(student_soln + "\n")

                f.write("\n=== Grading Part Label ===\n")
                f.write(part_label + "\n")

                f.write("\n=== Model ===\n")
                f.write(model + "\n")

            print(f"Sent grader input {fn}")

            # Call the grader
            grade_result = self.grader.grade(
                question_latex=ref_problem,
                ref_solution=ref_solution,
                grading_notes=grading_notes,
                student_soln=student_soln,
                part_label=part_label,
                model=model,
                api_key=api_key
            )

            return jsonify(grade_result)

        @bp.post("/reload")
        def reload_units():
            print("In /reload endpoint")
            self.grader.discover_units()
            return jsonify({"status": "ok"})

        @app.route("/admin")
        def admin_page():
            return render_template("admin.html")

        @app.route("/admin/upload", methods=["POST"])
        def upload():
            if "file" not in request.files:
                return {"error": "no file"}, 400

            f = request.files["file"]
            self.grader.save_uploaded_file(f)

            return {"status": "ok"}

        app.register_blueprint(bp)