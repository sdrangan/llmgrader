"""The course MCP tools: what a student's own AI can ask the portal.

Read-only, and for now limited to course and unit titles -- nothing a
student could not see on the portal's landing page.  Questions, rubrics,
solutions and slides arrive in later steps of ``plans/course_mcp.md``.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from llmgrader.services.course_registry import CourseRegistry

INSTRUCTIONS = (
    "Course material from an LLM Grader portal. Call list_courses first: "
    "every other tool takes a course_id, and it must be one list_courses "
    "returned."
)


def build_course_mcp(registry: CourseRegistry) -> MCPServer:
    """An MCP server whose tools read the courses *registry* serves.

    Only the tools are defined here.  How it is served over HTTP is
    ``mount.py``'s business: in mcp 2 those settings belong to the app, not
    the server.
    """
    mcp = MCPServer(
        "llmgrader-course",
        instructions=INSTRUCTIONS,
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

    return mcp
