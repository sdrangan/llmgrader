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
import io
import json
import os
import threading
import time

from a2wsgi import ASGIMiddleware
from flask import Flask
from mcp.server.transport_security import TransportSecuritySettings
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from llmgrader.coursemcp.server import build_course_mcp
from llmgrader.coursemcp.usage import build_rows, coarse_client, mint_session_id, parse_json
from llmgrader.services.course_registry import CourseRegistry
from llmgrader.services.mcp_usage import McpUsageStore, usage_db_path

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

# The demo tools (plans/demo_code_mcp.md) are served only with this set: a
# new thing served from the portal process ships behind a switch, so that
# unsetting it is the rollback.
CODE_ENV = "LLMGRADER_MCP_CODE"
DEMO_TOOLS = frozenset({"list_demos", "list_demo_files", "get_demo_file", "search_demos"})


def code_enabled() -> bool:
    return os.environ.get(CODE_ENV, "").strip().lower() in {"1", "true", "yes"}
MIN_TOKEN_CHARS = 16


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

    **The course token is optional.**  Unset (the default), the MCP is open:
    anyone with the address can use every tool, so students need nothing but
    the address.  Turning the MCP on at all (``LLMGRADER_MCP_ENABLED``) is
    already the instructor's choice to publish the course's solutions.  With
    ``LLMGRADER_MCP_TOKEN`` set, every MCP request must carry it -- for a
    course that reuses problems and wants to change the key each semester.

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

    def __init__(self, registry: CourseRegistry, usage: McpUsageStore | None = None):
        self.registry = registry
        # One row per MCP request, in its own database (plans/mcp_usage.md).
        self.usage = usage if usage is not None else McpUsageStore(
            usage_db_path(registry.storage.get_storage_path()))
        self.token = configured_token()
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
        # Each course's copy of its demo repo.  Creating it starts nothing:
        # the copy is loaded, and synced on a thread, on the first request.
        self.code = None
        if code_enabled():
            from llmgrader.coursemcp.code import CodeLibrary
            self.code = CodeLibrary(registry)

    def _running_here(self) -> bool:
        return (
            self._pid == os.getpid()
            and self._loop is not None
            and self._loop.is_running()
        )

    def _start(self) -> None:
        mcp = build_course_mcp(self.registry, content=True,
                               public_url=lambda: self.public_url, code=self.code)
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
        #
        # A GET is a browser checking the address, not use: it is not recorded.
        if environ.get("REQUEST_METHOD") != "POST":
            start_response("405 Method Not Allowed", [
                ("Allow", "POST"),
                ("Content-Type", "text/plain; charset=utf-8"),
            ])
            return [NOT_POST_MESSAGE]
        started = time.monotonic()
        body = self._read_body(environ)
        if self.token and not (token_in_path or self._bearer_matches(environ)):
            refusal = _refusal(
                "This course MCP needs the course access token. Add it to the "
                "connector as the request header 'Authorization: Bearer <token>', "
                "using the token your instructor posted.")
            start_response("403 Forbidden", [("Content-Type", "application/json")])
            return _Recorded([refusal], lambda: self._record(
                body, environ, 403, refusal, started, refused=True))
        self._warm_code()
        try:
            mcp_wsgi = self.wsgi()
        except Exception as exc:
            print(f"[CourseMCP] Could not start: {exc!r}")
            message = b"The course MCP could not start on this server.\n"
            start_response("503 Service Unavailable",
                           [("Content-Type", "text/plain; charset=utf-8")])
            return _Recorded([message], lambda: self._record(
                body, environ, 503, message, started))
        return self._serve(mcp_wsgi, environ, start_response, body, started)

    # ------------------------------------------------------------------
    # Recording (plans/mcp_usage.md, decision 7)
    # ------------------------------------------------------------------

    @staticmethod
    def _read_body(environ) -> bytes:
        """Read the request body, and put it back for the MCP app to read."""
        stream = environ.get("wsgi.input")
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        body = (stream.read(length) if length > 0 else stream.read()) if stream else b""
        environ["wsgi.input"] = io.BytesIO(body)
        environ["CONTENT_LENGTH"] = str(len(body))
        return body

    def _serve(self, mcp_wsgi, environ, start_response, body: bytes, started: float):
        """Answer through the MCP app, collecting the response to summarize it.

        The server answers in JSON (``json_response=True``), so the body is
        one short document and collecting it delays nothing.  An
        ``initialize`` response gains a minted ``Mcp-Session-Id``.
        """
        captured: dict = {}
        chunks: list[bytes] = []

        def capture(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = list(headers)
            return chunks.append

        result = mcp_wsgi(environ, capture)
        try:
            for chunk in result:
                chunks.append(chunk)
        finally:
            close = getattr(result, "close", None)
            if close is not None:
                close()

        status = captured.get("status", "500 Internal Server Error")
        headers = captured.get("headers", [])
        response_body = b"".join(chunks)
        status_code = int(status.split(" ", 1)[0])

        message = parse_json(body)
        if (isinstance(message, dict) and message.get("method") == "initialize"
                and status_code == 200
                and not any(name.lower() == "mcp-session-id" for name, _ in headers)):
            params = message.get("params") if isinstance(message.get("params"), dict) else {}
            info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
            session_id = mint_session_id(coarse_client(info.get("name")))
            headers.append(("Mcp-Session-Id", session_id))
            # The initialize itself is recorded under the id it is given.
            environ["HTTP_MCP_SESSION_ID"] = session_id

        start_response(status, headers)
        return _Recorded([response_body], lambda: self._record(
            body, environ, status_code, response_body, started))

    def _record(self, body, environ, status_code, response_body, started, *, refused=False):
        """Write this exchange's rows.  Never raises: the student has the answer."""
        try:
            duration_ms = int((time.monotonic() - started) * 1000)
            for row in build_rows(body, environ, status_code, response_body, duration_ms,
                                  refused=refused):
                row["package_version"] = self._package_version(row.get("course_id"))
                if self.code is not None and row.get("tool") in DEMO_TOOLS:
                    row["code_version"] = self.code.code_version(row.get("course_id"))
                self.usage.record(row)
        except Exception as exc:
            print(f"[McpUsage] Could not record a call: {exc!r}")

    def _warm_code(self) -> None:
        """Load each course's demo copy, and refresh a stale one on a thread.

        Any request does it, so a session's first calls warm the copy before
        a demo question.  Never waits on GitHub, and never fails a request.
        """
        if self.code is None:
            return
        try:
            self.code.warm()
        except Exception as exc:
            print(f"[CourseCode] Could not check the demo copies: {exc!r}")

    def _package_version(self, course_id):
        if not isinstance(course_id, str) or self.registry.get(course_id) is None:
            return None
        return self.registry.grader_for(course_id).package_version


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


class _Recorded:
    """A response body whose ``close()`` records the exchange.

    A WSGI server calls ``close()`` once the response has been sent, so the
    usage write adds to the request's time on the worker but never delays
    the answer.
    """

    def __init__(self, chunks: list[bytes], on_close):
        self._chunks = chunks
        self._on_close = on_close

    def __iter__(self):
        return iter(self._chunks)

    def close(self) -> None:
        on_close, self._on_close = self._on_close, None
        if on_close is not None:
            on_close()


def mount_course_mcp(app: Flask, registry: CourseRegistry) -> None:
    """Serve the course MCP for *registry* at ``/mcp`` on *app*.

    Starts nothing: no thread, no loop.  See the module docstring.
    """
    runner = CourseMCPRunner(registry)
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {MOUNT_PATH: runner})
    app.course_mcp = runner
