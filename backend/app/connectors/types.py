"""Typed contracts shared by every connector (Section 4 of the Phase 2
spec). A connector's job is narrow: produce `RawRecord`s (or report why
it couldn't) from whatever it's configured to read. It never touches
the database, never normalizes, never deduplicates -- that happens in
`app/services/ingestion_service.py` and `normalization_service.py`,
the same engine regardless of which connector produced the records.
This is what lets a future sensor/CV/edge adapter plug in later without
rewriting the ingestion engine (see docs/architecture/CONNECTOR_ARCHITECTURE.md).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ErrorCategory(str, enum.Enum):
    CONFIGURATION = "configuration"
    VALIDATION = "validation"
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    UNSUPPORTED_CONTENT = "unsupported_content"
    SIZE_LIMIT = "size_limit"
    UNSAFE_DESTINATION = "unsafe_destination"
    UNKNOWN = "unknown"


# Whether retrying the SAME request is expected to help. A 4xx/validation
# error is never retryable; a timeout or connection error might be.
RETRYABLE_CATEGORIES = {ErrorCategory.CONNECTION, ErrorCategory.TIMEOUT}


@dataclass(frozen=True)
class ConnectorError:
    category: ErrorCategory
    message: str

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE_CATEGORIES


@dataclass(frozen=True)
class RawRecord:
    """One record as the connector received it -- before normalization.
    `payload` is the record exactly as read (a dict for JSON/HTTP
    sources, a row-as-dict for CSV). `external_id`, if the connector
    can determine one without guessing, is passed through so dedup
    doesn't have to re-derive it."""

    payload: dict
    external_id: Optional[str] = None
    source_observed_at_raw: Optional[str] = None  # unparsed -- normalization owns parsing


@dataclass
class ConnectorResult:
    connector_type: str
    connector_version: str
    records: list[RawRecord] = field(default_factory=list)
    errors: list[ConnectorError] = field(default_factory=list)
    cursor: Optional[str] = None
    has_more: bool = False
    fetched_at: datetime = field(default_factory=_utcnow)


class ConnectorConfigError(ValueError):
    """Raised by validate_config()/fetch() for a configuration problem
    -- never for a transient one. Carries an ErrorCategory so callers
    don't have to guess."""

    def __init__(self, message: str, category: ErrorCategory = ErrorCategory.CONFIGURATION):
        super().__init__(message)
        self.category = category
