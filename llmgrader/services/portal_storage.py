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

The one place a course *id* appears here is
:meth:`PortalStorage.backfill_course_id`, and it appears as an argument.  This
module must not import :mod:`llmgrader.services.course_registry`: the registry
knows which courses exist and which is the default, and it calls down with the
id it has decided on.  Importing upwards would also be a cycle, since the
registry constructs a ``PortalStorage``.
"""

import os
import sqlite3
import textwrap
from datetime import datetime, timezone

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
        # Which course this submission was graded against.  Nullable on
        # purpose: a Grader built without a course -- llmgrader_test, the
        # replay tool -- writes NULL rather than guessing, and rows that
        # predate the column are stamped once by backfill_course_id.
        "course_id": "TEXT",
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

    # Name recorded in portal_migrations once the course_id backfill has run.
    MIGRATION_COURSE_ID_BACKFILL = "course_id_backfill"

    # Formats for displaying DB fields.
    # Fields not listed here default to "wrap" format,
    # meaning they will be wrapped in the UI.
    FIELD_FORMAT = {
        "timestamp": "short_datetime",
        "question_text": "html",
        "ref_soln": "html",
        "course_id": "text",
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
            "course_id": "TEXT",
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

        # Every course-scoped read filters on course_id, so index it.  This
        # runs after the loop above, which is what guarantees the column
        # exists on a database that predates it.
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_submissions_course ON submissions(course_id);"
        )
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

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'submissions'"
        )
        table_existed = cursor.fetchone() is not None

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

        if not table_existed:
            # A table built from DB_SCHEMA has course_id from the outset, so no
            # row in it can predate the column and there is nothing to backfill
            # -- ever.  Recording that here, at creation, is what keeps a
            # deliberately course-less row (llmgrader_test, the replay tool)
            # safe from the *first* registry boot as well as every later one.
            # The backfill exists for databases that predate the column; this
            # one does not.
            self._ensure_migrations_table(cursor)
            cursor.execute(
                "INSERT OR IGNORE INTO portal_migrations (name, applied_at, detail) "
                "VALUES (?, ?, ?)",
                (
                    self.MIGRATION_COURSE_ID_BACKFILL,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "new database; no rows predate course_id",
                ),
            )

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
    # One-shot data migrations
    # ------------------------------------------------------------------

    def _ensure_migrations_table(self, cursor) -> None:
        """Create the ledger of data migrations already applied to this file.

        Schema changes are idempotent by shape -- ``CREATE TABLE IF NOT
        EXISTS``, ``ALTER TABLE`` guarded by ``PRAGMA table_info`` -- but a
        data migration is not.  "Stamp every NULL course_id with the default
        course" is right exactly once, on the boot that introduces the column;
        run again later it would capture rows that are deliberately NULL.  So
        this file records which ones have run.
        """
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS portal_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                detail TEXT
            )
            """
        )

    def migration_applied(self, name: str) -> bool:
        """Whether the one-shot migration *name* has already run on this database."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            self._ensure_migrations_table(cursor)
            conn.commit()
            cursor.execute("SELECT 1 FROM portal_migrations WHERE name = ?", (name,))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def backfill_course_id(self, course_id: str) -> int:
        """Stamp *course_id* onto submission rows that predate the column.

        Rows written before ``submissions.course_id`` existed all belong to the
        one course the portal was deployed with, so the caller -- the course
        registry, once it knows its default -- passes that id down here.  This
        module deliberately has no way to work the id out for itself; see the
        module docstring.

        Runs **at most once per database, ever**, recorded in
        ``portal_migrations``.  That is stronger than ``WHERE course_id IS
        NULL`` alone, and the difference matters: a Grader constructed without
        a course writes NULL on purpose (``llmgrader_test``, the replay tool),
        and a backfill on some later boot must not adopt those rows into a
        course they were never graded against.

        The check, the UPDATE and the marker are one ``BEGIN IMMEDIATE``
        transaction.  That makes it safe for two gunicorn workers booting at
        once: the second blocks at ``BEGIN`` rather than reading a stale "not
        applied yet", and then finds the marker and does nothing.  It also
        means a crash part-way leaves the migration neither applied nor marked,
        so the next boot retries it.

        Returns the number of rows stamped (0 when it has already run, or when
        there was nothing to stamp).
        """
        if not course_id:
            # No default course to attribute rows to.  Leave the marker unset
            # so a later boot that does have one still gets its chance.
            return 0

        conn = sqlite3.connect(self.db_path)
        # Explicit transaction control: the default isolation level would
        # commit the DDL below out from under us and start the read outside
        # the write lock, which is exactly the race this avoids.
        conn.isolation_level = None
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            try:
                self._ensure_migrations_table(cursor)

                cursor.execute(
                    "SELECT 1 FROM portal_migrations WHERE name = ?",
                    (self.MIGRATION_COURSE_ID_BACKFILL,),
                )
                if cursor.fetchone() is not None:
                    cursor.execute("COMMIT")
                    return 0

                cursor.execute(
                    "UPDATE submissions SET course_id = ? WHERE course_id IS NULL",
                    (course_id,),
                )
                updated = cursor.rowcount or 0
                cursor.execute(
                    "INSERT INTO portal_migrations (name, applied_at, detail) "
                    "VALUES (?, ?, ?)",
                    (
                        self.MIGRATION_COURSE_ID_BACKFILL,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        f"{updated} row(s) stamped with course_id={course_id!r}",
                    ),
                )
                cursor.execute("COMMIT")
            except Exception:
                cursor.execute("ROLLBACK")
                raise
        finally:
            conn.close()

        if updated:
            print(
                f"[PortalStorage] Backfilled course_id={course_id!r} onto "
                f"{updated} submission row(s) that predate the column."
            )
        return updated

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
