print("LOADING api.py FROM:", __file__)

import os
from functools import wraps
from flask import Blueprint, request, jsonify, make_response
from flask import render_template, session, Response
import sqlite3
import csv
import io
from datetime import datetime


class APIController:
    def __init__(self, grader):
        self.grader = grader
    
    

    def require_admin(self, f):
        """
        Decorator to protect admin routes with HTTP Basic Authentication.
        
        If LLMGRADER_ADMIN_PASSWORD environment variable is not set, allows all requests (dev mode).
        Otherwise, validates password using HTTP Basic Auth (username is ignored).
        """
        @wraps(f)
        def decorated_function(*args, **kwargs):
            admin_password = os.environ.get('LLMGRADER_ADMIN_PASSWORD')
            
            # Development mode: no password required
            if admin_password is None:
                return f(*args, **kwargs)
            
            # Check HTTP Basic Authentication
            auth = request.authorization
            
            # Validate password (ignore username)
            if not auth or auth.password != admin_password:
                response = make_response(
                    jsonify({"error": "Unauthorized - authentication required"}),
                    401
                )
                response.headers['WWW-Authenticate'] = 'Basic realm="LLM Grader Admin"'
                return response
            
            return f(*args, **kwargs)
        return decorated_function

    def register(self, app):
        bp = Blueprint("api", __name__)

        @bp.get("/")
        def home():
            return render_template("index.html")

        @bp.get("/dashboard")
        def dashboard():
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
            timeout = data.get("timeout", 20)


            # Retrieve the question data
            u = self.grader.units[unit]

            if qtag not in u:
                return jsonify({"error": f"Unknown qtag '{qtag}'"}), 400

            qdata = u[qtag]

            ref_problem = qdata["question_text"]
            ref_solution = qdata["solution"]
            grading_notes = qdata["grading_notes"]

            # Save grader inputs for debugging
            safe_qtag = qtag.replace(" ", "_").replace("/", "_")
            fn = os.path.join(
                self.grader.scratch_dir,
                f"grade_input_{unit}_{safe_qtag}.txt"
            )

            with open(fn, "w", encoding="utf-8") as f:
                f.write(f"Unit: {unit}\n")
                f.write(f"Qtag: {qtag}\n\n")

                f.write("=== Reference Problem (HTML) ===\n")
                f.write(ref_problem + "\n\n")

                f.write("=== Reference Solution (HTML) ===\n")
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
                question_text=ref_problem,
                solution=ref_solution,
                grading_notes=grading_notes,
                student_soln=student_soln,
                part_label=part_label,
                unit_name=unit,
                qtag=qtag,
                model=model,
                api_key=api_key,
                timeout=timeout
            )

            return jsonify(grade_result)

        @bp.post("/reload")
        def reload_units():
            print("In /reload endpoint")
            self.grader.load_unit_pkg()
            return jsonify({"status": "ok"})

        @app.route("/admin")
        @self.require_admin
        def admin_page():
            return render_template("index.html")

        @app.route("/admin/upload", methods=["POST"])
        @self.require_admin
        def upload():
            if "file" not in request.files:
                return {"error": "no file"}, 400

            f = request.files["file"]
            self.grader.save_uploaded_file(f)

            return {"status": "ok"}
        
        @app.route("/admin/dbviewer", methods=["POST"])
        @self.require_admin
        def dbviewer_api():
            """
            JSON API for Analytics view.
            Accepts: { "sql_query": "SELECT ..." }
            Returns: { "columns": [...], "rows": [...], "error": null }
            """

            data = request.get_json(silent=True) or {}
            sql_query = (data.get("sql_query") or "").strip()

            if not sql_query:
                return jsonify({
                    "columns": [],
                    "rows": [],
                    "error": "Please enter a SQL query"
                })

            try:
                conn = sqlite3.connect(self.grader.db_path)
                cursor = conn.cursor()
                cursor.execute(sql_query)

                # Column names
                columns = [desc[0] for desc in cursor.description] if cursor.description else []

                # First 20 rows
                rows = cursor.fetchmany(20)
                conn.close()

                # Timestamp formatting
                if "timestamp" in columns:
                    ts_idx = columns.index("timestamp")
                    formatted = []
                    for row in rows:
                        row = list(row)
                        try:
                            if row[ts_idx]:
                                row[ts_idx] = datetime.fromisoformat(row[ts_idx]).strftime("%Y-%m-%d %H:%M")
                        except Exception:
                            pass
                        formatted.append(tuple(row))
                    rows = formatted

                # Store last query for CSV download
                session["last_sql"] = sql_query

                return jsonify({
                    "columns": columns,
                    "rows": rows,
                    "error": None
                })

            except Exception as e:
                return jsonify({
                    "columns": [],
                    "rows": [],
                    "error": f"SQL Error: {str(e)}"
                })

        

        @app.route("/admin/dbviewer/download")
        @self.require_admin
        def dbviewer_download():
            """
            Download CSV of the last SQL query results.
            """
            sql_query = session.get("last_sql")
            
            if not sql_query:
                return {"error": "No query in session"}, 400
            
            try:
                conn = sqlite3.connect(self.grader.db_path)
                cursor = conn.cursor()
                cursor.execute(sql_query)
                
                # Get column names
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                
                # Get all rows
                rows = cursor.fetchall()
                conn.close()
                
                # Generate CSV
                output = io.StringIO()
                writer = csv.writer(output)
                
                # Write header
                writer.writerow(columns)
                
                # Write data rows
                writer.writerows(rows)
                
                # Create response
                csv_data = output.getvalue()
                output.close()
                
                response = Response(csv_data, mimetype="text/csv")
                response.headers["Content-Disposition"] = "attachment; filename=submissions.csv"
                return response
                
            except Exception as e:
                return {"error": f"Download Error: {str(e)}"}, 500

        @app.route("/admin/submission/<int:sub_id>")
        @self.require_admin
        def submission_detail(sub_id):
            """
            Display detailed view of a single submission.
            """
            try:
                conn = sqlite3.connect(self.grader.db_path)
                conn.row_factory = sqlite3.Row  # Enable column access by name
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM submissions WHERE id = ?", (sub_id,))
                row = cursor.fetchone()
                conn.close()
                
                if not row:
                    return {"error": f"Submission {sub_id} not found"}, 404
                
                # Convert row to dictionary
                row_dict = dict(row)
                
                # Format the row using grader's formatting rules
                formatted_row = self.grader.format_db_entry(row_dict)
                
                return render_template(
                    "admin_submission_detail.html",
                    row=formatted_row,
                    sub_id=sub_id
                )
                
            except Exception as e:
                return {"error": f"Error loading submission: {str(e)}"}, 500
            
        @app.post("/api/admin-login")
        def api_admin_login():
            admin_password = os.environ.get("LLMGRADER_ADMIN_PASSWORD")
            data = request.json or {}

            if admin_password is None:
                return {"ok": True}

            if data.get("password") == admin_password:
                return {"ok": True}

            return {"ok": False}, 401

        app.register_blueprint(bp)