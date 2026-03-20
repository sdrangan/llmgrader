import textwrap
import os
import shutil
from pathlib import Path
import json
import os
from urllib import response
import pandas as pd
from openai import OpenAI, APITimeoutError
import zipfile
import re
import sqlite3
import time
from datetime import datetime
from concurrent.futures import TimeoutError as ThreadTimeoutError
from openai import APITimeoutError

from concurrent.futures import ThreadPoolExecutor

from typing import Union, Literal
from llmgrader.services.parselatex import parse_latex_soln
import sys
from markupsafe import Markup
from pydantic import ValidationError, ConfigDict, model_validator


import sys
from datetime import datetime, timezone
from llmgrader.services.prompt import PromptBuilder
from llmgrader.services.unit_parser import UnitParser

def _ts():
    # timezone-aware UTC timestamp with millisecond precision
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"

def log_error(msg: str):
    print(f"[{_ts()}] ERROR: {msg}", file=sys.stderr, flush=True)

def log_std(msg: str):
    print(f"[{_ts()}] INFO: {msg}", file=sys.stdout, flush=True)



from pydantic import BaseModel




class GradeResult(BaseModel):
    """
    Data model for the grading result.

    max_point_parts: float | list[float] | None
        - If the question has multiple parts and we are grading all parts (part_label == "all"), this will be a list of maximum points for each part, in the same order as part_labels
        - If the question has multiple parts but we are grading a specific part, this will be the maximum points for that part.
        - If the question has only one part, this will be the maximum points for that part.
        - This field is returned even if partial_credit is False, since the maximum points may still be relevant for grading and feedback.
        - The field is computed pre-grader
    point_parts: float | list[float] | None
        If partial_credit is True, this field contains the points awarded for each part of the question with an identical structure as `max_point_parts`.  In the multi-part case when part_label == "all", 
        the points for each part are returned by the grader.  In the case of grading a specific part or a single-part question, the grader returns `points` and that value is copied to `point_parts`
        post-grader for consistency.
        If partial_credit is False, the values are derived post-grader from `result_parts` with 0 points for "fail", "error", or "partial" and max_points for "pass".
    result_parts: Literal["pass", "fail", "error", "partial"] | list[Literal["pass", "fail", "error", "partial"]]
        - If partial_credit is False, this field has the same format as `max_point_parts`.  Specifically, if the question has multiple parts and part_label == "all", 
        this field is a list of results for each part of the question, in the same order as part_labels. In this case, the grader populates each result with "pass", "fail", or "error".
        The "partial" value is not used. If the question has multiple parts but we are grading a specific or the question has a single part, the field is a single value of "pass", "fail", or "error".
        The value will be copied post-grader from `result` to `result_parts` for consistency.
        - If partial_credit is True, the field is populated post-grading by the backend with values in points with 'pass' indicating full points, 'partial' indicating some points between 1 and max_points, 
        and 'fail' indicating 0 points.  The grader should not return the "partial" value in this case, since the backend will determine it based on the points awarded.
    result : Literal["pass", "fail", "error", "partial"]
        - If partial_credit is False and grading a specific part or single-part question, the field is filled by the grader and then copied to `result_parts` for consistency.  
        The grader should return "pass", "fail", or "error" in this case, but not "partial". 
        - In all other cases, the field is derived post-grader by the backend as follows:   If any(result_parts == 'error'), the result is "error".  
        Else if all(result_parts == 'pass') , the result is "pass", else if all(results_parts=='fail'), result = "fail", else result='partial'.  . 
    points : float | None
        When partial_credit==True and  grading a specific part or single-part question, the grader returns the points awarded for that part.  
        This value is copied post-grader to the appropriate position in `point_parts` for consistency.
        In all other cases, the value is derived post-grader by summing the point_parts.
class RubricEvalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: str
    point_awarded: float | None = None
    result: Literal["pass", "fail", "feedback", "n/a"] | None = None

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.point_awarded is None and self.result is None:
            raise ValueError("rubric_eval items must include point_awarded or result.")
        return self


    max_points : float | None
        The total maximum points for the question, i.e., sum(max_point_parts)
        The grader does not need to return this field since the backend will compute it.
    rubric_eval : dict[str, dict] | None
    model_config = ConfigDict(extra="forbid")

        For each rubric item id, the grader returns a dictionary for the assessment of 
        each rubric item with the following fields:
        rubric_eval[id]['evidence'] : str`
            A concise description of the evidence observed in the student's solution as to why or why not
            the condition of the rubric has been met.  
        rubric_eval[id]['point_awarded'] : float
    rubric_eval: dict[str, RubricEvalItem] | None = None
            the point_adjustment specified for the rubric item in the XML.  If the condition is not met,
            the point_awarded should be 0.  This fields is filled out only for partial_credit
            grading.
        rubric_eval[id]['result'] : "pass" | "fail" | "feedback" | "n/a"
            The final recommended result in the case of binary grading.  
            - 'fail' indicates that the rubric  
    """
    max_point_parts: float | list[float] | None
    point_parts: float | list[float] | None
    result_parts: Literal["pass", "fail", "error", "partial"] | list[Literal["pass", "fail", "error", "partial"]]
    result: Literal["pass", "fail", "error", "partial"]
    full_explanation: str
    feedback: str
    points: float | None = None
    max_points: float | None
    rubric_eval: dict[str, dict] | None = None



