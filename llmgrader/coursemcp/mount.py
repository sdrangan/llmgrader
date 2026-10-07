"""Serving the course MCP from inside the Flask portal, at ``/mcp``.

The portal is a WSGI app run by ``gunicorn run:app``; the MCP library is ASGI.
Rather than move the portal onto an ASGI server, the MCP app is wrapped as WSGI
(a2wsgi) and dispatched by path, so Flask and its start command are unchanged.

FastMCP's HTTP transport needs its session manager running inside an event
loop before it can answer.  a2wsgi does not run ASGI lifespan events, so that
loop runs in a daemon thread started here, and a2wsgi is handed the same loop
to run requests on.

**That thread is started lazily, in the process that serves the request.**  A
thread does not survive ``fork``: if it is started in gunicorn's master and the
worker is forked afterwards, the worker inherits a loop nothing is running, and
every MCP request handed to it waits forever -- holding gunicorn's only sync
worker, and so the whole portal, until the request times out.  That is what
happened on Render with the loop started at app creation.  Building everything
on the first request, and rebuilding if the pid has changed since, makes it
impossible for a forked process to inherit a running server.  (The session
manager can only be ``run()`` once per instance, so a rebuild means a new
FastMCP, not just a new thread.)
"""

from __future__ import annotations

import asyncio
import os
import threading

from a2wsgi import ASGIMiddleware
from flask import Flask
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from llmgrader.coursemcp.server import build_course_mcp
from llmgrader.services.course_registry import CourseRegistry

MOUNT_PATH = "/mcp"
START_TIMEOUT_S = 10


class CourseMCPRunner:
    """The course MCP as a WSGI app, started on first use in each process."""

    def __init__(self, registry: CourseRegistry):
        self.registry = registry
        self._lock = threading.Lock()
        self._pid: int | None = None
        self._wsgi = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _running_here(self) -> bool:
        return (
            self._pid == os.getpid()
            and self._loop is not None
            and self._loop.is_running()
        )

    def _start(self) -> None:
        mcp = build_course_mcp(self.registry)
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
        if not started.wait(timeout=START_TIMEOUT_S):
            raise RuntimeError("Course MCP session manager did not start")

        self._wsgi = ASGIMiddleware(asgi_app, loop=loop)
        self._loop = loop
        self._pid = os.getpid()
        print(f"[CourseMCP] Started in process {self._pid}")

    def wsgi(self):
        """The running MCP for this process, starting it if need be."""
        if not self._running_here():
            with self._lock:
                if not self._running_here():
                    self._start()
        return self._wsgi

    def __call__(self, environ, start_response):
        # The dispatcher hands a request for exactly /mcp on with an empty
        # PATH_INFO, which Starlette answers with a 307 to /mcp/.  Students
        # paste the URL without the slash, and an AI client following a
        # redirected POST is not something to depend on.
        if not environ.get("PATH_INFO"):
            environ["PATH_INFO"] = "/"
        try:
            mcp_wsgi = self.wsgi()
        except Exception as exc:
            print(f"[CourseMCP] Could not start: {exc!r}")
            start_response("503 Service Unavailable",
                           [("Content-Type", "text/plain; charset=utf-8")])
            return [b"The course MCP could not start on this server.\n"]
        return mcp_wsgi(environ, start_response)


def mount_course_mcp(app: Flask, registry: CourseRegistry) -> None:
    """Serve the course MCP for *registry* at ``/mcp`` on *app*.

    Starts nothing: no thread, no loop.  See the module docstring.
    """
    runner = CourseMCPRunner(registry)
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {MOUNT_PATH: runner})
    app.course_mcp = runner
