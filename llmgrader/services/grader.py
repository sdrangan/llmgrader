import textwrap
import os
import shutil
from pathlib import Path
import json
import os
from urllib import response
import pandas as pd
from openai import OpenAI, APITimeoutError
import xml.etree.ElementTree as ET
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


import sys
from datetime import datetime, timezone

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
    max_points : float | None
        The total maximum points for the question, i.e., sum(max_point_parts)
        The grader does not need to return this field since the backend will compute it.
    result: Literal["pass", "fail", "error"] | list[Literal["pass", "fail", "error"]]
    """
    max_point_parts: float | list[float] | None
    point_parts: float | list[float] | None
    result_parts: Literal["pass", "fail", "error", "partial"] | list[Literal["pass", "fail", "error", "partial"]]
    result: Literal["pass", "fail", "error", "partial"]
    full_explanation: str
    feedback: str
    points: float | None = None
    max_points: float | None


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



def strip_code_block_leading_newlines(html_text):
    """
    Find <pre><code>...</code></pre> blocks and strip leading newlines from the code content.
    
    Args:
        html_text: HTML text that may contain code blocks
        
    Returns:
        HTML text with leading newlines removed from code blocks
    """
    def strip_newlines_match(match):
        """Strip leading newlines from the code content in a regex match."""
        code_content = match.group(1)
        # Remove leading newlines (but preserve internal formatting)
        stripped_code = code_content.lstrip('\n')
        return f'<pre><code>{stripped_code}</code></pre>'
    
    # Pattern to match <pre><code>...</code></pre> blocks
    # Uses non-greedy matching and DOTALL flag to handle multiline code
    pattern = r'<pre><code>(.*?)</code></pre>'
    result = re.sub(pattern, strip_newlines_match, html_text, flags=re.DOTALL)
    
    return result


def clean_cdata(text: str) -> str:
    """
    Clean CDATA content from XML elements.
    Removes leading newline, dedents, strips trailing whitespace, and cleans code blocks.
    
    Args:
        text: Raw CDATA text content
        
    Returns:
        Cleaned and dedented text
    """
    if not text:
        return ""
    # Remove a single leading newline if present
    if text.startswith("\n"):
        text = text[1:]
    # Dedent and strip trailing whitespace
    text = textwrap.dedent(text).strip()
    # Strip leading newlines from code blocks
    text = strip_code_block_leading_newlines(text)
    return text


class Grader:
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
            return {"error": "No valid units found. Check llmgrader_config.xml."}, 400

        print(f"[Upload] Loaded {len(self.units)} unit(s): {list(self.units.keys())}")

        return {"status": "ok"}

    def load_unit_pkg(self):
        self.units = {}

        # Logging
        fn = os.path.join(self.scratch_dir, "load_unit_pkg_log.txt")
        log = open(fn, "w", encoding="utf-8")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.write(f'Loading unit package at {now}\n')

        # Set the solution package path.  If explicitly set in constructor, use it
        if self.soln_pkg is not None:
            soln_pkg_path = self.soln_pkg

        else:
            # Check unified storage root
            storage_root = os.environ.get("LLMGRADER_STORAGE_PATH")

            if storage_root:
                soln_pkg_path = os.path.join(storage_root, "soln_pkg")
            else:
                # Local fallback
                local_root = os.path.join(os.getcwd(), "local_data")
                os.makedirs(local_root, exist_ok=True)
                soln_pkg_path = os.path.join(local_root, "soln_pkg")

        soln_pkg_path = os.path.abspath(soln_pkg_path)
        os.makedirs(soln_pkg_path, exist_ok=True)
        self.soln_pkg = soln_pkg_path

        log.write(f'Using solution package path: {soln_pkg_path}\n')
    

        # Get the path to llmgrader_config.xml
        llmgrader_config_path = os.path.join(soln_pkg_path, "llmgrader_config.xml")
        if not os.path.exists(llmgrader_config_path):
            log.write(f'llmgrader_config.xml not found in solution package: {llmgrader_config_path}\n')
            self.units = {}
            log.close()
            return

        
        # Parse llmgrader_config.xml
        try:
            config_tree = ET.parse(llmgrader_config_path)
            config_root = config_tree.getroot()
            log.write(f'Successfully parsed llmgrader_config.xml\n')
        except Exception as e:
            log.write(f'Failed to parse llmgrader_config.xml: {e}\n')
            self.units = {}
            log.close()
            return
        
        # Extract units from config
        units_elem = config_root.find('units')
        if units_elem is None:
            log.write('No <units> section found in llmgrader_config.xml\n')
            self.units = {}
            log.close()
            return
        
        # Build ordered list (sections + units) and parallel unit/path lists
        self.units_order = []
        self.units_list = []
        self.xml_path_list = []

        for child in units_elem:
            if child.tag == 'section':
                section_name = (child.text or '').strip()
                self.units_order.append({"type": "section", "name": section_name})
                log.write(f'Found section: {section_name}\n')
            elif child.tag == 'unit':
                name = child.findtext('name')
                destination = child.findtext('destination')
                if not name or not destination:
                    log.write(f'Skipping unit: missing <name> or <destination> element\n')
                    continue
                self.units_order.append({"type": "unit", "name": name})
                self.units_list.append(name)
                self.xml_path_list.append(destination)
                log.write(f'Found unit in config: {name} -> {destination}\n')

        if not self.units_list:
            log.write('No <unit> elements found in llmgrader_config.xml\n')
            self.units = {}
            log.close()
            return

        units = {}

        # Loop over each unit and specified solution file
        for name, xml_path in zip(self.units_list, self.xml_path_list):


            xml_path = os.path.normpath(xml_path)
            xml_path = os.path.join(soln_pkg_path, xml_path)

            log.write(f'Processing unit: {name}\n')
            log.write(f'  XML file: {xml_path}\n')

            # Check that the path exists
            if not os.path.exists(xml_path):
                log.write(f"Skipping unit {name}: file {xml_path} does not exist.\n")
                continue

            # Parse the XML file
            try:
                tree = ET.parse(xml_path)
                root = tree.getroot()
            except Exception as e:
                log.write(f"Skipping unit {name}: failed to parse XML: {e}\n")
                continue

            # Build unit_dict from XML
            unit_dict = {}
            
            for question in root.findall('question'):
                qtag = question.get('qtag')
                if not qtag:
                    log.write(f"Skipping question in unit {name}: missing qtag attribute\n")
                    continue
                
                # Extract preferred_model attribute
                preferred_model = question.get('preferred_model', '')
                
                # Extract question_text element (CDATA)
                question_text_elem = question.find('question_text')
                question_text = clean_cdata(question_text_elem.text if question_text_elem is not None else '')
                
                # Extract solution element (CDATA)
                solution_elem = question.find('solution')
                solution = clean_cdata(solution_elem.text if solution_elem is not None else '')
                
                # Extract grading_notes element (CDATA)
                grading_notes_elem = question.find('grading_notes')
                grading_notes = clean_cdata(grading_notes_elem.text if grading_notes_elem is not None else '')
                
                # Extract required element (boolean). Fall back to legacy <grade>.
                required_elem = question.find('required')
                if required_elem is None:
                    required_elem = question.find('grade')
                if required_elem is not None and required_elem.text:
                    required = required_elem.text.strip().lower() == 'true'
                else:
                    required = True  # Default to true if not specified

                # Extract partial_credit element (boolean)
                partial_credit_elem = question.find('partial_credit')
                if partial_credit_elem is not None and partial_credit_elem.text:
                    partial_credit = partial_credit_elem.text.strip().lower() == 'true'
                else:
                    partial_credit = False
                
                # Extract parts
                parts = []
                parts_elem = question.find('parts')
                if parts_elem is not None:
                    for part in parts_elem.findall('part'):
                        part_id = part.get('id')
                        part_label_elem = part.find('part_label')
                        points_elem = part.find('points')
                        
                        # Use id attribute as part_label if part_label element not found
                        if part_label_elem is not None and part_label_elem.text:
                            part_label = part_label_elem.text.strip()
                        elif part_id:
                            part_label = part_id
                        else:
                            part_label = 'all'
                        
                        # Get points
                        if points_elem is not None and points_elem.text:
                            try:
                                points = int(points_elem.text.strip())
                            except ValueError:
                                points = 0
                        elif part.get('points'):
                            try:
                                points = int(part.get('points'))
                            except ValueError:
                                points = 0
                        else:
                            points = 0
                        
                        parts.append({
                            'part_label': part_label,
                            'points': points
                        })
                
                # Build question dictionary
                question_dict = {
                    'qtag': qtag,
                    'question_text': question_text,
                    'solution': solution,
                    'grading_notes': grading_notes,
                    'parts': parts,
                    'required': required,
                    'partial_credit': partial_credit,
                    'preferred_model': preferred_model
                }
                
                unit_dict[qtag] = question_dict

            # Validate the unit_dict has required fields
            required_fields = [
                "qtag",
                "question_text",
                "solution",
                "grading_notes",
                "parts",
                "required",
            ]
            
            # Check that every question has the required fields
            valid_questions = {}
            for qtag in unit_dict:
                qdict = unit_dict[qtag]
                missing_fields = [field for field in required_fields if field not in qdict]
                if missing_fields:
                    log.write(f"Skipping question {qtag} in unit {name}: missing required fields: {missing_fields}\n")
                    continue
                valid_questions[qtag] = qdict
                
            # Update unit_dict with only valid questions
            unit_dict = valid_questions
            
            if len(unit_dict) == 0:
                log.write(f"Skipping unit {name}: no valid questions found\n")
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
    
    

    
    def build_task_prompt(
        self,
        question_text : str,
        ref_solution : str,
        grading_notes : str,
        student_soln : str,
        part_label: str = "all",
        partial_credit: bool = False,
        part_labels: list[str] | None = None,
        max_points: list[int] | None = None,
    ) -> tuple[str, int | list[int] | None]:
        """
        Build the grading prompt sent to the language model.

        Parameters
        ----------
        question_text: str
            The question text in HTML format.
        ref_solution: str
            The reference solution text.
        grading_notes: str
            Instructor grading notes used to guide evaluation.
        student_soln: str
            The student's submitted solution text.
        part_label: str
            The specific part being graded, or "all" for whole-question grading.
        partial_credit: bool
            Whether the question is configured to allow partial credit.
        part_labels: list[str] | None
            Ordered list of part labels defined for the question.
        max_points: list[int] | None
            Ordered list of maximum point values corresponding to part_labels.

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
        prompt = textwrap.dedent("""
            Your task is to grade a student's solution to an engineering problem.

            You will be given:
            - HTML version of the question,
            - HTML version of a correct reference solution,
            - Plain text grading notes, and
            - Plain text student solution.

            Return only the fields explicitly requested below.
            The backend will compute derived fields such as max_point_parts, max_points,
            aggregate result, aggregate points, and any fields not explicitly requested.
            Text fields such as "full_explanation" and "feedback" may use Markdown,
            including paragraphs, lists, and tables.
        """)

        multi_part = part_labels is not None and len(part_labels) > 1
        max_points_part = None

        if max_points is not None:
            if multi_part and part_label == "all":
                max_points_part = max_points
            elif max_points:
                if multi_part and part_labels:
                    try:
                        part_index = part_labels.index(part_label)
                        max_points_part = max_points[part_index]
                    except (ValueError, IndexError):
                        max_points_part = None
                else:
                    max_points_part = max_points[0]

        if partial_credit:
            if not part_labels or not max_points or len(part_labels) != len(max_points):
                partial_credit = False

        # ---------- Mode 1: partial credit, multi-part, grade ALL ----------
        if partial_credit and multi_part and part_label == "all":
            prompt += "\nThis question allows partial credit. It has multiple parts.\n"
            prompt += "The parts and their maximum points are:\n\n"
            for lbl, pts in zip(part_labels, max_points):
                prompt += f"- ({lbl}): max_points = {pts}\n"

            prompt += textwrap.dedent("""
                
                You must return a JSON object with the following fields:

                - "point_parts": a list of numeric values, one for each part, in the exact order above.
                Each point value must be between 0 and the maximum points for that part.
                - "full_explanation": a detailed explanation of your grading reasoning.
                - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
                student improve without revealing the reference solution or grading notes.

                Follow these steps:

                1. For each part, carefully identify the student's answer for that part. Students may
                write answers out of order or embed multiple parts together. Use your judgment to
                isolate the portion corresponding to each part.
                2. Compare the student's work for each part to the corresponding part in the reference
                solution, using the grading notes as guidance.
                3. In "full_explanation", explain your reasoning step by step, describing what is correct
                and what is incorrect for each part.
                4. Based on your reasoning and the grading notes, assign a numeric score to each part,
                between 0 and that part's maximum points. Place these point values in the "point_parts" list in
                the exact order given above.
                5. In "feedback", provide concise, student-facing guidance that helps the student improve,
                without revealing the reference solution or grading notes.

                Important rules:
                - Do not return part labels.
                - Do not return maximum points.
                - Do not compute or return the total points; the backend will sum the points.
                - Do not return result, result_parts, max_point_parts, or max_points.
                - Return only valid JSON with no surrounding text.
            """)

        # ---------- Mode 2: partial credit,  multi-part,  grading one part ----------
        elif partial_credit and multi_part:
            idx = part_labels.index(part_label)
            max_points_part = max_points[idx]

            prompt += f"\nThis question allows partial credit. You are grading only part ({part_label}).\n"
            prompt += f"The maximum points for this part is {max_points_part} points.\n\n"

            prompt += textwrap.dedent(f"""
                You must return a JSON object with the following fields:

                - "points": the numeric points for this part, between 0 and {max_points_part}.
                - "full_explanation": a detailed explanation of your grading reasoning for this part.
                - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
                student improve without revealing the reference solution or grading notes.

                Follow these steps:

                1. Extract the student's answer for part ({part_label}) from the student solution.
                Students may write answers out of order or embed multiple parts together. Use your
                judgment to isolate the portion corresponding to part ({part_label}).
                2. Compare the student's solution for part ({part_label}) to the corresponding part in the
                reference solution, using the grading notes as guidance.
                3. In "full_explanation", work through your reasoning step by step, explaining what is
                correct and what is incorrect.
                4. Based on your reasoning and the grading notes, decide how many points (from 0 to
                {max_points_part}) the student earns for this part and set "points" to that numeric value.
                5. In "feedback", provide concise, student-facing guidance that helps the student improve,
                without revealing the reference solution or grading notes.

                Important rules:
                - Do not return points for other parts.
                - Do not return a list of points.
                - Do not return result, result_parts, max_point_parts, point_parts, or max_points.
                - Return only valid JSON with no surrounding text.
            """)
        # ---------- Mode 3: partial credit,  single part ----------
        elif partial_credit:
            max_points_question = max_points[0]

            prompt += "\nThis question allows partial credit. It has a single part.\n"
            prompt += f"The maximum points for this question is {max_points_question} points.\n\n"

            prompt += textwrap.dedent(f"""
            You must return a JSON object with the following fields:

            - "points": the numeric points for this question, between 0 and {max_points_question}.
            - "full_explanation": a detailed explanation of your grading reasoning.
            - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
            student improve without revealing the reference solution or grading notes.

            Follow these steps:

            1. Read the student's solution carefully.
            2. Compare the student's solution to the reference solution, using the grading notes as guidance.
            3. In "full_explanation", work through your reasoning step by step, explaining what is
            correct and what is incorrect.
            4. Based on your reasoning and the grading notes, decide how many points (from 0 to
            {max_points_question}) the student earns and set "points" to that numeric value.
            5. In "feedback", provide concise, student-facing guidance that helps the student improve,
            without revealing the reference solution or grading notes.

            Important rules:
            - Do not return a list of points.
            - Do not return result, result_parts, max_point_parts, point_parts, or max_points.
            - Return only valid JSON with no surrounding text.
            """)


        # ---------- Mode 4: binary, multi-part, grade ALL ----------
        elif not partial_credit and multi_part and part_label == "all":
            prompt += "\nThis question has multiple parts. The parts are:\n\n"
            for lbl in part_labels:
                prompt += f"- ({lbl})\n"

            prompt += textwrap.dedent("""
                This question is configured for binary grading (no partial credit).

                You must return a JSON object with the following fields:

                - "result_parts": a list with one value for each part, in the same order as the parts above.
                Each value must be one of "pass", "fail", or "error".
                - "full_explanation": a detailed explanation of your grading reasoning.
                - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
                student improve without revealing the reference solution or grading notes.

                Follow these steps:

                1. For each part, carefully identify the student's answer for that part. Students may
                write answers out of order or embed multiple parts together. Use your judgment to
                isolate the portion corresponding to each part.
                2. Compare the student's work for each part to the corresponding part in the reference
                solution, using the grading notes as guidance.
                3. In "full_explanation", work through your reasoning step by step, explaining what is
                correct and what is incorrect for each part.
                4. After you have completed your reasoning, decide the correctness of each part and place
                the corresponding values in "result_parts" in the exact part order above.
                5. In "feedback", provide concise, student-facing guidance that helps the student improve,
                without revealing the reference solution or grading notes.

                Important rules:
                - Do not return part points.
                - Do not return aggregate result, max_point_parts, point_parts, points, or max_points.
                - Return only valid JSON with no surrounding text.
            """)

        
        elif multi_part:
            prompt += f"\nThis question is configured for binary grading. You are grading only part ({part_label}).\n\n"

            prompt += textwrap.dedent(f"""
                You must return a JSON object with the following fields:

                - "result": "pass", "fail", or "error"
                - "full_explanation": a detailed explanation of your grading reasoning for this part.
                - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
                student improve without revealing the reference solution or grading notes.

                Follow these steps:

                1. Extract the student's answer for part ({part_label}) from the student solution.
                Students may write answers out of order or embed multiple parts together. Use your
                judgment to isolate the portion corresponding to part ({part_label}).
                2. Compare the student's solution for part ({part_label}) to the corresponding part in the
                reference solution, using the grading notes as guidance.
                3. In "full_explanation", work through your reasoning step by step, explaining what is
                correct and what is incorrect.
                4. After you have completed your reasoning, decide the correctness for this part:
                - If the solution is correct, set "result" to "pass".
                - If the solution is incorrect, set "result" to "fail".
                - If you cannot grade due to missing or inconsistent information, set "result" to "error".
                5. In "feedback", provide concise, student-facing guidance that helps the student improve,
                without revealing the reference solution or grading notes.

                Important rules:
                - Do not return part points.
                - Do not return result_parts, max_point_parts, point_parts, points, or max_points.
                - Return only valid JSON with no surrounding text.
            """)


        else:  # Mode 6: binary, single-part question
            prompt += "\nThis question is configured for binary grading (no partial credit).\n\n"

            prompt += textwrap.dedent("""
                You must return a JSON object with the following fields:

                - "result": "pass", "fail", or "error"
                - "full_explanation": a detailed explanation of your grading reasoning.
                - "feedback": concise (up to 5 sentences), student-facing guidance that helps the
                student improve without revealing the reference solution or grading notes.

                Follow these steps:

                1. Read the student's solution carefully.
                2. Compare the student's solution to the reference solution, using the grading notes as guidance.
                3. In "full_explanation", work through your reasoning step by step, explaining what is
                correct and what is incorrect.
                4. After you have completed your reasoning, decide the overall correctness:
                - If the solution is correct, set "result" to "pass".
                - If the solution is incorrect, set "result" to "fail".
                - If you cannot grade due to missing or inconsistent information, set "result" to "error".
                5. In "feedback", provide concise, student-facing guidance that helps the student improve,
                without revealing the reference solution or grading notes.

                Important rules:
                - Do not return result_parts, max_point_parts, point_parts, points, or max_points.
                - Return only valid JSON with no surrounding text.
            """)

        prompt += "\n\n--- QUESTION HTML ---\n" + question_text
        prompt += "\n\n--- REFERENCE SOLUTION HTML ---\n" + ref_solution
        prompt += "\n\n--- GRADING NOTES ---\n" + grading_notes
        prompt += "\n\n--- STUDENT SOLUTION ---\n" + student_soln

        return prompt, max_points_part

    def grade_post_process(
        self,
        raw_grade: dict,
        partial_credit: bool,
        max_points_part: int | list[int] | None,
        part_labels: list[str] | None = None,
        part_label: str = "all",
    ) -> GradeResult:
        """
        Fill in derived GradeResult fields that are not returned directly by the grader.
        """
        full_explanation = str(raw_grade.get("full_explanation", ""))
        feedback = str(raw_grade.get("feedback", ""))

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
            explanation: str,
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
                "| part_label | points | max_points | result |",
                "| --- | --- | --- | --- |",
            ]
            for row_label, row_point, row_max_point, row_result in zip(row_labels, row_points, row_max_points, row_results):
                table_lines.append(f"| {row_label} | {row_point} | {row_max_point} | {row_result} |")

            if explanation:
                return explanation + "\n" + "\n".join(table_lines)
            return "\n".join(table_lines).lstrip("\n")

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
                feedback=feedback,
                points=None,
                max_points=total_max_points(max_points_part),
            )

        max_points_total = total_max_points(max_points_part)

        if partial_credit:
            if isinstance(max_points_part, list):
                raw_point_parts = raw_grade.get("point_parts")
                if not isinstance(raw_point_parts, list) or len(raw_point_parts) != len(max_points_part):
                    return invalid_grade("Grader error: expected point_parts as a list matching the part structure.")

                point_parts: list[float] = []
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
                    full_explanation=append_result_table(full_explanation, point_parts, max_points_part, result_parts),
                    feedback=feedback,
                    points=points,
                    max_points=max_points_total,
                )

            raw_points = raw_grade.get("points")
            if not isinstance(raw_points, (int, float)) or isinstance(raw_points, bool):
                return invalid_grade("Grader error: expected numeric points for this grading mode.")

            points_value = float(raw_points)
            scalar_max_points = max_points_total
            if scalar_max_points is not None and (points_value < 0 or points_value > scalar_max_points):
                return invalid_grade("Grader error: points is outside the allowed range.")

            result_parts = classify_points(points_value, scalar_max_points)
            result = aggregate_result(result_parts)
            return GradeResult(
                max_point_parts=max_points_part,
                point_parts=points_value,
                result_parts=result_parts,
                result=result,
                full_explanation=append_result_table(full_explanation, points_value, max_points_part, result_parts),
                feedback=feedback,
                points=points_value,
                max_points=max_points_total,
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
                full_explanation=append_result_table(full_explanation, point_parts, max_points_part, raw_result_parts),
                feedback=feedback,
                points=float(sum(point_parts)),
                max_points=max_points_total,
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
            full_explanation=append_result_table(full_explanation, point_parts, max_points_part, raw_result),
            feedback=feedback,
            points=point_parts,
            max_points=max_points_total,
        )


    def _make_llm_caller(self, provider, model, api_key, task, timeout):
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

            def call_openai():
                resp = client.responses.parse(
                    model=model,
                    input=task,
                    text_format=GraderRawResult,
                    temperature=1 if model.startswith("gpt-5-mini") else 0,
                    timeout=timeout
                )

                # Get the total tokens used (input + output)
                if resp.usage is not None:
                    inputs_tokens = resp.usage.input_tokens
                    output_tokens = resp.usage.output_tokens
                else:
                    inputs_tokens = 0
                    output_tokens = 0
                return resp.output_parsed, inputs_tokens, output_tokens
            
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
                return GraderRawResult.model_validate_json(text), input_tokens, output_tokens

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
            question_text: str, 
            solution : str, 
            grading_notes: str, 
            student_soln : str, 
            required: bool = True,
            partial_credit: bool = False,
            part_labels: list[str] | None = None,
            max_points: list[int] | None = None,
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
        question_text: str
            The HTML question text.
        solution: str
            The reference solution text.
        grading_notes: str
            The grading notes text.
        student_soln: str
            The student's solution text.
        required: bool
            Whether the question is required for submission/export workflows.
        partial_credit: bool
            Whether partial credit grading is enabled for this question.
        part_labels: list[str] | None
            The ordered list of part labels defined for the question.
        max_points: list[int] | None
            The ordered list of maximum points for each part.
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
        # Initialize variables
        grade = None
        tokens_in = 0
        tokens_out = 0
        timed_out = False
        used_admin_key = False
    
        # Start measuring time
        t0 = time.time()

        log_std(
            f"partial_credit={partial_credit}, part_labels={part_labels}, "
            f"max_points={max_points}"
        )

        
        # ---------------------------------------------------------
        # 1. Build the task prompt
        # ---------------------------------------------------------
        task, max_points_part = self.build_task_prompt(
            question_text,
            solution,
            grading_notes,
            student_soln,
            part_label=part_label,
            partial_credit=partial_credit,
            part_labels=part_labels,
            max_points=max_points,
        )

        # ---------------------------------------------------------
        # 2. Write task prompt to scratch/task.txt
        # ---------------------------------------------------------
        task_path = os.path.join(self.scratch_dir, "task.txt")
        with open(task_path, "w", encoding="utf-8") as f:
            f.write(task)

        # ---------------------------------------------------------
        # 3. Call the LLM API with timeout handling
        # ---------------------------------------------------------

        # Create the OpenAI LLM client
        if not api_key or not api_key.strip():
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
                ).model_dump()
            api_key = admin_key
            used_admin_key = True
        else:
            used_admin_key = False

        # Only attempt API call if no error yet
        if grade is None:
            log_std(f'Calling {provider} for grading...')
            
            # Create the API call function
            try:
                call_llm = self._make_llm_caller(provider, model, api_key, task, timeout)
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
                response, tokens_in, tokens_out = future.result(timeout=total_timeout)
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
        