"""The data-quality/validation engine. Produces a
structured ValidationOutcome for a single raw record -- never a single
opaque "truth probability" score. Fatal errors (the record cannot be
stored as a valid event) are kept strictly separate from warnings (the
record is stored, but something about it is worth an analyst's
attention).

This module makes no database calls and never mutates the record it is
given; ingestion_service.py decides what to do with the outcome
(accept / reject / quarantine), and quality_service.py aggregates many
outcomes into summaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.services import normalization_service as norm

RULE_VERSION = "1.0"

REQUIRED_FIELDS = ("event_type", "title", "observed_at")

# Fields whose values are rejected outright if oversized -- a bound
# against resource exhaustion from a single pathological record, not a
# meaningful business rule.
MAX_FIELD_LENGTH = 8000
MAX_ATTRIBUTE_COUNT = 200

# --- Error codes (fatal -- the record is rejected/quarantined) ------------
ERR_MISSING_REQUIRED_FIELD = "missing_required_field"
ERR_INVALID_TIMESTAMP = "invalid_timestamp"
ERR_INVALID_COORDINATE = "invalid_coordinate"
ERR_OVERSIZED_FIELD = "oversized_field"
ERR_TOO_MANY_ATTRIBUTES = "too_many_attributes"
ERR_MALFORMED_RECORD = "malformed_record"

# --- Warning codes (non-fatal -- the record is still accepted) -----------
WARN_UNKNOWN_SEVERITY_LABEL = "unknown_severity_label"
WARN_UNKNOWN_EVENT_TYPE = "unknown_event_type"
WARN_MISSING_EXTERNAL_ID = "missing_external_id"
WARN_AMBIGUOUS_TIMESTAMP_ASSUMED_UTC = "ambiguous_timestamp_assumed_utc"
WARN_MISSING_COORDINATES = "missing_coordinates"
WARN_LIKELY_DUPLICATE_CONTENT = "likely_duplicate_content"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    field: Optional[str] = None


@dataclass
class ValidationOutcome:
    status: str  # "valid" | "invalid"
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    rule_version: str = RULE_VERSION
    # Normalized values, populated when the corresponding check passed
    # well enough to produce a usable value (even if other fields
    # failed) -- so a caller never has to re-run normalization itself.
    normalized_observed_at = None
    normalized_latitude: Optional[float] = None
    normalized_longitude: Optional[float] = None
    normalized_priority: Optional[str] = None
    timestamp_policy: Optional[str] = None

    @property
    def affected_fields(self) -> list[str]:
        fields = {issue.field for issue in (*self.errors, *self.warnings) if issue.field}
        return sorted(fields)

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"


def validate_record(record: dict, *, required_fields: tuple[str, ...] = REQUIRED_FIELDS) -> ValidationOutcome:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    if not isinstance(record, dict):
        errors.append(ValidationIssue(ERR_MALFORMED_RECORD, "record is not an object/row of fields"))
        return ValidationOutcome(status="invalid", errors=errors, warnings=warnings)

    # --- required fields ---------------------------------------------------
    present = {k for k, v in record.items() if v not in (None, "")}
    missing = [f for f in required_fields if f not in present]
    for f in missing:
        errors.append(ValidationIssue(ERR_MISSING_REQUIRED_FIELD, f"required field '{f}' is missing or empty", field=f))

    # --- oversized fields / payload shape ----------------------------------
    if len(record) > MAX_ATTRIBUTE_COUNT:
        errors.append(ValidationIssue(ERR_TOO_MANY_ATTRIBUTES, f"record has {len(record)} fields, exceeding the limit of {MAX_ATTRIBUTE_COUNT}"))
    for k, v in record.items():
        if isinstance(v, str) and len(v) > MAX_FIELD_LENGTH:
            errors.append(ValidationIssue(ERR_OVERSIZED_FIELD, f"field '{k}' exceeds {MAX_FIELD_LENGTH} characters", field=k))

    # --- timestamp -----------------------------------------------------------
    normalized_ts = norm.normalize_timestamp(record.get("observed_at"))
    timestamp_policy = normalized_ts.policy
    normalized_observed_at = normalized_ts.value
    if normalized_ts.value is None:
        if "observed_at" not in missing:  # don't double-report an already-missing field
            errors.append(ValidationIssue(ERR_INVALID_TIMESTAMP, f"observed_at value {record.get('observed_at')!r} could not be parsed as a timestamp", field="observed_at"))
    elif normalized_ts.policy == "assumed_utc":
        warnings.append(ValidationIssue(WARN_AMBIGUOUS_TIMESTAMP_ASSUMED_UTC, "observed_at had no timezone information -- assumed to already be UTC per documented policy", field="observed_at"))

    # --- coordinates -----------------------------------------------------
    normalized_lat = normalized_lon = None
    try:
        normalized_lat, normalized_lon = norm.normalize_coordinates(record.get("latitude"), record.get("longitude"))
        if normalized_lat is None:
            # Only warn when the record looks like it intended to supply
            # a location (one of the two fields was present) -- a
            # record with neither field at all is simply location-less.
            if record.get("latitude") not in (None, "") or record.get("longitude") not in (None, ""):
                warnings.append(ValidationIssue(WARN_MISSING_COORDINATES, "latitude/longitude incomplete -- stored as missing rather than guessed", field="latitude"))
    except ValueError as exc:
        errors.append(ValidationIssue(ERR_INVALID_COORDINATE, str(exc), field="latitude"))

    # --- severity ----------------------------------------------------------
    normalized_priority, recognized = norm.map_severity_to_priority(record.get("severity"))
    if not recognized:
        warnings.append(ValidationIssue(WARN_UNKNOWN_SEVERITY_LABEL, f"severity value '{record.get('severity')}' is not in the known mapping -- left unmapped rather than escalated", field="severity"))

    # --- event type ----------------------------------------------------------
    event_type = record.get("event_type")
    if event_type and "event_type" not in missing and not norm.classify_event_type(str(event_type)):
        warnings.append(ValidationIssue(WARN_UNKNOWN_EVENT_TYPE, f"event_type '{event_type}' is not in the known taxonomy -- preserved as-is", field="event_type"))

    # --- identifier quality ------------------------------------------------
    if not record.get("external_id"):
        warnings.append(ValidationIssue(WARN_MISSING_EXTERNAL_ID, "no external_id supplied -- duplicate detection will fall back to a content fingerprint", field="external_id"))

    status = "invalid" if errors else "valid"
    outcome = ValidationOutcome(
        status=status,
        errors=errors,
        warnings=warnings,
        normalized_latitude=normalized_lat,
        normalized_longitude=normalized_lon,
        normalized_priority=normalized_priority,
        timestamp_policy=timestamp_policy,
    )
    outcome.normalized_observed_at = normalized_observed_at
    return outcome
