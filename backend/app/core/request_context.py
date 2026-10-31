"""Give every HTTP request an id, and write one log line per request.

The id is a fresh UUID, never taken from the client: an id a client could pick
would let it plant lines that look like they belong to someone else's request.
It is returned as the ``X-Request-ID`` response header, so a user reporting an
error can quote it, and every log line the request causes carries it (see
``app.core.log_config``).

A pure ASGI middleware rather than ``@app.middleware("http")``: it must be the
outermost layer so the CORS, CSRF and rate-limit responses carry an id too.
"""

import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.log_config import request_id_var

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        # Deliberately never reset. uvicorn runs each request in its own task,
        # so the value dies with it, and leaving it set means uvicorn's own
        # "Exception in ASGI application" traceback, logged after this
        # middleware has unwound, still names the request it belongs to.
        request_id_var.set(request_id)
        status = 500  # what the client gets if the app raises before responding
        started = time.perf_counter()
        logged = False

        def log_request() -> None:
            nonlocal logged
            if logged:
                return
            logged = True
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            client = scope.get("client")
            # The path only: a query string can hold an e-mail address (admin
            # user search) and must never reach the logs.
            logger.info(
                "%s %s %s %.0fms",
                scope["method"],
                scope["path"],
                status,
                duration_ms,
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": duration_ms,
                    "client": client[0] if client else None,
                },
            )

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)
            # Logged as the last of the body goes out, not when the app returns:
            # Starlette runs BackgroundTasks (feedback triage, e-mail sends)
            # before returning, which would bill their seconds to a response
            # the client already has, and lose the line if the container
            # stops mid-task.
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                log_request()

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log_request()  # a response that never finished: an exception, a dropped client


async def unhandled_error_response(request: Request, exc: Exception) -> Response:
    """The 500 for an exception nothing else handled, carrying the request id.

    Starlette sends this from ServerErrorMiddleware, which always sits OUTSIDE
    user middleware, so the response bypasses RequestContextMiddleware's header.
    Yet it is the response a user is most likely to report. Same body as
    Starlette's default; Starlette re-raises afterwards, so uvicorn still logs
    the traceback (with the id, as the var is never reset).
    """
    request_id = request_id_var.get()
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return PlainTextResponse("Internal Server Error", status_code=500, headers=headers)
