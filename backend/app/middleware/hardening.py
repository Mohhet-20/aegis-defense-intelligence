"""Request-size limiting and security headers.

Pure ASGI middleware (not BaseHTTPMiddleware) so a body can be rejected
while it streams, without buffering it first.
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from app.core.config import get_settings

def _body_limit(path: str) -> int:
    """Route-specific ceiling. Media upload gets the large ceiling; the two
    file-ingestion endpoints are capped just above MAX_UPLOAD_BYTES (multipart
    framing overhead); everything else uses the small JSON ceiling."""
    s = get_settings()
    p = path.rstrip("/")
    if p.endswith("/api/v1/media"):
        return s.MAX_UPLOAD_REQUEST_BYTES
    if p.endswith("/api/v1/ingestion/jobs") or p.endswith("/api/v1/sensor-ingestion/batches"):
        return s.MAX_UPLOAD_BYTES + 256 * 1024
    return s.MAX_REQUEST_BODY_BYTES


class SizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive: Callable[[], Awaitable[dict]], send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        limit = _body_limit(scope["path"])
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    return await self._reject(send, limit)
            except ValueError:
                return await self._reject(send, limit, status=400, detail="Invalid Content-Length")
        received = 0
        too_big = False
        responded = False

        async def limited_receive():
            nonlocal received, too_big
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_big = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def guarded_send(message):
            nonlocal responded
            if too_big and not responded:
                responded = True
                if message["type"] == "http.response.start":
                    return await self._reject(send, limit)
            if responded and too_big:
                return  # swallow the handler's own response; ours was sent
            await send(message)

        await self.app(scope, limited_receive, guarded_send)

    @staticmethod
    async def _reject(send, limit: int, status: int = 413, detail: str | None = None):
        body = json.dumps({"detail": detail or f"Request body exceeds the {limit}-byte limit"}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def _allows_framing(headers) -> bool:
    for k, v in headers:
        if k.lower() == b"content-security-policy":
            value = v.decode("latin-1")
            return "frame-ancestors" in value and "frame-ancestors 'none'" not in value
    return False


class SecurityHeadersMiddleware:
    _HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
        (b"cross-origin-resource-policy", b"same-origin"),
        (b"cache-control", b"no-store"),
    ]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self._HEADERS if k not in existing]
                if _allows_framing(message.get("headers", [])):
                    # The page's own CSP names who may frame it (FRONTEND_FRAME_ANCESTORS);
                    # X-Frame-Options: DENY would override that in older browsers.
                    extra = [(k, v) for k, v in extra if k != b"x-frame-options"]
                path = scope.get("path", "")
                if path.startswith("/api/docs") or path.startswith("/api/openapi"):
                    extra = [(k, v) for k, v in extra if k not in (b"cache-control",)]
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        await self.app(scope, receive, send_wrapper)
