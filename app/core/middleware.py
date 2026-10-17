"""
app/core/middleware.py — ASGI-level request body streaming limiter and security middleware.

Protects the server from resource exhaustion and Starlette multipart buffer exhaustion (SEC-004):
1. Upfront Content-Length verification (fast rejection before reading body).
2. Streaming body inspection wrapping the ASGI `receive` callable:
   - Tracks cumulative chunk sizes as they stream across the wire.
   - Terminates immediately with HTTP 413 Payload Too Large if byte ceiling is exceeded,
     even if Content-Length was omitted or misleadingly understated.
   - Streams chunks through without accumulating the payload in memory.
3. Bounded limits:
   - Upload routes (/verify, /identify): MAX_AUDIO_SIZE_BYTES + 64KB multipart overhead margin.
   - Non-upload routes: 1 MB maximum.
4. WebSocket passthrough: scope["type"] == "websocket" is delegated to endpoint-level message guards.
"""

from typing import Optional
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app.core.config import MAX_AUDIO_SIZE_BYTES


class PayloadTooLargeError(Exception):
    """Raised when streaming ASGI body chunks exceed the configured ceiling."""
    def __init__(self, limit_bytes: int):
        self.limit_bytes = limit_bytes


class RequestSizeLimiterMiddleware:
    """
    ASGI middleware enforcing body size ceilings before downstream parsing and disk spooling.
    """
    def __init__(
        self,
        app,
        max_upload_bytes: int = MAX_AUDIO_SIZE_BYTES + 65536,  # 10 MB + 64 KB margin
        max_default_bytes: int = 1024 * 1024,                  # 1 MB for non-upload endpoints
    ):
        self.app = app
        self.max_upload_bytes = max_upload_bytes
        self.max_default_bytes = max_default_bytes

    def _get_max_bytes_for_path(self, path: str) -> int:
        clean_path = path.rstrip("/")
        if clean_path in {"/verify", "/identify"}:
            return self.max_upload_bytes
        return self.max_default_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        max_bytes = self._get_max_bytes_for_path(path)

        # 1. Fast Pre-check: Inspect Content-Length header if present
        headers = Headers(raw=scope.get("headers", []))
        content_length_str = headers.get("content-length")
        if content_length_str:
            try:
                declared_length = int(content_length_str.strip())
                if declared_length > max_bytes:
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "detail": f"Payload too large. Declared Content-Length ({declared_length} bytes) exceeds limit of {max_bytes} bytes."
                        },
                    )
                    return await response(scope, receive, send)
            except ValueError:
                pass  # Malformed Content-Length; fallback to streaming inspection

        # 2. Raw Stream Limiter: Wrap ASGI receive to count incoming chunks on-the-fly
        received_bytes = 0
        response_started = False

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                received_bytes += len(chunk)
                if received_bytes > max_bytes:
                    raise PayloadTooLargeError(max_bytes)
            return message

        try:
            await self.app(scope, limited_receive, tracking_send)
        except PayloadTooLargeError:
            if not response_started:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"Payload too large. Streaming body size exceeded limit of {max_bytes} bytes."
                    },
                )
                await response(scope, receive, send)
