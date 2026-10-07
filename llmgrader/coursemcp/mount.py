"""Serving the course MCP from inside the Flask portal, at ``/mcp``.

The portal is a WSGI app run by ``gunicorn run:app``; the MCP library is ASGI.
Rather than move the portal onto an ASGI server, the MCP app is wrapped as WSGI
(a2wsgi) and dispatched by path, so Flask and its start command are unchanged.

The MCP server's HTTP transport needs its session manager running inside an event
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
MCPServer, not just a new thread.)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import threading

from a2wsgi import ASGIMiddleware
from flask import Flask
from mcp.server.transport_security import TransportSecuritySettings
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from llmgrader.coursemcp.server import build_course_mcp
from llmgrader.services.course_registry import CourseRegistry

MOUNT_PATH = "/mcp"
START_TIMEOUT_S = 10

# What a browser shows at /mcp.  Worded for the person checking the address,
# since that is who sends a GET.
NOT_POST_MESSAGE = (
    b"This is the course MCP server, and it is running.\n\n"
    b"It is not a web page: add this address to an AI assistant as a "
    b"connector (MCP server) instead of opening it in a browser.\n"
)


TOKEN_ENV = "LLMGRADER_MCP_TOKEN"
PUBLIC_ENV = "LLMGRADER_MCP_PUBLIC"
MIN_TOKEN_CHARS = 16


def configured_public() -> bool:
    """``LLMGRADER_MCP_PUBLIC`` is set to a true value: serve content openly."""
    return os.environ.get(PUBLIC_ENV, "").strip().lower() in {"1", "true", "yes"}


def configured_token() -> str | None:
    """The course token from ``LLMGRADER_MCP_TOKEN``, or None when unset."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    return token or None


def _same(given: str, token: str) -> bool:
    """Constant-time comparison.  Bytes, since compare_digest rejects non-ASCII str."""
    return hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))


def _refusal(message: str) -> bytes:
    # A JSON-RPC error body, so an AI client shows the message rather than a
    # bare status code.
    return json.dumps({"jsonrpc": "2.0", "id": None,
                       "error": {"code": -32001, "message": message}}).encode()


