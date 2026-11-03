"""Shared bounded-input validation for MLOps payloads."""
from __future__ import annotations

import json
import math
from typing import Any

from app.core.errors import MlopsValidationError

MAX_DEPTH = 5
MAX_KEYS = 100


def _walk(value: Any, field: str, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise MlopsValidationError(f"{field} is nested too deeply (max {MAX_DEPTH} levels)")
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MlopsValidationError(f"{field} contains a non-finite number (NaN/Infinity)")
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 1000:
            raise MlopsValidationError(f"{field} contains a list longer than 1000 items")
        for v in value:
            _walk(v, field, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_KEYS:
            raise MlopsValidationError(f"{field} has more than {MAX_KEYS} keys")
        for k, v in value.items():
            if not isinstance(k, str) or not (1 <= len(k) <= 100):
                raise MlopsValidationError(f"{field} keys must be strings of 1-100 characters")
            _walk(v, field, depth + 1)
        return
    raise MlopsValidationError(f"{field} contains an unsupported value type")


def validate_json_blob(value: Any, *, field: str, max_bytes: int) -> dict:
    """Metadata must be a JSON object: finite numbers only, bounded depth, key
    count and encoded size. Returns the value unchanged when valid."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MlopsValidationError(f"{field} must be a JSON object")
    _walk(value, field, 1)
    size = len(json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    if size > max_bytes:
        raise MlopsValidationError(f"{field} is too large ({size} bytes; limit {max_bytes})")
    return value


def bounded_evidence(value: Any, max_bytes: int = 8192) -> dict:
    """Best-effort bound for system-generated evidence: oversized evidence is
    replaced by a marker rather than failing the operation that raised it."""
    try:
        size = len(json.dumps(value, allow_nan=False, default=str, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return {"truncated": True, "reason": "evidence could not be serialised"}
    if size > max_bytes:
        return {"truncated": True, "reason": f"evidence exceeded {max_bytes} bytes"}
    return value if isinstance(value, dict) else {"value": value}
