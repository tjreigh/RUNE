"""FastAPI adapter for the RUNE web REPL prototype.

Run locally with:
    .venv/bin/python -m uvicorn app:app --app-dir web --port 8000

This module never imports the core (src/) directly -- everything
core-facing goes through rune_worker.evaluate_isolated(), which runs each
evaluation in a disposable subprocess with a hard wall-clock timeout.
"""

import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import rune_worker

STATIC_DIR = Path(__file__).resolve().parent / "static"

MAX_CHUNKS = 10_000  # bounds a pathological client sending endless
                      # zero-length "more_body" chunks -- byte-size alone
                      # doesn't catch that, since each adds 0 to the total


async def _send_413(send):
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": b'{"detail":"request body too large"}',
    })


async def _send_429(send, retry_after: float):
    await send({
        "type": "http.response.start",
        "status": 429,
        "headers": [
            (b"content-type", b"application/json"),
            (b"retry-after", str(max(1, int(retry_after))).encode("ascii")),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": b'{"detail":"rate limit exceeded"}',
    })


class MaxBodySizeMiddleware:
    """Real streaming request-body size enforcement. A Content-Length
    check alone is insufficient (a client can omit it, lie about it, or
    bypass it via chunked transfer); this counts actual bytes as chunks
    arrive and rejects before the app ever sees an oversized body. Raw
    ASGI middleware, not Starlette's BaseHTTPMiddleware, which has known
    issues re-providing a consumed body stream to the downstream app.

    Accumulates into a single bytearray (not a growing list of ASGI
    messages) and replays exactly one reconstructed http.request message.
    The precise guarantee this provides: at most max_bytes plus one
    ASGI-provided chunk may momentarily be held in memory, since the
    middleware cannot control how large a single chunk the server hands
    it.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers", []))
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    return await _send_413(send)
            except ValueError:
                pass  # malformed header -- fall through to real enforcement

        body = bytearray()
        chunk_count = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return  # client gone mid-body -- stop, don't fabricate a
                         # completed request from a partial buffer
            if message["type"] != "http.request":
                break
            chunk_count += 1
            if chunk_count > MAX_CHUNKS:
                return await _send_413(send)
            chunk = message.get("body", b"") or b""
            if len(body) + len(chunk) > self.max_bytes:
                return await _send_413(send)  # rejected before ever being
                                                 # appended -- never retained
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


class FixedWindowRateLimiter:
    """Thread-safe, monotonic-clock fixed-window limiter with periodic stale
    entry cleanup and a hard bucket cap. Deliberately per-process (run a
    single uvicorn worker for v0.3)."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        max_buckets: int = 10_000,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, int]] = {}
        self._next_cleanup = time.monotonic() + window_seconds

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if now >= self._next_cleanup:
                self._buckets = {
                    k: v for k, v in self._buckets.items()
                    if now - v[0] < self.window_seconds
                }
                self._next_cleanup = now + self.window_seconds

            if key not in self._buckets and len(self._buckets) >= self.max_buckets:
                return False

            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= self.window_seconds:
                window_start, count = now, 0
            if count >= self.max_requests:
                self._buckets[key] = (window_start, count)
                return False
            self._buckets[key] = (window_start, count + 1)
            return True


class EvaluateRateLimitMiddleware:
    """Rate-limit every request to /evaluate before body parsing or schema
    validation, so malformed and oversized requests cannot bypass the cap.

    The client key comes from the ASGI scope populated by Uvicorn. For local
    v0.3 that is the direct peer address; v0.3.1 must only trust proxy headers
    from Caddy.
    """

    def __init__(self, app, limiter: FixedWindowRateLimiter):
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/evaluate":
            client = scope.get("client")
            client_key = client[0] if client else "unknown-client"
            if not self.limiter.allow(client_key):
                return await _send_429(send, self.limiter.window_seconds)
        return await self.app(scope, receive, send)


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chaos_threshold: int = Field(default=1, ge=0, strict=True)  # strict: no
        # silent str/float coercion; matches what @chaos can actually
        # produce (a non-negative integer, no negative literals in v0.1)


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a client-sent "limits"
    source: str                                 # field is rejected (422),
    state: StateModel | None = None              # never silently dropped


def create_app(
    *,
    max_concurrency: int = 4,
    rate_limit_max: int = 30,
    rate_limit_window: float = 60.0,
    max_source_length: int = 10_000,
    max_request_bytes: int = 16_384,
    eval_timeout: float = 2.0,
    evaluator=rune_worker.evaluate_isolated,
) -> FastAPI:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    rate_limiter = FixedWindowRateLimiter(rate_limit_max, rate_limit_window)
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=max_request_bytes)
    # Added after MaxBodySizeMiddleware so Starlette makes it the outer layer:
    # all /evaluate requests count before body parsing or validation.
    app.add_middleware(EvaluateRateLimitMiddleware, limiter=rate_limiter)
    app.state.concurrency_semaphore = threading.Semaphore(max_concurrency)
    app.state.rate_limiter = rate_limiter
    app.state.max_source_length = max_source_length
    app.state.eval_timeout = eval_timeout

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/evaluate")
    def evaluate_endpoint(payload: EvaluateRequest):
        if len(payload.source) > app.state.max_source_length:
            raise HTTPException(413, "source exceeds maximum length")

        if not app.state.concurrency_semaphore.acquire(blocking=False):
            raise HTTPException(503, "server busy, try again shortly")
        try:
            state_dict = (
                {"chaos_threshold": payload.state.chaos_threshold}
                if payload.state else {"chaos_threshold": 1}
            )
            outcome = evaluator(payload.source, state_dict, timeout=app.state.eval_timeout)
            return JSONResponse(status_code=outcome.status_code, content=outcome.body)
        finally:
            app.state.concurrency_semaphore.release()

    return app


app = create_app()  # module-level instance for `uvicorn app:app --app-dir web`
