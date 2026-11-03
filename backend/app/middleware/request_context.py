"""Request-correlation middleware (Section 8 / Section 19). Every
request gets an X-Request-ID -- generated if the caller doesn't supply
one -- echoed back in the response header and attached to
request.state so every log line and audit record for this request can
be tied together."""
from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging_config import request_id_var
from app.core.obs_metrics import registry, status_class

logger = logging.getLogger("aegis.request")
_SAFE_ID = re.compile(r"[A-Za-z0-9._\-]{8,64}")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        # Client-supplied ids are only honoured if they are short and use a
        # safe alphabet -- otherwise log/audit injection via CR/LF or huge values.
        request_id = supplied if _SAFE_ID.fullmatch(supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        start = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            duration = time.monotonic() - start
            # Route TEMPLATE (e.g. /api/v1/mlops/models/{model_id}), never the raw path:
            # raw paths contain ids and would be an unbounded label.
            route = request.scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            registry.inc("http_requests_total", {"method": request.method, "route": template, "status_class": status_class(status_code)})
            registry.observe("http_request_duration_seconds", {"method": request.method, "route": template}, duration)
            request_id_var.reset(token)
        duration_ms = duration * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "operation": "http_request",
                "outcome": "success" if response.status_code < 400 else ("client_error" if response.status_code < 500 else "server_error"),
            },
        )
        return response
