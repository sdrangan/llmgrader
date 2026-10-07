"""Serving the course MCP from inside the Flask portal, at ``/mcp``.

The portal is a WSGI app run by ``gunicorn run:app``; the MCP library is ASGI.
Rather than move the portal onto an ASGI server, the MCP app is wrapped as WSGI
(a2wsgi) and dispatched by path, so Flask and its start command are unchanged.

FastMCP's HTTP transport needs its session manager running inside an event
loop before the first request.  a2wsgi does not run ASGI lifespan events, so
the loop is started here, in a daemon thread, and a2wsgi is handed that same
loop to run requests on.

This runs at app creation, which under gunicorn without ``--preload`` is inside
each worker.  With ``--preload`` it would run in the master before the fork,
and the thread would not survive into the workers.
"""

from __future__ import annotations

import asyncio
import threading

from a2wsgi import ASGIMiddleware
from flask import Flask
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from llmgrader.coursemcp.server import build_course_mcp
from llmgrader.services.course_registry import CourseRegistry

MOUNT_PATH = "/mcp"


def mount_course_mcp(app: Flask, registry: CourseRegistry) -> None:
    """Serve the course MCP for *registry* at ``/mcp`` on *app*."""
    mcp = build_course_mcp(registry)
    asgi_app = mcp.streamable_http_app()  # creates mcp.session_manager

    loop = asyncio.new_event_loop()
    started = threading.Event()

    async def hold_session_manager() -> None:
        async with mcp.session_manager.run():
            started.set()
            await asyncio.Event().wait()

    threading.Thread(
        target=loop.run_until_complete,
        args=(hold_session_manager(),),
        name="course-mcp-loop",
        daemon=True,
    ).start()
    if not started.wait(timeout=10):
        raise RuntimeError("Course MCP session manager did not start")

    mcp_wsgi = ASGIMiddleware(asgi_app, loop=loop)

    def serve_mount_root(environ, start_response):
        # The dispatcher hands a request for exactly /mcp on with an empty
        # PATH_INFO, which Starlette answers with a 307 to /mcp/.  Students
        # paste the URL without the slash, and an AI client following a
        # redirected POST is not something to depend on.
        if not environ.get("PATH_INFO"):
            environ["PATH_INFO"] = "/"
        return mcp_wsgi(environ, start_response)

    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {MOUNT_PATH: serve_mount_root})
    app.course_mcp = mcp
