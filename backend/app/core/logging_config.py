"""Logging setup (extends the original text logger).

Default behaviour is unchanged (``LOG_FORMAT=text``). Setting
``LOG_FORMAT=json`` switches to one JSON object per line with standard fields:
timestamp, severity, subsystem (logger name), environment, request_id, job_id,
operation, duration_ms, outcome, error_category.

In BOTH formats a redaction filter removes secrets from the message and from
every structured field before anything is written: bearer tokens, JWT-shaped
strings, ``password=...``/``token=...``/``api_key=...`` pairs, and any field
whose NAME looks sensitive. Request bodies, uploaded media and prompts are
never logged by the application; only fields explicitly passed via ``extra=``
are emitted.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("aegis_request_id", default=None)
job_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("aegis_job_id", default=None)

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(r"(pass(word|wd)?|secret|token|authorization|api[_-]?key|cookie|private[_-]?key|credential|signature)", re.I)
_PATTERNS = [
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}"), "Bearer " + REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"), REDACTED),
    (re.compile(r"(?i)\b(authorization|cookie|set-cookie)\s*[:=]\s*[^\r\n]+"), r"\1=" + REDACTED),
    (re.compile(r"""(?i)\b(pass(?:word|wd)?|secret|token|api[_-]?key|private[_-]?key|access[_-]?key)(["']?\s*[:=]\s*["']?)[^\s,;&"']+"""), r"\1\2" + REDACTED),
]
MAX_FIELD_CHARS = 500

_STANDARD_ATTRS = set(logging.LogRecord("x", 0, "x", 0, "x", (), None).__dict__) | {"message", "asctime", "taskName"}
_JSON_FIELDS = ("request_id", "job_id", "operation", "duration_ms", "outcome", "error_category", "method", "path", "status_code")


def redact_text(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_value(key: str, value: Any, depth: int = 0) -> Any:
    if _SENSITIVE_KEY.search(key or ""):
        return REDACTED
    if isinstance(value, str):
        v = redact_text(value)
        return v if len(v) <= MAX_FIELD_CHARS else v[:MAX_FIELD_CHARS] + "...[truncated]"
    if isinstance(value, dict) and depth < 3:
        return {str(k): redact_value(str(k), v, depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)) and depth < 3:
        return [redact_value(key, v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_text(str(value))[:MAX_FIELD_CHARS]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 -- a malformed log call must not break the request
            message = str(record.msg)
        record.msg = redact_text(message)
        record.args = None
        for key in list(record.__dict__):
            if key not in _STANDARD_ATTRS and key != "msg":
                record.__dict__[key] = redact_value(key, record.__dict__[key])
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, environment: str = "") -> None:
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "severity": record.levelname,
            "subsystem": record.name,
            "environment": self.environment,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "job_id": getattr(record, "job_id", None) or job_id_var.get(),
        }
        for field in _JSON_FIELDS:
            if field in ("request_id", "job_id"):
                continue
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS and k not in payload and k not in _JSON_FIELDS}
        if extras:
            payload["extra"] = extras
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
            # Traceback text is redacted like everything else; it belongs in the protected log sink only.
            payload["exc_trace"] = redact_text(self.formatException(record.exc_info))[:4000]
        return json.dumps(payload, default=str, separators=(",", ":"))


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        rid = request_id_var.get()
        return text if not rid or "request_id" in text else f"{text} request_id={rid}"


def configure_logging(level: str = "INFO", fmt: Optional[str] = None) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    chosen = (fmt or settings.LOG_FORMAT or "text").lower()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    if chosen == "json":
        handler.setFormatter(JsonFormatter(environment=settings.ENVIRONMENT))
    else:
        handler.setFormatter(_TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
