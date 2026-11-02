"""Demo webhook receiver. It has no database, and trusts nothing it has not verified."""

import html
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from intakefold.delivery.signing import EVENT_ID_HEADER, SIGNATURE_HEADER, verify

MAX_KEPT = 200
MAX_BODY_BYTES = 1024 * 1024
CSP = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"


@dataclass
class SinkState:
    secret: str
    fail_first: int
    now: Callable[[], int]
    received: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    seen: set[str] = field(default_factory=set[str])
    failures: dict[str, int] = field(default_factory=dict[str, int])
    lock: threading.Lock = field(default_factory=threading.Lock)


def build_sink(secret: str, fail_first: int = 0, now: Callable[[], int] | None = None) -> FastAPI:
    state = SinkState(secret, fail_first, now or (lambda: int(time.time())))
    app = FastAPI(title="Intakefold sink", docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/webhook")
    async def receive(request: Request) -> JSONResponse:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse({"error": "too_large"}, status_code=413)
        header = request.headers.get(SIGNATURE_HEADER, "")
        if not verify(state.secret, header, body, state.now()):
            return JSONResponse({"error": "bad_signature"}, status_code=401)
        event_id = request.headers.get(EVENT_ID_HEADER, "")
        if not event_id:
            return JSONResponse({"error": "no_event_id"}, status_code=400)
        with state.lock:
            if event_id in state.seen:
                # Delivery is at least once, so a repeat is expected and must change nothing.
                return JSONResponse({"duplicate": True}, status_code=200)
            failed = state.failures.get(event_id, 0)
            if failed < state.fail_first:
                state.failures[event_id] = failed + 1
                return JSONResponse({"error": "failing_on_purpose"}, status_code=503)
            state.seen.add(event_id)
            state.received.insert(0, {"event_id": event_id, "payload": json.loads(body)})
            del state.received[MAX_KEPT:]
        return JSONResponse({"duplicate": False}, status_code=200)

    @app.get("/events")
    def events() -> list[dict[str, object]]:
        with state.lock:
            return list(state.received)

    @app.get("/", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        with state.lock:
            items = list(state.received)
        rows = "".join(
            f"<li><code>{html.escape(str(item['event_id']))}</code>"
            f"<pre>{html.escape(json.dumps(item['payload'], indent=2))}</pre></li>"
            for item in items
        )
        body = (
            "<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<title>Intakefold sink</title><h1>Received events</h1>"
            f"<p>{len(items)} received.</p><ol>{rows}</ol></html>"
        )
        return HTMLResponse(body, headers={"Content-Security-Policy": CSP})

    app.state.sink = state
    return app


def create_app() -> FastAPI:
    """Entry point for `uvicorn --factory intakefold_sink.app:create_app`."""
    secret = os.environ.get("SINK_SECRET", "")
    if len(secret) < 32:
        raise SystemExit("Set SINK_SECRET to at least 32 characters.")
    return build_sink(secret, int(os.environ.get("SINK_FAIL_FIRST", "0")))
