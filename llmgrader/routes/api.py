print("LOADING api.py FROM:", __file__)

import os
import json
import secrets
from functools import wraps
from urllib.parse import urlencode
from flask import Blueprint, request, jsonify
from flask import render_template, session, Response, send_from_directory, redirect, url_for
import sqlite3
import csv
import io
from datetime import datetime, timezone
import requests


def get_default_admin_prefs():
    return {
        "openaiApiKey": "",
        "hfToken": "",
        "allowedModels": [],
        "tokenLimit": {
            "limit": 0,
            "period": "hour"
        }
    }


class APIController:
    def __init__(self, grader):
        self.grader = grader

    @staticmethod
    def normalize_email(email: str | None) -> str:
        return (email or "").strip().lower()

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def auth_mode(self) -> str:
        return (os.environ.get("LLMGRADER_AUTH_MODE") or "normal").strip().lower()

    def is_dev_open_mode(self) -> bool:
        return self.auth_mode() == "dev-open"

    def ensure_auth_tables(self) -> None:
        conn = sqlite3.connect(self.grader.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    google_sub TEXT,
                    name TEXT,
                    picture_url TEXT,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_users (
                    email TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    created_by TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        self.bootstrap_initial_admin()

    def bootstrap_initial_admin(self) -> None:
        initial_admin_email = self.normalize_email(
            os.environ.get("LLMGRADER_INITIAL_ADMIN_EMAIL")
        )
        if not initial_admin_email:
            return

        conn = sqlite3.connect(self.grader.db_path)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO admin_users (email, created_at, created_by)
                VALUES (?, ?, ?)
                """,
                (initial_admin_email, self.utc_now(), "bootstrap"),
            )
            conn.commit()
        finally:
            conn.close()

    def is_admin_email(self, email: str | None) -> bool:
        if self.is_dev_open_mode():
            return True

        normalized = self.normalize_email(email)
        if not normalized:
            return False

        conn = sqlite3.connect(self.grader.db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM admin_users WHERE email = ?",
                (normalized,),
            ).fetchone()
            return bool(row)
        finally:
            conn.close()

    def current_user(self) -> dict | None:
        email = self.normalize_email(session.get("user_email"))
        if not email:
            return None
        return {
            "email": email,
            "name": session.get("user_name"),
            "picture": session.get("user_picture"),
            "is_admin": self.is_admin_email(email),
        }

    def oauth_config(self) -> dict | None:
        client_id = (os.environ.get("LLMGRADER_GOOGLE_CLIENT_ID") or "").strip()
        client_secret = (os.environ.get("LLMGRADER_GOOGLE_CLIENT_SECRET") or "").strip()
        if not client_id or not client_secret:
            return None
        return {"client_id": client_id, "client_secret": client_secret}

    def oauth_redirect_uri(self) -> str:
        configured = (os.environ.get("LLMGRADER_GOOGLE_REDIRECT_URI") or "").strip()
        if configured:
            return configured
        return url_for("google_auth_callback", _external=True)

    def upsert_user(self, email: str, google_sub: str, name: str, picture_url: str | None) -> None:
        now = self.utc_now()
        conn = sqlite3.connect(self.grader.db_path)
        try:
            conn.execute(
                """
                INSERT INTO users (email, google_sub, name, picture_url, created_at, last_login_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    google_sub=excluded.google_sub,
                    name=excluded.name,
                    picture_url=excluded.picture_url,
                    last_login_at=excluded.last_login_at
                """,
                (email, google_sub, name, picture_url, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    def get_auth_status(self) -> dict:
        user = self.current_user()
        oauth_ready = self.oauth_config() is not None
        return {
            "authenticated": user is not None,
            "is_admin": bool(user and user.get("is_admin")),
            "user": {
                "email": user.get("email"),
                "name": user.get("name"),
                "picture": user.get("picture"),
            } if user else None,
            "auth_mode": self.auth_mode(),
            "oauth_enabled": oauth_ready,
        }

    def require_authenticated_user(self, f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if self.current_user() is None and not self.is_dev_open_mode():
                return jsonify({"error": "authentication required"}), 401
            return f(*args, **kwargs)
        return decorated_function
    
    def read_admin_hf_token(self) -> str | None:
        """Returns the admin HF token from persistent storage, or None if missing."""
        path = self.grader.get_admin_pref_path()
        if not os.path.exists(path):
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                token = data.get("adminHfToken", "").strip()
                return token if token else None
        except Exception:
            return None

    def require_admin(self, f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if self.is_dev_open_mode():
                return f(*args, **kwargs)

            user = self.current_user()
            if not user or not self.is_admin_email(user.get("email")):
                return jsonify({"error": "admin access required"}), 403

            return f(*args, **kwargs)
        return decorated_function

    def register(self, app):
        self.ensure_auth_tables()
        bp = Blueprint("api", __name__)

        @bp.get("/")
        def home():
            return render_template("index.html")

        @bp.get("/dashboard")
        def dashboard():
            return render_template("index.html")

        @app.get("/auth/login")
        def google_auth_login():
            cfg = self.oauth_config()
            if cfg is None:
                return jsonify({"error": "Google OAuth is not configured"}), 503

            state = secrets.token_urlsafe(24)
            session["oauth_state"] = state
            session["oauth_next"] = "/"
            params = {
                "client_id": cfg["client_id"],
                "redirect_uri": self.oauth_redirect_uri(),
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "access_type": "offline",
                "prompt": "select_account",
            }
            return redirect(
                "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
            )

        @app.get("/auth/callback")
        def google_auth_callback():
            cfg = self.oauth_config()
            if cfg is None:
                return jsonify({"error": "Google OAuth is not configured"}), 503

            expected_state = session.pop("oauth_state", None)
            actual_state = request.args.get("state")
            code = request.args.get("code")
            if not expected_state or expected_state != actual_state or not code:
                return jsonify({"error": "Invalid OAuth callback"}), 400

            token_resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "redirect_uri": self.oauth_redirect_uri(),
                    "grant_type": "authorization_code",
                },
                timeout=10,
            )
            if not token_resp.ok:
                return jsonify({"error": "Failed to exchange OAuth code"}), 400

            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return jsonify({"error": "Missing access token"}), 400

            userinfo_resp = requests.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            if not userinfo_resp.ok:
                return jsonify({"error": "Failed to fetch user profile"}), 400

            profile = userinfo_resp.json()
            email = self.normalize_email(profile.get("email"))
            email_verified = bool(profile.get("email_verified"))
            google_sub = (profile.get("sub") or "").strip()
            name = (profile.get("name") or "").strip()
            picture = (profile.get("picture") or "").strip() or None

            if not email or not email_verified or not google_sub:
                return jsonify({"error": "Google account email must be verified"}), 403

            self.upsert_user(
                email=email,
                google_sub=google_sub,
                name=name,
                picture_url=picture,
            )

            session["user_email"] = email
            session["user_name"] = name
            session["user_picture"] = picture

            return redirect(session.pop("oauth_next", "/"))

        @app.get("/auth/logout")
        def auth_logout():
            session.pop("user_email", None)
            session.pop("user_name", None)
            session.pop("user_picture", None)
            session.pop("oauth_state", None)
            session.pop("oauth_next", None)
            return redirect("/")

        @bp.get("/api/auth/session")
        def auth_session():
            return jsonify(self.get_auth_status())

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
            units_order = getattr(self.grader, 'units_order', None)
            payload = units_order if units_order else [{"type": "unit", "name": k} for k in self.grader.units.keys()]
            return jsonify({
                "items": payload,
                "validation_alert": getattr(self.grader, 'unit_validation_alert', None),
            })

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
            provider = data.get("provider", None)
            timeout = data.get("timeout", 20)
            solution_images = data.get("solution_images", [])

    
            # Retrieve the question data
            u = self.grader.units[unit]

            if qtag not in u:
                return jsonify({"error": f"Unknown qtag '{qtag}'"}), 400

            qdata = u[qtag]

            ref_problem = qdata["question_text"]
            ref_solution = qdata["solution"]
            grading_notes = qdata["grading_notes"]
            tools = qdata.get("tools", [])

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

                f.write("\n=== Tools ===\n")
                f.write(json.dumps(tools) + "\n")

                f.write("\n=== Solution Images ===\n")
                f.write(f"{len(solution_images)} image(s) attached\n")

            print(f"Sent grader input {fn}")

            # Call the grader
            grade_result = self.grader.grade(
                question_dict=qdata,
                student_soln=student_soln,
                part_label=part_label,
                unit_name=unit,
                qtag=qtag,
                model=model,
                provider=provider,
                api_key=api_key,
                timeout=timeout,
                solution_images=solution_images
            )

            return jsonify(grade_result)

        @bp.post("/reload")
        def reload_units():
            print("In /reload endpoint")
            self.grader.load_unit_pkg()
            return jsonify({
                "status": "ok",
                "validation_alert": getattr(self.grader, 'unit_validation_alert', None),
            })

        @bp.get("/pkg_assets/<path:filename>")
        def pkg_assets(filename):
            """Serve static assets (e.g. images) from the uploaded solution package.

            Images referenced in unit XML as ``/pkg_assets/<dest_stem>_images/<file>``
            are resolved here relative to the loaded solution-package directory.
            ``send_from_directory`` prevents directory-traversal attacks.
            """
            soln_pkg = self.grader.soln_pkg
            if not soln_pkg:
                return jsonify({"error": "No solution package has been loaded"}), 404
            return send_from_directory(soln_pkg, filename)

        @bp.get("/api/admin/preferences")
        @self.require_admin
        def get_admin_preferences():
            pref_path = self.grader.get_admin_pref_path()
            defaults = get_default_admin_prefs()

            if not os.path.exists(pref_path):
                return jsonify(defaults)

            try:
                with open(pref_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except (OSError, json.JSONDecodeError):
                return jsonify(defaults)

            merged = {**defaults, **config}
            return jsonify(merged)

        @bp.post("/api/admin/preferences")
        @self.require_admin
        def set_admin_preferences():
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"error": "invalid request body"}), 400

            defaults = get_default_admin_prefs()
            merged = {**defaults, **data}

            pref_path = self.grader.get_admin_pref_path()
            try:
                with open(pref_path, "w", encoding="utf-8") as f:
                    json.dump(merged, f, indent=2)
            except OSError as e:
                return jsonify({"error": str(e)}), 500

            return jsonify({"status": "ok"})

        @bp.get("/api/admin/users")
        @self.require_admin
        def list_admin_users():
            conn = sqlite3.connect(self.grader.db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT a.email, a.created_at, a.created_by, u.name
                    FROM admin_users a
                    LEFT JOIN users u ON u.email = a.email
                    ORDER BY a.email
                    """
                ).fetchall()
            finally:
                conn.close()

            admins = [
                {
                    "email": r[0],
                    "created_at": r[1],
                    "created_by": r[2],
                    "name": r[3],
                }
                for r in rows
            ]
            return jsonify({"admins": admins})

        @bp.post("/api/admin/users")
        @self.require_admin
        def add_admin_user():
            data = request.get_json(silent=True) or {}
            email = self.normalize_email(data.get("email"))
            if not email:
                return jsonify({"error": "email is required"}), 400

            actor = self.current_user()
            actor_email = self.normalize_email(actor.get("email")) if actor else "admin"
            conn = sqlite3.connect(self.grader.db_path)
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO admin_users (email, created_at, created_by)
                    VALUES (?, ?, ?)
                    """,
                    (email, self.utc_now(), actor_email),
                )
                conn.commit()
            finally:
                conn.close()

            return jsonify({"status": "ok"})

        @bp.delete("/api/admin/users/<path:email>")
        @self.require_admin
        def remove_admin_user(email):
            target_email = self.normalize_email(email)
            if not target_email:
                return jsonify({"error": "invalid email"}), 400

            conn = sqlite3.connect(self.grader.db_path)
            try:
                cur = conn.cursor()
                count_row = cur.execute("SELECT COUNT(*) FROM admin_users").fetchone()
                admin_count = count_row[0] if count_row else 0
                exists_row = cur.execute(
                    "SELECT 1 FROM admin_users WHERE email = ?",
                    (target_email,),
                ).fetchone()

                if not exists_row:
                    return jsonify({"error": "admin user not found"}), 404
                if admin_count <= 1:
                    return jsonify({"error": "cannot remove the last admin"}), 400

                cur.execute("DELETE FROM admin_users WHERE email = ?", (target_email,))
                conn.commit()
            finally:
                conn.close()

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
            result = self.grader.save_uploaded_file(f)

            if isinstance(result, tuple):
                payload, status_code = result
                return jsonify(payload), status_code

            return jsonify(result)
        
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

                # Parse solution image paths before formatting
                raw_image_paths_json = row_dict.get("solution_image_paths_json")
                try:
                    solution_image_paths = json.loads(raw_image_paths_json) if raw_image_paths_json else []
                except (json.JSONDecodeError, TypeError):
                    solution_image_paths = []
                
                # Format the row using grader's formatting rules
                formatted_row = self.grader.format_db_entry(row_dict)
                
                return render_template(
                    "admin_submission_detail.html",
                    row=formatted_row,
                    sub_id=sub_id,
                    solution_image_paths=solution_image_paths,
                )
                
            except Exception as e:
                return {"error": f"Error loading submission: {str(e)}"}, 500

        @app.route("/admin/soln_images/<path:filename>")
        @self.require_admin
        def serve_soln_image(filename):
            """
            Serve a student solution image stored in storage_path/soln_images/.
            Only plain filenames are accepted; path separators are rejected.
            """
            import posixpath
            # Reject any attempt to traverse directories
            if posixpath.sep in filename or (os.sep != posixpath.sep and os.sep in filename):
                return {"error": "Invalid filename"}, 400
            images_dir = self.grader.get_soln_images_path()
            return send_from_directory(images_dir, filename)

        app.register_blueprint(bp)
