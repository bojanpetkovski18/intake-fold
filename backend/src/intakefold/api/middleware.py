import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from intakefold.api.problems import problem_response

log = structlog.get_logger()

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Cache-Control": "no-store",
}
HSTS_VALUE = "max-age=31536000; includeSubDomains"


class RequestContextMiddleware:
    """Trace ID, security headers and the request log, on every response.

    Pure ASGI rather than BaseHTTPMiddleware, and it handles unexpected errors itself:
    FastAPI's Exception handler runs outside user middleware, so its 500 response would
    have neither headers nor a trace ID.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Trace-Id"] = trace_id
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if self.hsts:
                    headers["Strict-Transport-Security"] = HSTS_VALUE
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            log.exception("request_failed")
            if response_started:
                raise
            response = problem_response(500, "An unexpected error occurred.")
            await response(scope, receive, send_with_headers)
        finally:
            # The path only: query strings and bodies can carry sensitive data.
            log.info(
                "request_finished",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
