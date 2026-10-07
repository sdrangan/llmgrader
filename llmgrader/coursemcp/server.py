"""The course MCP tools: what a student's own AI can ask the portal.

Read-only, and for now limited to course and unit titles -- nothing a
student could not see on the portal's landing page.  Questions, rubrics,
solutions and slides arrive in later steps of ``plans/course_mcp.md``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from llmgrader.services.course_registry import CourseRegistry

INSTRUCTIONS = (
    "Course material from an LLM Grader portal. Call list_courses first: "
    "every other tool takes a course_id, and it must be one list_courses "
    "returned."
)


def build_course_mcp(registry: CourseRegistry) -> FastMCP:
    """A FastMCP server whose tools read the courses *registry* serves."""
    mcp = FastMCP(
        "llmgrader-course",
        instructions=INSTRUCTIONS,
        # Mounted at /mcp by the portal, so the app itself serves its root.
        streamable_http_path="/",
        # No per-client session on the server: each POST is answered on its
        # own, so any gunicorn worker can take any request.
        stateless_http=True,
        # A plain JSON body rather than an event stream, which is all a
        # read-only tool needs and passes through WSGI unbuffered or not.
        json_response=True,
        # FastMCP turns DNS-rebinding protection on whenever its host is
        # localhost, which is its default.  That protection allows only
        # localhost Host headers, so on Render every request would be refused.
        # It guards servers on a user's own machine; this one is public.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )

    def require_course(course_id: str):
        # An unknown or archived id is an error, never a fall back to the
        # default course -- the same rule as bind_course in routes/api.py.
        if registry.get(course_id) is None:
            raise ValueError(
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
