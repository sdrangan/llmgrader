"""The course MCP tools: what a student's own AI can ask the portal.

Read-only.  Two tiers:

* **Titles** -- ``list_courses``, ``list_units``: nothing a student could not
  see on the portal's landing page.  Always served.
* **Content** -- questions, rubrics, solutions.  Served only when the portal
  has a course token configured (``mount.py``), because a complete answer key
  must not sit on the open web where it is crawled and indexed
  (``plans/course_mcp.md`` decision 4).  The gate is the token, not the tools:
  without one, the content tools are not even registered.
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from llmgrader.coursemcp import content as cc
from llmgrader.services.course_registry import CourseRegistry

INSTRUCTIONS = (
    "Course material from an LLM Grader portal. Call list_courses first: "
    "every other tool takes a course_id, and it must be one list_courses "
    "returned."
)

CONTENT_INSTRUCTIONS = (
    " Units come from list_units and questions from list_questions; pass "
    "their names exactly. This is practice material for a student who is "
    "studying: when they are working on a problem, help them reason toward "
    "the answer -- use the rubric to see what counts, and the worked solution "
    "to check their reasoning or build a hint -- rather than reproducing the "
    "solution, unless they ask for it. The portal grades their submitted "
    "answers; nothing done through these tools is graded or recorded."
)


def log_call(tool: str, **ids) -> None:
    """One log line per tool call: the tool and the ids it was asked about.

    Never the student's question -- that is student data (and these tools are
    never sent it anyway).  The ids are what show how often the answer key is
    actually pulled.
    """
    detail = " ".join(f"{k}={v!r}" for k, v in ids.items())
    print(f"[CourseMCP] {tool} {detail}".rstrip())


def build_course_mcp(registry: CourseRegistry, *, content: bool = False) -> MCPServer:
    """An MCP server whose tools read the courses *registry* serves.

    *content* adds the question, rubric and solution tools; ``mount.py``
    passes it only when a course token is configured.

    Only the tools are defined here.  How it is served over HTTP is
    ``mount.py``'s business: in mcp 2 those settings belong to the app, not
    the server.
    """
    mcp = MCPServer(
        "llmgrader-course",
        instructions=INSTRUCTIONS + (CONTENT_INSTRUCTIONS if content else ""),
        # No subscriptions/listen.  A listen request is a POST held open to
        # stream change notifications, and under gunicorn's sync worker an
        # open stream holds the whole portal.  Course content changes only on
        # an upload, so there is nothing to stream anyway.
        subscriptions=False,
    )

    def require_course(course_id: str):
        # An unknown or archived id is an error, never a fall back to the
        # default course -- the same rule as bind_course in routes/api.py.
        # ToolError, not ValueError: only a ToolError's message reaches the
        # model, and this one tells it what to do next.
        if registry.get(course_id) is None:
            raise ToolError(
                f"Unknown course {course_id!r}. Call list_courses for valid ids."
            )
        return registry.grader_for(course_id)

    @mcp.tool()
    def list_courses() -> list[dict]:
        """List the courses this portal serves: id, name and semester.

        Use the id as course_id in every other tool.
        """
        return [
            {"course_id": entry.id, "name": entry.name, "semester": entry.semester}
            for entry in registry.courses()
        ]

    @mcp.tool()
    def list_units(course_id: str) -> list[dict]:
        """List a course's units in teaching order, with section headings.

        Each item is a section heading or a unit; a unit carries its number of
        questions.  course_id must come from list_courses.
        """
        grader = require_course(course_id)
        items = []
        for item in grader.units_order:
            if item["type"] == "unit":
                questions = grader.units.get(item["name"], {})
                items.append({"type": "unit", "name": item["name"],
                              "questions": len(questions)})
            else:
                items.append({"type": item["type"], "name": item["name"]})
        return items

    if content:
        _add_content_tools(mcp, require_course)

    return mcp


def _with_figures(payload: dict, figures: list) -> list:
    """A tool result: the JSON payload, then each figure after its own label.

    Each image is preceded by "Figure n:", so the [Figure n] placeholders in
    the text map onto images unambiguously even when one could not be sent.
    """
    payload = dict(payload)
    notes = cc.figure_notes(figures)
    if notes:
        payload["figure_notes"] = notes
    blocks: list = [json.dumps(payload, indent=2, ensure_ascii=False)]
    for number, figure in enumerate(figures, start=1):
        if figure is not None and len(figure.data) <= cc.MAX_FIGURE_BYTES:
            blocks.append(f"Figure {number}:")
            blocks.append(Image(data=figure.data, format=figure.mime.split("/", 1)[1]))
    return blocks


def _add_content_tools(mcp: MCPServer, require_course) -> None:

    @mcp.tool()
    def list_questions(course_id: str, unit: str | None = None) -> list[dict]:
        """List a course's questions: unit, qtag, a short label, parts and points.

        Omit unit for every question in the course -- the whole index is small,
        so prefer this to guessing, and match the student's description against
        the labels yourself.  Pass unit (a name from list_units) for one unit.
        The label is the start of the question text; call get_question for the
        full text and its figures.
        """
        log_call("list_questions", course=course_id, unit=unit)
        grader = require_course(course_id)
        names = [cc.resolve_unit(grader, unit)] if unit else cc.unit_names(grader)
        index = []
        for name in names:
            for qtag, question in grader.units.get(name, {}).items():
                parts = cc.parts_summary(question)
                index.append({
                    "unit": name,
                    "qtag": qtag,
                    "label": cc.question_label(question),
                    "parts": parts,
                    "points": sum(p["points"] or 0 for p in parts),
                })
        return index

    @mcp.tool()
    def get_question(course_id: str, unit: str, qtag: str):
        """Get one question: its full text, its parts with points, and its figures.

        unit and qtag come from list_questions.  The text is HTML; [Figure n]
        marks where the n-th attached figure belongs.  This is what the student
        sees.  Use get_rubric for what earns credit, and get_solution for the
        worked solution.

        When the instructor has written variation_guidance, it says what is
        safe to change when making a similar practice problem and what must
        stay fixed.  Follow it if the student asks for one.
        """
        log_call("get_question", course=course_id, unit=unit, qtag=qtag)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        figures = cc.figures_in(question.get("question_text", ""), grader.soln_pkg)
        payload = {
            "unit": unit_name,
            "qtag": tag,
            "question": cc.tidy_html(question.get("question_text", "")),
            "parts": cc.parts_summary(question),
            "partial_credit": bool(question.get("partial_credit")),
        }
        if question.get("variation_guidance"):
            payload["variation_guidance"] = question["variation_guidance"]
        return _with_figures(payload, figures)

    @mcp.tool()
    def get_rubric(course_id: str, unit: str, qtag: str) -> dict:
        """Get the rubric the portal grades one question against.

        Returns each rubric item -- what it checks, its part, the points it is
        worth (negative for a deduction) and the grader's notes on it -- plus
        the question's grading notes, which describe common mistakes and what
        is accepted.  Use it to see what counts and to aim feedback or hints at
        it; it does not contain the worked solution.
        """
        log_call("get_rubric", course=course_id, unit=unit, qtag=qtag)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        items = [
            {
                "id": item_id,
                "part": item.get("part", ""),
                "display_text": item.get("display_text", ""),
                "condition": cc.plain_text(item.get("condition", "")),
                "points": item.get("point_adjustment", 0),
                "notes": item.get("notes", ""),
            }
            for item_id, item in (question.get("rubrics") or {}).items()
        ]
        return {
            "unit": unit_name,
            "qtag": tag,
            "parts": cc.parts_summary(question),
            "partial_credit": bool(question.get("partial_credit")),
            "scoring": question.get("rubric_total") or "",
            "rubric": items,
            "grading_notes": question.get("grading_notes", ""),
        }

    @mcp.tool()
    def get_solution(course_id: str, unit: str, qtag: str):
        """Get the instructor's worked solution to one question, with its figures.

        Prefer using this to check the student's reasoning, find where it goes
        wrong, or build a hint, rather than showing it to them -- unless they
        ask to see the solution.  unit and qtag come from list_questions.
        """
        log_call("get_solution", course=course_id, unit=unit, qtag=qtag)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        figures = cc.solution_figures(question, grader.soln_pkg)
        return _with_figures({
            "unit": unit_name,
            "qtag": tag,
            "solution": cc.tidy_html(question.get("solution", "")),
        }, figures)
