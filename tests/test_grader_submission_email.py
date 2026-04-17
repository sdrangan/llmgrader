import sqlite3

import pytest

from llmgrader.services.grader import Grader


class _FakeRawResponse:
    def model_dump(self):
        return {
            "result": "pass",
            "full_explanation": "ok",
            "feedback": "ok",
        }


class _FakeProcessedResult:
    def model_dump(self):
        return {
            "result": "pass",
            "full_explanation": "ok",
            "feedback": "ok",
            "point_parts": None,
            "max_point_parts": 1.0,
            "result_parts": "pass",
            "points": None,
            "max_points": 1.0,
        }


@pytest.mark.parametrize(
    ("user_email", "expected_email"),
    [
        ("student@example.com", "student@example.com"),
        (None, None),
    ],
)
def test_grade_persists_optional_submission_user_email(tmp_path, monkeypatch, user_email, expected_email):
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(Grader, "load_unit_pkg", lambda self: None)
    monkeypatch.setattr(
        Grader,
        "build_task_prompt",
        lambda self, question_dict, student_soln, part_label="all": ("task", 1.0),
    )
    monkeypatch.setattr(
        Grader,
        "_make_llm_caller",
        lambda self, *args, **kwargs: (lambda: (_FakeRawResponse(), 11, 7, "")),
    )
    monkeypatch.setattr(Grader, "grade_post_process", lambda self, *args, **kwargs: _FakeProcessedResult())

    grader = Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(tmp_path / "pkg"))

    grade = grader.grade(
        question_dict={
            "question_text": "Question",
            "solution": "Solution",
            "grading_notes": "Notes",
            "required": True,
            "partial_credit": False,
            "tools": [],
            "parts": [{"part_label": "all", "points": 1.0}],
            "rubrics": {},
            "rubric_total": None,
        },
        student_soln="My answer",
        unit_name="unit1",
        qtag="q1",
        provider="openai",
        model="gpt-5.4-mini",
        api_key="test-key",
        user_email=user_email,
    )

    assert grade["result"] == "pass"

    conn = sqlite3.connect(grader.db_path)
    try:
        row = conn.execute(
            "SELECT user_email FROM submissions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row == (expected_email,)