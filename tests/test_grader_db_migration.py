import sqlite3

from llmgrader.services.grader import Grader


def test_temp_modify_db_adds_solution_image_paths_json_for_existing_db(tmp_path, monkeypatch) -> None:
    storage_dir = tmp_path / "storage"
    db_dir = storage_dir / "db"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "llmgrader.db"

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            student_soln TEXT
        )
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage_dir))
    monkeypatch.setattr(Grader, "load_unit_pkg", lambda self: None)

    grader = Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(tmp_path / "pkg"))

    conn = sqlite3.connect(grader.db_path)
    try:
        columns = {
            row[1]: row[2]
            for row in conn.execute("PRAGMA table_info(submissions)")
        }
    finally:
        conn.close()

    assert columns["solution_image_paths_json"] == "TEXT"