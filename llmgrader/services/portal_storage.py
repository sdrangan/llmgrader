"""Portal-wide storage: the database, admin preferences and student images.

Everything in here is global to a deployed portal rather than to a course.
It lived on :class:`~llmgrader.services.grader.Grader` until the split for
multi-course support (``plans/multicourse.md``, phase 1): a ``Grader`` owns one
course's content -- its units, its solution package, its scratch directory and
the grading path -- while a single :class:`PortalStorage` owns the one SQLite
file, the one ``admin-config.json`` and the one ``soln_images/`` tree that all
courses share.

Nothing here knows about courses, and that is the point.  When a second course
is added (phase 2) the registry hands every ``Grader`` the *same*
``PortalStorage``, so the database is opened and migrated once instead of once
per course.

``Grader`` still exposes thin delegating shims for every public name below --
see the "compatibility shims" block in ``grader.py``.  Call sites outside that
file still reach through the grader; moving them onto the storage object
directly is a later commit.
"""

import os
import sqlite3
import textwrap
from datetime import datetime

from markupsafe import Markup


class PortalStorage:
    """The global, course-independent half of the old ``Grader``.

    Constructing one resolves the storage root, creates the submissions table
    if it is missing and applies the add-a-column migrations, exactly as
    ``Grader.__init__`` used to.  It is cheap and idempotent, but it is meant to
    be constructed once per process and shared.
    """

    # Database schema definition for submissions table
    DB_SCHEMA = {
        "timestamp": "TEXT NOT NULL",
        "client_id": "TEXT",
        "unit_name": "TEXT",
        "qtag": "TEXT",
        "part_label": "TEXT",
        "required": "INTEGER",
        "partial_credit": "INTEGER",
        "question_text": "TEXT",
        "ref_soln": "TEXT",
        "grading_notes": "TEXT",
        "student_soln": "TEXT",
        "model": "TEXT",
        "timeout": "REAL",
        "latency_ms": "INTEGER",
        "timed_out": "INTEGER",
        "tokens_in": "INTEGER",
        "tokens_out": "INTEGER",
        "used_admin_key" : "INTEGER",
        "raw_prompt": "TEXT",
        "result": "TEXT",
        "full_explanation": "TEXT",
        "feedback": "TEXT",
        "point_parts_json": "TEXT",
        "max_point_parts_json": "TEXT",
        "points": "REAL",
        "max_points": "REAL",
        "result_parts_json": "TEXT",
        "tools_json": "TEXT",
        "solution_image_paths_json": "TEXT",
    }

    # Formats for displaying DB fields.
    # Fields not listed here default to "wrap" format,
    # meaning they will be wrapped in the UI.
    FIELD_FORMAT = {
        "timestamp": "short_datetime",
        "question_text": "html",
        "ref_soln": "html",
        "unit_name": "text",
        "qtag": "text",
        "required": "bool",
        "partial_credit": "bool",
        "model": "text",
        "timeout": "text",
        "latency_ms": "text",
        "timed_out": "text",
        "tokens_in": "text",
        "tokens_out": "text",
        "tools_json": "text",
        "client_id": "text",
    }

    def __init__(self):
        # Get the database path
        self.db_path = self.get_db_path()

        # Initialize field format
        PortalStorage.initialize_field_format()

        # Initialize the database first, then apply any missing-column migrations.
        # init_db uses CREATE TABLE IF NOT EXISTS, so it is safe on both new and
        # existing databases. temp_modify_db must run after so it can find the
        # table when the DB is brand-new.
        self.init_db()
        self.temp_modify_db()

    # ------------------------------------------------------------------
    # Storage paths
    # ------------------------------------------------------------------

    def get_storage_path(self) -> str:
        """
        Returns the root storage directory.
        On Render: uses LLMGRADER_STORAGE_PATH (e.g., /var/data)
        Locally: falls back to ./local_data

        The environment variable is read on every call, not cached at
        construction: the test suites redirect LLMGRADER_STORAGE_PATH to a temp
        tree per test and rely on that.
        """
        root = os.environ.get("LLMGRADER_STORAGE_PATH")
        if root:
            storage_path = root
        else:
            storage_path = os.path.join(os.getcwd(), "local_data")
            os.makedirs(storage_path, exist_ok=True)

        return storage_path

    def get_db_path(self) -> str:
        """
        Returns the full path to the SQLite database file.

        """
        storage = self.get_storage_path()
        db_dir = os.path.join(storage, "db")
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, "llmgrader.db")
        print("Using database path:", db_path)
        return db_path

    def get_admin_pref_path(self) -> str:
        """
        Returns the full path to the admin preferences JSON file.
        """
        storage = self.get_storage_path()
        pref_dir = os.path.join(storage, "pref")
        os.makedirs(pref_dir, exist_ok=True)
        admin_pref_path = os.path.join(pref_dir, "admin-config.json")
        return admin_pref_path

    def get_soln_images_path(self) -> str:
        """
        Returns the full path to the directory where student solution images are stored.
        Creates the directory if it does not exist.
        """
        storage = self.get_storage_path()
        images_dir = os.path.join(storage, "soln_images")
        os.makedirs(images_dir, exist_ok=True)
        return images_dir

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def temp_modify_db(self):
        """
        Modify the database schema to add new JSON columns for points and max_points
        if they do not already exist. This supports older databases without requiring
        users to run a migration script. Safe to remove once all users have updated.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get existing columns
        cursor.execute("PRAGMA table_info(submissions);")
        columns = [row[1] for row in cursor.fetchall()]

        new_columns = {
            "required": "INTEGER",
            "partial_credit": "INTEGER",
            "max_point_parts_json": "TEXT",
            "point_parts_json": "TEXT",
            "result_parts_json": "TEXT",
            "tools_json": "TEXT",
            "solution_image_paths_json": "TEXT",
            "points": "REAL",
            "max_points": "REAL",
            "client_id": "TEXT",
        }

        # Add each column if missing
        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                cursor.execute(
                    f"ALTER TABLE submissions ADD COLUMN {col_name} {col_type} DEFAULT NULL;"
                )
                conn.commit()

        # Privacy scrub: erase any stored user emails from older schema
        if "user_email" in columns:
            cursor.execute("UPDATE submissions SET user_email = NULL WHERE user_email IS NOT NULL;")
            conn.commit()

        conn.close()

    def init_db(self):
        """
        Initialize the SQLite database for storing submission data.
        Creates the submissions table if it does not already exist.

        The schema is defined by the DB_SCHEMA class attribute, ensuring
        a single canonical definition of the database structure.

        This function is idempotent and safe to call multiple times.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Build column definitions from DB_SCHEMA
        column_defs = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for col_name, col_type in self.DB_SCHEMA.items():
            column_defs.append(f"{col_name} {col_type}")

        # Construct the CREATE TABLE statement
        columns_sql = ",\n                ".join(column_defs)
        create_table_sql = f'''
            CREATE TABLE IF NOT EXISTS submissions (
                {columns_sql}
            )
        '''

        cursor.execute(create_table_sql)
        conn.commit()
        conn.close()

    def insert_submission(self, **kwargs):
        """
        Insert a submission record into the SQLite database.

        This method is schema-driven: it dynamically reads column names from
        the DB_SCHEMA class attribute, making it future-proof against schema changes.

        Parameters
        ----------
        **kwargs : dict
            Keyword arguments matching column names in DB_SCHEMA.
            Any columns not provided will default to None.
            Extra keywords not in DB_SCHEMA are silently ignored.

        Examples
        --------
        storage.insert_submission(
            timestamp="2026-01-28 12:34:56",
            client_id="a1b2c3d4",
            unit_name="unit1",
            qtag="basic_logic",
            student_soln="My answer...",
            model="gpt-5.6-luna"
        )
        """
        # Build record dictionary from DB_SCHEMA columns
        record = {}
        for col_name in self.DB_SCHEMA.keys():
            record[col_name] = kwargs.get(col_name)

        # Construct dynamic INSERT statement
        columns = ", ".join(self.DB_SCHEMA.keys())
        placeholders = ", ".join(f":{col}" for col in self.DB_SCHEMA.keys())

        insert_sql = f'''
            INSERT INTO submissions ({columns})
            VALUES ({placeholders})
        '''

        # Execute the insert
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(insert_sql, record)
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Display formatting for the submission detail view
    # ------------------------------------------------------------------

    def _apply_format(self, fmt: str, value):
        """
        Apply a formatting rule to a field value.

        Parameters
        ----------
        fmt: str
            The format type: "short_datetime", "html", "wrap80", "bool", or "text"
        value:
            The value to format

        Returns
        -------
        Formatted value
        """
        if value is None:
            return ""

        if fmt == "short_datetime":
            try:
                return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")
            except (ValueError, AttributeError):
                return str(value)
        elif fmt == "bool":
            normalized = str(value).strip().lower()
            if normalized in {"1", "true"}:
                return "true"
            if normalized in {"0", "false"}:
                return "false"
            return str(value)
        elif fmt == "html":
            return Markup(str(value))
        elif fmt == "wrap80":
            # Wrap text to 80 characters, preserving existing line breaks
            lines = str(value).splitlines()
            wrapped_lines = []
            for line in lines:
                if len(line) <= 80:
                    wrapped_lines.append(line)
                else:
                    wrapped_lines.extend(textwrap.wrap(line, width=80, break_long_words=False, break_on_hyphens=False))
            return "\n".join(wrapped_lines)
        else:  # "text" or default
            return str(value)

    def format_db_entry(self, row: dict) -> dict:
        """
        Format a database row for display in the submission detail view.

        Parameters
        ----------
        row: dict
            Dictionary containing submission data (column_name: value)

        Returns
        -------
        dict
            New dictionary with formatted values according to FIELD_FORMAT rules
        """
        formatted = {}
        for key, value in row.items():
            # Get format rule, default to "wrap80"
            fmt = self.FIELD_FORMAT.get(key, "wrap80")
            formatted[key] = self._apply_format(fmt, value)
        return formatted

    @staticmethod
    def initialize_field_format():
        # 1. Validate FIELD_FORMAT keys are real DB fields
        unknown = set(PortalStorage.FIELD_FORMAT.keys()) - set(PortalStorage.DB_SCHEMA.keys())
        if unknown:
            raise ValueError(f"FIELD_FORMAT contains unknown fields: {unknown}")

        # 2. Add missing DB fields with default formatting
        for field in PortalStorage.DB_SCHEMA.keys():
            if field not in PortalStorage.FIELD_FORMAT:
                PortalStorage.FIELD_FORMAT[field] = "wrap80"

        # 3. Optional: warn about fields that defaulted
        # (Useful during development, can remove later)
        # print("FIELD_FORMAT auto-filled defaults for:",
        #       [f for f in DB_SCHEMA.keys() if FIELD_FORMAT[f] == "wrap80"])
