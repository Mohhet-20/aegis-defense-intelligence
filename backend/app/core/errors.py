"""Consistent error classification.

``classify_exception`` maps any exception to a stable category plus a message
that is safe to show a client or store on a run record. Stack traces and raw
exception text never leave the process through this function: only exceptions
that are known to carry curated messages (validation / our own domain errors)
have their text passed through, and even then it is scrubbed of filesystem
paths and secret-shaped values and truncated.
"""
from __future__ import annotations

import re
from typing import Optional

from app.core.logging_config import redact_text

CATEGORIES = (
    "validation", "authorization", "missing_artifact", "unsupported_configuration",
    "evaluation_failure", "resource_limit", "database", "storage", "interrupted", "internal",
)

_PATH = re.compile(r"(?:[A-Za-z]:\\|/)(?:[\w.\-~]+[\\/])+[\w.\-~]*")
MAX_MESSAGE = 300


class MlopsError(Exception):
    """Base for domain errors whose message is curated and safe to expose."""

    category = "internal"
    http_status = 500


class MlopsValidationError(MlopsError):
    category = "validation"
    http_status = 422


class MlopsNotFound(MlopsError):
    category = "validation"
    http_status = 404


class MlopsConflict(MlopsError):
    category = "validation"
    http_status = 409


class MlopsForbidden(MlopsError):
    category = "forbidden"
    http_status = 403


class ArtifactUnavailable(MlopsError):
    category = "missing_artifact"
    http_status = 409


class UnsupportedConfiguration(MlopsError):
    category = "unsupported_configuration"
    http_status = 422


class ResourceLimitExceeded(MlopsError):
    category = "resource_limit"
    http_status = 413


class IncompatibleComparison(MlopsError):
    category = "validation"
    http_status = 422

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def scrub(text: str, limit: int = MAX_MESSAGE) -> str:
    cleaned = _PATH.sub("<path>", redact_text(text or ""))
    cleaned = " ".join(cleaned.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Returns (category, client_safe_message)."""
    from sqlalchemy.exc import SQLAlchemyError

    if isinstance(exc, MlopsError):
        return exc.category, scrub(str(exc))
    try:
        from app.analytics.metrics import MetricInputError
        from app.services.classification_evaluation_service import EvaluationInputError

        if isinstance(exc, (MetricInputError, EvaluationInputError)):
            return "validation", scrub(str(exc))
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.cv.adapters.registry import UnsupportedRuntimeError

        if isinstance(exc, UnsupportedRuntimeError):
            return "unsupported_configuration", "The model adapter is not available in this runtime."
    except Exception:  # noqa: BLE001
        pass
    if isinstance(exc, PermissionError):
        return "authorization", "The operation is not permitted."
    if isinstance(exc, FileNotFoundError):
        return "missing_artifact", "A required file or artifact is missing."
    if isinstance(exc, (TimeoutError, MemoryError)):
        return "resource_limit", "A resource limit was reached while running the operation."
    if isinstance(exc, SQLAlchemyError):
        return "database", "A database error occurred."
    if isinstance(exc, OSError):
        return "storage", "A storage error occurred."
    if isinstance(exc, ValueError):
        return "validation", "The supplied input was not valid."
    return "internal", "An unexpected internal error occurred."


def public_error(category: str, message: str, request_id: Optional[str] = None) -> dict:
    body = {"detail": message, "error_category": category}
    if request_id:
        body["request_id"] = request_id
    return body