class CourseMCPRunner:
    """The course MCP as a WSGI app, started on first use in each process.

    **Access.**  Three modes, from the environment:

    * ``LLMGRADER_MCP_PUBLIC`` set -- everything is served, to anyone, with no
      token.  For a course whose problems are study material and whose answer
      key it does not mind being readable: students then need only the
      portal's address.  A token, if also set, is ignored.
    * ``LLMGRADER_MCP_TOKEN`` set -- every MCP request must carry it, and the
      question, rubric, solution and slide tools are served.
    * Neither -- open, but titles only.  The safe default: an answer key is
      never published without the instructor choosing one of the above.

    The token is accepted two ways:

    * ``Authorization: Bearer <token>`` -- preferred.  claude.ai's connector
      form, VS Code's ``mcp.json`` and ``claude mcp add --header`` can all send
      a header, and a header stays out of URLs, server logs and screenshots.
    * ``/mcp/<token>`` -- for a client that cannot set headers.

    A missing or wrong token is refused with 403, not 401: a 401 tells an
    OAuth-aware client such as claude.ai to start a sign-in flow, which this
    server does not offer, and the student would see a broken sign-in rather
    than the message.
    """

    def __init__(self, registry: CourseRegistry):
        self.registry = registry
        self.public = configured_public()
        # Public mode wants no token: requiring one would defeat the point.
        self.token = None if self.public else configured_token()
        if self.public and configured_token():
            print(f"[CourseMCP] {PUBLIC_ENV} is set, so {TOKEN_ENV} is ignored: "
                  "content is served without a token.")
        # The portal's public address, for links a student can open (a
        # slide's image).  LLMGRADER_PUBLIC_URL if set; otherwise taken from
        # each request -- behind Render's proxy, X-Forwarded-Proto says https.
        self.public_url_override = os.environ.get("LLMGRADER_PUBLIC_URL", "").rstrip("/") or None
        self.public_url: str | None = self.public_url_override
        if self.token and len(self.token) < MIN_TOKEN_CHARS:
            print(f"[CourseMCP] Warning: {TOKEN_ENV} is under {MIN_TOKEN_CHARS} "
                  "characters; use a long random value.")
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
        mcp = build_course_mcp(self.registry, content=self.public or self.token is not None,
                               public_url=lambda: self.public_url)
        asgi_app = mcp.streamable_http_app(  # creates mcp.session_manager
            # Mounted at /mcp by the dispatcher, so the app serves its root.
            streamable_http_path="/",
            # No per-client session on the server: each POST is answered on
            # its own, so any gunicorn worker can take any request.
            stateless_http=True,
            # A plain JSON body rather than an event stream, which is all a
            # read-only tool needs and passes through WSGI unbuffered or not.
            json_response=True,
            # DNS-rebinding protection is switched on whenever the host is
            # localhost, which is the default.  It then allows only localhost
            # Host headers, so on Render every request would be refused.  It
            # guards servers on a user's own machine; this one is public.
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )

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
        token_in_path = self._take_path_token(environ)
        if not self.public_url_override and environ.get("HTTP_HOST"):
            scheme = (environ.get("HTTP_X_FORWARDED_PROTO") or environ.get("wsgi.url_scheme")
                      or "https").split(",")[0].strip()
            self.public_url = f"{scheme}://{environ['HTTP_HOST']}"
        # Only POST reaches the MCP app.  A GET is a request for a standing
        # server-to-client event stream, which mcp 2 opens and never closes
        # for any client accepting */* -- so a browser, or a crawler, visiting
        # /mcp would hold gunicorn's only sync worker, and the portal with it.
        # This server sends nothing unprompted, and the MCP spec has a server
        # without that stream answer GET with 405.  That is also the clearest
        # thing a person checking the address in a browser can be shown.
        if environ.get("REQUEST_METHOD") != "POST":
            start_response("405 Method Not Allowed", [
                ("Allow", "POST"),
                ("Content-Type", "text/plain; charset=utf-8"),
            ])
            return [NOT_POST_MESSAGE]
        if self.token and not (token_in_path or self._bearer_matches(environ)):
            start_response("403 Forbidden", [("Content-Type", "application/json")])
            return [_refusal(
                "This course MCP needs the course access token. Add it to the "
                "connector as the request header 'Authorization: Bearer <token>', "
                "using the token your instructor posted.")]
        try:
            mcp_wsgi = self.wsgi()
        except Exception as exc:
            print(f"[CourseMCP] Could not start: {exc!r}")
            start_response("503 Service Unavailable",
                           [("Content-Type", "text/plain; charset=utf-8")])
            return [b"The course MCP could not start on this server.\n"]
        return mcp_wsgi(environ, start_response)


    def _take_path_token(self, environ) -> bool:
        """Whether the path is ``/<token>``; if so, rewrite it to ``/``."""
        if not self.token:
            return False
        segment = environ["PATH_INFO"].strip("/")
        if segment and _same(segment, self.token):
            environ["PATH_INFO"] = "/"
            return True
        return False

    def _bearer_matches(self, environ) -> bool:
        header = environ.get("HTTP_AUTHORIZATION", "")
        scheme, _, value = header.partition(" ")
        return scheme.lower() == "bearer" and _same(value.strip(), self.token)


def mount_course_mcp(app: Flask, registry: CourseRegistry) -> None:
    """Serve the course MCP for *registry* at ``/mcp`` on *app*.

    Starts nothing: no thread, no loop.  See the module docstring.
    """
    runner = CourseMCPRunner(registry)
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {MOUNT_PATH: runner})
    app.course_mcp = runner