class GraderRawResult(BaseModel):
    """
    Raw fields that the LLM grader may return before backend post-processing.
    """
    point_parts: list[float] | None = None
    result_parts: list[Literal["pass", "fail", "error"]] | None = None
    result: Union[Literal["pass", "fail", "error"], float, None] = None
    full_explanation: str
    feedback: str
    points: float | None = None
    rubric_eval: dict[str, dict] | None = None

def summarize_tool_calls(response) -> str:
    """
    Summarize tool activity from an OpenAI Responses API object.
    """
    def get_value(obj, key, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    summary = []

    for item in get_value(response, "output", []) or []:
        item_type = get_value(item, "type")

        if item_type == "reasoning":
            summary.append("- reasoning")
            continue

        if item_type == "web_search_call":
            action = get_value(item, "action", {})
            action_type = get_value(action, "type")

            if action_type == "search":
                query = get_value(action, "query")
                if query:
                    summary.append(f"- web_search: {query}")
                else:
                    summary.append("- web_search")
            elif action_type == "open_page":
                url = get_value(action, "url")
                if url:
                    summary.append(f"- open_page: {url}")
                else:
                    summary.append("- open_page")
            else:
                summary.append("- web_search_call")
            continue

        if item_type == "message":
            summary.append("- message (final answer)")

    return "\n".join(summary)


def normalize_json_response_text(text: str) -> str:
    """
    Normalize model output so JSON parsing can tolerate fenced or wrapped content.
    """
    normalized = (text or "").strip()
    if not normalized:
        return normalized

    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s*```$", "", normalized).strip()

    start = normalized.find("{")
    end = normalized.rfind("}")
    if start != -1 and end != -1 and end >= start:
        return normalized[start:end + 1]

    return normalized


class Grader:
    SUPPORTED_TOOLS = ["web_search"]

    # Database schema definition for submissions table
    DB_SCHEMA = {
        "timestamp": "TEXT NOT NULL",
        "client_id": "TEXT",
        "user_email": "TEXT",
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
    }

    # Field formatting rules for submission detail view
    FIELD_FORMAT = {
        "timestamp": "short_datetime",
        "question_text": "html",
        "ref_soln": "html",
        "grading_notes": "html",
        "student_soln": "wrap80",
        "raw_prompt": "wrap80",
        "full_explanation": "wrap80",
        "feedback": "wrap80",
        "result": "text",
        "model": "text",
        "unit_name": "text",
        "qtag": "text",
        "part_label": "text",
        "timeout": "text",
        "latency_ms": "text",
        "timed_out": "text",
        "tokens_in": "text",
        "tokens_out": "text",
        "client_id": "text",
        "user_email": "text",
        "point_parts_json": "text",
        "max_point_parts_json": "text",
        "points": "text",
        "max_points": "text",
        "result_parts_json": "text",
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
    }

    
    def __init__(self, 
                 scratch_dir : str ="scratch",
                 soln_pkg : str | None = None
                 ):
        """
        Main Grader service class.

        Parameters
        ----------
        scratch_dir: str
            Path to the scratch directory for temporary files.
        soln_pkg: str | None
            Path to a solution package (if testing locally).
        """
        self.scratch_dir = scratch_dir
        self.soln_pkg = soln_pkg

        # Get the database path
        self.db_path = self.get_db_path()

        # Initialize field format
        Grader.initialize_field_format()

         # Temporary database modification to add 'used_admin_key' column if it doesn't exist
        self.temp_modify_db()
        
        # Initialize the database
        self.init_db()

        # Initialize units dictionary
        self.units = {}
        self.units_order = []
        self.units_list = []
        self.xml_path_list = []
        self.unit_validation_errors = []
        self.unit_validation_alert = None
        self.prompt_builder = PromptBuilder()

        # Remove old scratch directory if it exists
        if os.path.exists(self.scratch_dir):
            shutil.rmtree(self.scratch_dir)

        # Recreate it fresh
        os.makedirs(self.scratch_dir, exist_ok=True)

        # Load units from the solution package
        self.load_unit_pkg() 

       
    def temp_modify_db(self):
        """
        Modify the database schema to add new JSON columns for points and max_points
        if they do not already exist. This supports older databases without requiring
        users to run a migration script. Safe to remove once all users have updated.
        """
        import sqlite3
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
            "points": "REAL",
            "max_points": "REAL",
        }

        # Add each column if missing
        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                cursor.execute(
                    f"ALTER TABLE submissions ADD COLUMN {col_name} {col_type} DEFAULT NULL;"
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
        grader.insert_submission(
            timestamp="2026-01-28 12:34:56",
            user_email="student@example.com",
            unit_name="unit1",
            qtag="basic_logic",
            student_soln="My answer...",
            model="gpt-4.1-mini"
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


    def save_uploaded_file(self, file_storage):
        """
        Save an uploaded solution package ZIP, extract it into self.soln_pkg,
        and reload units.
        """

        # ---------------------------------------------------------
        # 1. Save uploaded ZIP into scratch
        # ---------------------------------------------------------
        save_path = os.path.join(self.scratch_dir, file_storage.filename)
        file_storage.save(save_path)
        print(f"[Upload] Saved uploaded file to {save_path}")

        # ---------------------------------------------------------
        # 2. Resolve solution package directory
        # ---------------------------------------------------------
        soln_pkg_path = self.soln_pkg
        if soln_pkg_path is None:
            return {"error": "Internal error: soln_pkg_path not set"}, 500

        print(f"[Upload] Using solution package path: {soln_pkg_path}")

        # ---------------------------------------------------------
        # 3. Clear existing package directory
        # ---------------------------------------------------------
        def remove_readonly(func, path, excinfo):
            os.chmod(path, 0o666)
            func(path)

        shutil.rmtree(soln_pkg_path, onexc=remove_readonly)
        os.makedirs(soln_pkg_path, exist_ok=True)

        # ---------------------------------------------------------
        # 4. Extract ZIP into soln_pkg_path
        # ---------------------------------------------------------
        try:
            with zipfile.ZipFile(save_path, "r") as z:
                z.extractall(soln_pkg_path)
            print(f"[Upload] Extracted ZIP into {soln_pkg_path}")
        except zipfile.BadZipFile:
            print("[Upload] Invalid ZIP file")
            return {"error": "Uploaded file is not a valid zip file."}, 400
        except Exception as e:
            print(f"[Upload] Unexpected error while extracting ZIP: {e}")
            return {"error": "Failed to extract ZIP file."}, 500

        # ---------------------------------------------------------
        # 5. Reload units from the extracted package
        # ---------------------------------------------------------
        try:
            self.load_unit_pkg()
            print("[Upload] Unit package loaded successfully")
        except Exception as e:
            print(f"[Upload] Failed to load unit package: {e}")
            return {"error": f"Failed to load units: {e}"}, 400

        # ---------------------------------------------------------
        # 6. Verify units loaded
        # ---------------------------------------------------------
        if not self.units:
            print("[Upload] No units found after loading")
            error_message = self.unit_validation_alert or "No valid units found. Check llmgrader_config.xml."
            return {"error": error_message}, 400

        print(f"[Upload] Loaded {len(self.units)} unit(s): {list(self.units.keys())}")

        return {
            "status": "ok",
            "validation_alert": self.unit_validation_alert,
        }

    def load_unit_pkg(self):
        parser = UnitParser(
            scratch_dir=self.scratch_dir,
            soln_pkg=self.soln_pkg,
            supported_tools=self.SUPPORTED_TOOLS,
        )
        unit_package = parser.parse()

        if unit_package is None:
            # Defensive: treat as empty package
            self.soln_pkg = self.soln_pkg or None
            self.units = {}
            self.units_order = []
            self.units_list = []
            self.xml_path_list = []
            self.unit_validation_errors = ["Unit package could not be loaded (None returned)"]
            self.unit_validation_alert = "Unit package could not be loaded."
            return

        self.soln_pkg = unit_package.soln_pkg_path
        self.units = unit_package.units
        self.units_order = unit_package.units_order
        self.units_list = unit_package.units_list
        self.xml_path_list = unit_package.xml_path_list
        self.unit_validation_errors = unit_package.validation_errors
        self.unit_validation_alert = unit_package.validation_alert
    
    def build_task_prompt(
        self,
        question_dict: dict,
        student_soln : str,
        part_label: str = "all",
    ) -> tuple[str, int | list[int] | None]:
        """
        Build the grading prompt sent to the language model.

        Parameters
        ----------
        question_dict: dict
            The question configuration dictionary loaded from the unit package.
        student_soln: str
            The student's submitted solution text.
        part_label: str
            The specific part being graded, or "all" for whole-question grading.

        Returns
        -------
        prompt : str
            The full prompt text to send to the grading model.
        max_points_part : float | list[float]
            If the input `max_points` is None, returns None.
            If part_label == 'all', returns max_points and the question has multiple parts, returns 
            max_points, the list with points for all parts
            If part_label is a specific part or the question has a single part, returns
            the maximum points for that part.  Note that this field is returned even if partial_credit is False,
            since the maximum points may still be relevant for grading and feedback.
        """
        return self.prompt_builder.build_task_prompt(question_dict, student_soln, part_label)

    def grade_post_process(
        self,
        raw_grade: dict,
        partial_credit: bool,
        max_points_part: int | list[int] | None,
        part_labels: list[str] | None = None,
        part_label: str = "all",
        rubrics: dict[str, dict] | None = None,
        rubric_total: str | None = None,
        tools: list[str] | None = None,
        tool_call_summary: str | None = None,
    ) -> GradeResult:
        """
        Fill in derived GradeResult fields that are not returned directly by the grader.
        """
        full_explanation = str(raw_grade.get("full_explanation", ""))
        feedback = str(raw_grade.get("feedback", ""))
        rubric_eval = raw_grade.get("rubric_eval")

        def total_max_points(value):
            if isinstance(value, list):
                return float(sum(value))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            return None

        def classify_points(points_value, max_value):
            if max_value is None or points_value is None:
                return "error"
            if points_value >= float(max_value):
                return "pass"
            if points_value > 0:
                return "partial"
            return "fail"

        def aggregate_result(result_parts_value):
            if isinstance(result_parts_value, list):
                if any(part_result == "error" for part_result in result_parts_value):
                    return "error"
                if all(part_result == "pass" for part_result in result_parts_value):
                    return "pass"
                if all(part_result == "fail" for part_result in result_parts_value):
                    return "fail"
                return "partial"
            if result_parts_value == "error":
                return "error"
            if result_parts_value == "pass":
                return "pass"
            if result_parts_value == "fail":
                return "fail"
            return "partial"

        def append_result_table(
            text: str,
            point_parts_value,
            max_point_parts_value,
            result_parts_value,
        ) -> str:
            if isinstance(max_point_parts_value, list):
                row_labels = part_labels if part_labels and len(part_labels) == len(max_point_parts_value) else [str(index + 1) for index in range(len(max_point_parts_value))]
                row_points = point_parts_value if isinstance(point_parts_value, list) else [point_parts_value] * len(max_point_parts_value)
                row_results = result_parts_value if isinstance(result_parts_value, list) else [result_parts_value] * len(max_point_parts_value)
                row_max_points = max_point_parts_value
            else:
                row_labels = [part_label]
                row_points = [point_parts_value]
                row_results = [result_parts_value]
                row_max_points = [max_point_parts_value]

            table_lines = [
                "",
                "| Part | points | max_points | result |",
                "| --- | --- | --- | --- |",
            ]
            for row_label, row_point, row_max_point, row_result in zip(row_labels, row_points, row_max_points, row_results):
                table_lines.append(f"| {row_label} | {row_point} | {row_max_point} | {row_result} |")

            if text:
                return text + "\n" + "\n".join(table_lines)
            return "\n".join(table_lines).lstrip("\n")

        def append_tool_summary(explanation: str, tool_names: list[str] | None, summary: str | None) -> str:
            tool_names = tool_names or []
            tools_line = f"Tools: {', '.join(tool_names)}" if tool_names else "Tools: None"

            if summary:
                summary_block = f"{tools_line}\nTool Summary:\n{summary}"
            else:
                summary_block = tools_line

            if explanation:
                return explanation + "\n\n" + summary_block
            return summary_block

        def append_rubric_feedback(
            feedback_text: str,
            rubric_eval_value,
            rubric_definitions: dict[str, dict] | None,
        ) -> str:
            if not isinstance(rubric_eval_value, dict) or not rubric_eval_value:
                return feedback_text

            def table_cell(value) -> str:
                text = str(value if value is not None else "")
                text = " ".join(text.splitlines())
                return text.replace("|", "\\|").strip()

            rubric_definitions = rubric_definitions or {}
            uses_points = any(
                isinstance(
                    entry.model_dump() if hasattr(entry, "model_dump") else entry,
                    dict,
                )
                and (
                    (entry.model_dump() if hasattr(entry, "model_dump") else entry).get("point_awarded")
                    is not None
                )
                for entry in rubric_eval_value.values()
            )
            value_header = "Points" if uses_points else "Outcome"
            rubric_lines = [
                "",
                "Rubric evaluation:",
                f"| Criteria | {value_header} | Evaluation |",
                "| --- | --- | --- |",
            ]

            for rubric_id, rubric_entry in rubric_eval_value.items():
                if hasattr(rubric_entry, "model_dump"):
                    rubric_entry = rubric_entry.model_dump()
                if not isinstance(rubric_entry, dict):
                    continue

                rubric_meta = rubric_definitions.get(rubric_id, {})
                part = rubric_meta.get("part", "all")
                display_text = rubric_meta.get("display_text", rubric_id)
                point_adjustment = rubric_meta.get("point_adjustment")
                point_awarded = rubric_entry.get("point_awarded")
                rubric_result = rubric_entry.get("result")
                evidence = str(rubric_entry.get("evidence", "")).strip()

                criteria_text = display_text if part == "all" else f"Part {part}: {display_text}"

                if point_awarded is not None:
                    points_text = f"{point_awarded} / {point_adjustment}"
                else:
                    points_text = str(rubric_result or "")
                rubric_lines.append(
                    "| "
                    + table_cell(criteria_text)
                    + " | "
                    + table_cell(points_text)
                    + " | "
                    + table_cell(evidence or "None")
                    + " |"
                )

            if len(rubric_lines) == 4:
                return feedback_text

            appendix = "\n".join(rubric_lines)
            if feedback_text:
                return feedback_text + "\n\n" + appendix.lstrip("\n")
            return appendix.lstrip("\n")

        def invalid_grade(message: str) -> GradeResult:
            explanation = full_explanation
            if explanation:
                explanation += f"\n\n{message}"
            else:
                explanation = message

            if isinstance(max_points_part, list):
                result_parts_value = ["error"] * len(max_points_part)
            else:
                result_parts_value = "error"

            return GradeResult(
                max_point_parts=max_points_part,
                point_parts=None,
                result_parts=result_parts_value,
                result="error",
                full_explanation=explanation,
                feedback=append_rubric_feedback(feedback, rubric_eval, rubrics),
                points=None,
                max_points=total_max_points(max_points_part),
                rubric_eval=rubric_eval,
            )

        max_points_total = total_max_points(max_points_part)

        def rubric_points_total(rubric_eval_value, max_value: float | None, mode: str | None) -> float | None:
            if not isinstance(rubric_eval_value, dict) or not rubric_eval_value:
                return None
            if mode == "flexible":
                return None

            total = 0.0
            saw_numeric_award = False
            for rubric_entry in rubric_eval_value.values():
                if hasattr(rubric_entry, "model_dump"):
                    rubric_entry = rubric_entry.model_dump()
                if not isinstance(rubric_entry, dict):
                    continue

                point_awarded = rubric_entry.get("point_awarded")
                if point_awarded is None:
                    continue
                if not isinstance(point_awarded, (int, float)) or isinstance(point_awarded, bool):
                    return None

                total += float(point_awarded)
                saw_numeric_award = True

            if not saw_numeric_award:
                return None

            if mode == "sum_negative" and max_value is not None:
                total = float(max_value) + total

            if max_value is None:
                return total
            return max(0.0, min(float(max_value), total))

        def rubric_point_parts_total(
            rubric_eval_value,
            rubrics_value: dict[str, dict] | None,
            labels: list[str] | None,
            max_values: list[float] | None,
            mode: str | None,
        ) -> list[float] | None:
            if mode == "flexible":
                return None
            if not isinstance(rubric_eval_value, dict) or not rubric_eval_value:
                return None
            if not isinstance(rubrics_value, dict) or not rubrics_value:
                return None
            if not labels or not max_values or len(labels) != len(max_values):
                return None

            if mode == "sum_negative":
                point_parts_total = [float(value) for value in max_values]
            else:
                point_parts_total = [0.0 for _ in max_values]

            saw_numeric_award = False
            for rubric_id, rubric_entry in rubric_eval_value.items():
                if hasattr(rubric_entry, "model_dump"):
                    rubric_entry = rubric_entry.model_dump()
                if not isinstance(rubric_entry, dict):
                    continue

                point_awarded = rubric_entry.get("point_awarded")
                if point_awarded is None:
                    continue
                if not isinstance(point_awarded, (int, float)) or isinstance(point_awarded, bool):
                    return None

                rubric_data = rubrics_value.get(rubric_id)
                if not isinstance(rubric_data, dict):
                    continue

                rubric_part = rubric_data.get("part", "all")
                if rubric_part == "all":
                    return None

                try:
                    part_index = labels.index(rubric_part)
                except ValueError:
                    return None

                point_parts_total[part_index] += float(point_awarded)
                saw_numeric_award = True

            if not saw_numeric_award:
                return None

            return [
                max(0.0, min(float(max_value), float(point_value)))
                for point_value, max_value in zip(point_parts_total, max_values)
            ]

        if partial_credit:
            if isinstance(max_points_part, list):
                point_parts = rubric_point_parts_total(
                    rubric_eval,
                    rubrics,
                    part_labels,
                    max_points_part,
                    rubric_total,
                )

                if point_parts is None:
                    raw_point_parts = raw_grade.get("point_parts")
                    if not isinstance(raw_point_parts, list) or len(raw_point_parts) != len(max_points_part):
                        return invalid_grade("Grader error: expected point_parts as a list matching the part structure.")

                    point_parts = []
                    for point_value, max_value in zip(raw_point_parts, max_points_part):
                        if not isinstance(point_value, (int, float)) or isinstance(point_value, bool):
                            return invalid_grade("Grader error: all values in point_parts must be numeric.")
                        point_value = float(point_value)
                        if point_value < 0 or point_value > float(max_value):
                            return invalid_grade("Grader error: point_parts contains a value outside the allowed range.")
                        point_parts.append(point_value)

                result_parts = [
                    classify_points(point_value, max_value)
                    for point_value, max_value in zip(point_parts, max_points_part)
                ]
                points = float(sum(point_parts))
                result = aggregate_result(result_parts)

                return GradeResult(
                    max_point_parts=max_points_part,
                    point_parts=point_parts,
                    result_parts=result_parts,
                    result=result,
                    full_explanation=append_tool_summary(
                        full_explanation,
                        tools,
                        tool_call_summary,
                    ),
                    feedback=append_rubric_feedback(
                        append_result_table(feedback, point_parts, max_points_part, result_parts),
                        rubric_eval,
                        rubrics,
                    ),
                    points=points,
                    max_points=max_points_total,
                    rubric_eval=rubric_eval,
                )

            scalar_max_points = max_points_total
            points_value = rubric_points_total(rubric_eval, scalar_max_points, rubric_total)

            if points_value is None:
                raw_points = raw_grade.get("points")
                if not isinstance(raw_points, (int, float)) or isinstance(raw_points, bool):
                    return invalid_grade("Grader error: expected numeric points for this grading mode.")
                points_value = float(raw_points)

            if scalar_max_points is not None and (points_value < 0 or points_value > scalar_max_points):
                return invalid_grade("Grader error: points is outside the allowed range.")

            result_parts = classify_points(points_value, scalar_max_points)
            result = aggregate_result(result_parts)
            return GradeResult(
                max_point_parts=max_points_part,
                point_parts=points_value,
                result_parts=result_parts,
                result=result,
                full_explanation=append_tool_summary(
                    full_explanation,
                    tools,
                    tool_call_summary,
                ),
                feedback=append_rubric_feedback(
                    append_result_table(feedback, points_value, max_points_part, result_parts),
                    rubric_eval,
                    rubrics,
                ),
                points=points_value,
                max_points=max_points_total,
                rubric_eval=rubric_eval,
            )

        valid_results = {"pass", "fail", "error"}
        if isinstance(max_points_part, list):
            raw_result_parts = raw_grade.get("result_parts")
            if not isinstance(raw_result_parts, list) or len(raw_result_parts) != len(max_points_part):
                return invalid_grade("Grader error: expected result_parts as a list matching the part structure.")
            if any(result_value not in valid_results for result_value in raw_result_parts):
                return invalid_grade("Grader error: result_parts contains an invalid value.")

            point_parts = [
                float(max_value) if result_value == "pass" else 0.0
                for result_value, max_value in zip(raw_result_parts, max_points_part)
            ]
            result = aggregate_result(raw_result_parts)

            return GradeResult(
                max_point_parts=max_points_part,
                point_parts=point_parts,
                result_parts=raw_result_parts,
                result=result,
                full_explanation=append_tool_summary(
                    full_explanation,
                    tools,
                    tool_call_summary,
                ),
                feedback=append_rubric_feedback(
                    append_result_table(feedback, point_parts, max_points_part, raw_result_parts),
                    rubric_eval,
                    rubrics,
                ),
                points=float(sum(point_parts)),
                max_points=max_points_total,
                rubric_eval=rubric_eval,
            )

        raw_result = raw_grade.get("result")
        if raw_result not in valid_results:
            return invalid_grade("Grader error: expected result to be pass, fail, or error.")

        point_parts = float(max_points_total) if raw_result == "pass" and max_points_total is not None else 0.0
        return GradeResult(
            max_point_parts=max_points_part,
            point_parts=point_parts,
            result_parts=raw_result,
            result=raw_result,
            full_explanation=append_tool_summary(
                full_explanation,
                tools,
                tool_call_summary,
            ),
            feedback=append_rubric_feedback(
                append_result_table(feedback, point_parts, max_points_part, raw_result),
                rubric_eval,
                rubrics,
            ),
            points=point_parts,
            max_points=max_points_total,
            rubric_eval=rubric_eval,
        )


    def _make_llm_caller(self, provider, model, api_key, task, timeout, tools=None):
        """
        Creates a function that calls the specified LLM provider with the given parameters.
        
        Parameters
        ----------
        provider: str
            The LLM provider to use ("openai" or "hf").
        model: str
            The model to use for grading.
        api_key: str
            The API key for authentication with the LLM provider.
        task: str
            The input prompt to send to the LLM.
        timeout: float
            The timeout in seconds for the API call.
        tools: list[str] | None
            Built-in tool names enabled for the request.

        Returns
        -------
        function
            A function that, when called, will execute the API call to the 
            specified LLM provider and return: 
                result:  GradeResult
                    Grading result
                input_tokens, output_tokens: int
                    Number of tokens used in the API call (input & output)
        """
        if provider == "openai":
            client = OpenAI(api_key=api_key)
            requested_tools = [tool for tool in (tools or []) if tool in self.SUPPORTED_TOOLS]

            def call_openai():
                request_kwargs = {
                    "model": model,
                    "input": task,
                    "temperature": 1 if model.startswith("gpt-5-mini") else 0,
                    "timeout": timeout,
                }

                if "web_search" in requested_tools:
                    request_kwargs["tools"] = [{"type": "web_search"}]
                else:
                    request_kwargs["text"] = {
                        "format": {
                            "type": "json_object"
                        }
                    }

                resp = client.responses.create(**request_kwargs)

                response_text = resp.output_text or ""
                if not response_text.strip():
                    raise ValueError("OpenAI response did not contain output_text.")

                normalized_response_text = normalize_json_response_text(response_text)

                try:
                    parsed = GraderRawResult.model_validate_json(normalized_response_text)
                except ValidationError as exc:
                    raise ValueError(f"Failed to parse OpenAI JSON response: {exc}") from exc

                tool_call_summary = summarize_tool_calls(resp)

                # Get the total tokens used (input + output)
                if resp.usage is not None:
                    inputs_tokens = resp.usage.input_tokens
                    output_tokens = resp.usage.output_tokens
                else:
                    inputs_tokens = 0
                    output_tokens = 0
                return parsed, inputs_tokens, output_tokens, tool_call_summary
            
            return call_openai

        elif provider == "hf":
            import requests
            hf_model = model.replace("hf:", "")
            url = f"https://router.huggingface.co/models/{hf_model}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}"}

            def call_hf():
                payload = {
                    "model": hf_model,
                    "messages": [
                        {"role": "user", "content": task}
                    ],
                    "temperature": 0,
                }

                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()

                # Extract assistant message
                text = data["choices"][0]["message"]["content"]

                # Set tokens to 0 now since HF API does not provide then
                input_tokens = 0
                output_tokens = 0

                # Parse using your existing GradeResult model
                return GraderRawResult.model_validate_json(normalize_json_response_text(text)), input_tokens, output_tokens, None

            return call_hf

        else:
            raise ValueError(f"Unknown provider '{provider}'")
        
    def get_admin_key(self, model: str) -> tuple[str | None, str | None]:
        """
        Determine whether the admin key may be used for this grading request.

        Returns:
            (admin_key_or_none, reason_message_or_none)

            If admin_key is None, reason_message contains the full user-facing message.
            If admin_key is not None, reason_message is None.
        """

        prefs = self.load_admin_preferences()
        print(f"Admin preferences loaded: {prefs}")
        admin_key = prefs.get("openaiApiKey", None)
        

        # 1. No admin key at all
        if admin_key is None or not admin_key.strip():
            return None, (
                "Please add your OpenAI API key to continue."
            )

        # 2. Model not allowed for admin usage
        allowed_models = prefs.get("allowedModels", [])
        if model not in allowed_models:
            return None, (
                "This model is not available for the free community service. "
                "Select another model or add your own OpenAI API key."
            )

        # 3. Token-limit logic
        limit_info = prefs.get("tokenLimit", {})
        token_limit = limit_info.get("limit", 0)
        period = limit_info.get("period", "unlimited")

        # Compute cutoff timestamp based on period
        from datetime import datetime, timedelta

        now = datetime.now(timezone.utc)
        cutoff = None

        if period == "per_hour":
            cutoff = now - timedelta(hours=1)
            reset_period = "hour"
        elif period == "per_day":
            cutoff = now - timedelta(days=1)
            reset_period = "day"
        elif period == "per_week":
            cutoff = now - timedelta(weeks=1)
            reset_period = "week"
        elif period == "per_month":
            cutoff = now - timedelta(days=30)
            reset_period = "month"
        elif period == "unlimited":
            cutoff = None

        # If there is no cutoff, we can skip the DB query and token counting
        if cutoff is None:
            return admin_key, None

        
        # Query DB for token usage in the window
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff_str = cutoff.isoformat(timespec="seconds")
        sql = """
            SELECT SUM(tokens_in + tokens_out)
            FROM submissions
            WHERE used_admin_key = 1
            AND timestamp >= ?
        """
        params = (cutoff_str,)
        print(f"Executing DB query:\n{sql}\nWith params: {params}")
        cursor.execute(sql, params)
        total_tokens = cursor.fetchone()[0] or 0
        conn.close()

        # 4. Compare to token limit
        if total_tokens >= token_limit:
            return None, (
                f"The community usage has exceeded the free token limit for this {reset_period}. "
                "Please add your OpenAI API key to continue."
            )

        # 5. All checks passed
        print('admin key=', admin_key)
        return admin_key, None

    def api_key_walkthrough(self) -> str:
        """
        Returns a special token that tells the frontend to launch the
        API Key Setup Wizard modal.
        """
        return "__START_API_KEY_WALKTHROUGH__"

    def grade(
            self, 
            question_dict: dict,
            student_soln : str, 
            part_label: str="all",
            unit_name: str = "",
            qtag: str = "",
            provider : str = "openai",
            model: str="gpt-4.1-mini",
            api_key: str | None = None,
            timeout: float = 20.) -> GradeResult:
        """
        Grades a student's solution using the OpenAI API.
        
        Parameters
        ----------
        question_dict: dict
            The question configuration dictionary loaded from the unit package.
        student_soln: str
            The student's solution text.
        part_label: str
            The part label to grade (or "all" for whole question).
        unit_name: str
            The unit name for the question.
        qtag: str
            The question tag identifier.
        provider: str
            The model provider to use for grading (e.g., "openai" or "hf").
        model: str
            The  model to use for grading.
        api_key: str | None
            The API key (either OpenAI API key or Hugging Face token) to use for authentication.
        timeout: float
            The timeout in seconds for the API call.

        Returns
        -------
        grade: dictionary corresponding to GradeResult
            The grading dictionary result containing 'result', 'full_explanation', and 'feedback'.
            Note the pydantic GradeResult model is converted to a dict before returning.
        """
        question_text = str(question_dict.get("question_text", ""))
        solution = str(question_dict.get("solution", ""))
        grading_notes = str(question_dict.get("grading_notes", ""))
        required = question_dict.get("required", True) is not False
        partial_credit = question_dict.get("partial_credit", False) is True
        tools = question_dict.get("tools", [])
        parts = question_dict.get("parts", [])
        rubrics = question_dict.get("rubrics", {})
        rubric_total = question_dict.get("rubric_total")
        part_labels = [part.get("part_label", "all") for part in parts]
        max_points = [part.get("points", 0) for part in parts]
        if not qtag:
            qtag = str(question_dict.get("qtag", ""))

        grade = None
        tokens_in = 0
        tokens_out = 0
        timed_out = False
        tool_call_summary = None
        used_admin_key = False
        t0 = time.time()

        task, max_points_part = self.build_task_prompt(
            question_dict,
            student_soln,
            part_label=part_label,
        )

        if provider == "openai" and not api_key:
            admin_key, reason = self.get_admin_key(model)
            if admin_key is None:
                token = self.api_key_walkthrough()
                return self.grade_post_process(
                    {
                        "result": "error",
                        "full_explanation": token,
                        "feedback": reason or "",
                    },
                    partial_credit=partial_credit,
                    max_points_part=max_points_part,
                    part_labels=part_labels,
                    part_label=part_label,
                    rubrics=rubrics,
                    rubric_total=rubric_total,
                    tools=tools,
                ).model_dump()
            api_key = admin_key
            used_admin_key = True

        # Only attempt API call if no error yet
        if grade is None:
            log_std(f'Calling {provider} for grading...')
            
            # Create the API call function
            try:
                call_llm = self._make_llm_caller(provider, model, api_key, task, timeout, tools=tools)
            except Exception as e:
                grade = {
                    "result": "error",
                    "full_explanation": f"Failed to initialize LLM client: {e}",
                    "feedback": "Initialization failed."
                }

        if grade is None:

            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(call_llm)
            
            try:
                additional_timeout = 5.0  # seconds
                total_timeout = timeout + additional_timeout
                
                # Get the result with timeout
                response, tokens_in, tokens_out, tool_call_summary = future.result(timeout=total_timeout)
                grade = response.model_dump()
                log_std(f"Received response from {provider}.")

            except ThreadTimeoutError:
                # Thread timed out
                timed_out = True
                log_error(f"Thread timed out after {total_timeout} seconds.")
                explanation = (
                    f"{provider} API did not respond within {total_timeout} seconds. "
                    f"(timeout={timeout}, extra={additional_timeout})."
                )
                grade = {
                    "result": "error",
                    "full_explanation": explanation,
                    "feedback": f"{provider} server not responding in time. Try again."
                }

            except APITimeoutError:
                timed_out = True
                log_error(f"{provider} API call timed out at the SDK level.")
                # SDK-level timeout
                explanation = (
                    f"{provider} API responded with a timeout after {timeout} seconds."
                )
                grade = {
                    "result": "error",
                    "full_explanation": explanation,
                    "feedback": "The grading request took too long to process."
                }
            
            except Exception as e:
                log_error(f"{provider} API call failed: {str(e)}")
                grade = {
                    'result': 'error', 
                    'full_explanation': f'{provider} API call failed: {str(e)}', 
                    'feedback': f'There was an error while trying to grade the solution using {provider}.'}
            finally:
                # IMPORTANT: do NOT overwrite grade here
                executor.shutdown(wait=False, cancel_futures=True)

        grade = self.grade_post_process(
            grade,
            partial_credit=partial_credit,
            max_points_part=max_points_part,
            part_labels=part_labels,
            part_label=part_label,
            rubrics=rubrics,
            rubric_total=rubric_total,
            tools=tools,
            tool_call_summary=tool_call_summary,
        ).model_dump()

        # ---------------------------------------------------------
        # 4. Save raw response to scratch/resp.json
        # ---------------------------------------------------------
        resp_path = os.path.join(self.scratch_dir, "resp.json")
        with open(resp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(grade, indent=2))
        
        # ---------------------------------------------------------
        # 5. Log submission to database (ALWAYS happens)
        # ---------------------------------------------------------
        t1 = time.time()
        latency_ms = int((t1 - t0) * 1000)
        point_parts = grade.get("point_parts")
        max_point_parts = grade.get("max_point_parts")
        result_parts = grade.get("result_parts")
        self.insert_submission(
            timestamp=datetime.now(timezone.utc).isoformat(),
            question_text=question_text,
            ref_soln=solution,
            grading_notes=grading_notes,
            student_soln=student_soln,
            part_label=part_label,
            unit_name=unit_name,
            qtag=qtag,
            required=required,
            partial_credit=partial_credit,
            tools_json=json.dumps(tools if tools is not None else []),
            model=model,
            timeout=timeout,
            latency_ms=latency_ms,
            raw_prompt=task,
            result=grade.get("result", "error"),
            full_explanation=grade.get("full_explanation", ""),
            feedback=grade.get("feedback", ""),
            point_parts_json=json.dumps(point_parts) if isinstance(point_parts, list) else None,
            max_point_parts_json=json.dumps(max_point_parts) if isinstance(max_point_parts, list) else None,
            result_parts_json=json.dumps(result_parts),
            points=grade.get("points"),
            max_points=grade.get("max_points"),
            tokens_in = tokens_in,
            tokens_out = tokens_out,
            timed_out=1 if timed_out else 0,
            used_admin_key=used_admin_key
        )
        
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
    
    def get_storage_path(self) -> str:
        """
        Returns the root storage directory.
        On Render: uses LLMGRADER_STORAGE_PATH (e.g., /var/data)
        Locally: falls back to ./local_data
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

    def load_admin_preferences(self) -> dict:
        """
        Load admin preferences from the JSON file at get_admin_pref_path().

        Returns the stored dict on success, or a default dict if the file
        does not exist or contains malformed JSON.
        """
        defaults = {
            "openaiApiKey": "",
            "hfToken": "",
            "allowedModels": [],
            "tokenLimit": {
                "limit": 0,
                "period": "unlimited"
            }
        }

        path = self.get_admin_pref_path()
        if not os.path.exists(path):
            return defaults

        try:
            with open(path, "r", encoding="utf-8") as f:
                prefs = json.load(f)
                return prefs
        except (json.JSONDecodeError, OSError):
            return defaults
            

    
    @staticmethod
    def initialize_field_format():
        # 1. Validate FIELD_FORMAT keys are real DB fields
        unknown = set(Grader.FIELD_FORMAT.keys()) - set(Grader.DB_SCHEMA.keys())
        if unknown:
            raise ValueError(f"FIELD_FORMAT contains unknown fields: {unknown}")

        # 2. Add missing DB fields with default formatting
        for field in Grader.DB_SCHEMA.keys():
            if field not in Grader.FIELD_FORMAT:
                Grader.FIELD_FORMAT[field] = "wrap80"

        # 3. Optional: warn about fields that defaulted
        # (Useful during development, can remove later)
        # print("FIELD_FORMAT auto-filled defaults for:", 
        #       [f for f in DB_SCHEMA.keys() if FIELD_FORMAT[f] == "wrap80"])
        