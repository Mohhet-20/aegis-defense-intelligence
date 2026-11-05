"""Canonical event normalization. Pure functions
that turn a raw record's loosely-typed fields into the canonical
Event schema's typed values, each with a documented, explicit policy --
never a silent guess.

This module makes NO database calls and raises nothing for an
ordinary "this value doesn't normalize cleanly" case; a caller
(validation_service.py, ingestion_service.py) decides what to do with
a value that fails to normalize. The one exception is
`normalize_coordinates`, which raises ValueError for an out-of-range
pair -- a deliberate signal that the caller must turn into a rejection,
mirroring the contract this was extracted from.

See docs/data/CANONICAL_EVENT_SCHEMA.md for the schema this produces.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# Bumped whenever a change here would affect how an already-stored
# event should be interpreted (e.g. a new timestamp policy, a new
# severity mapping). Stored on every Event's provenance so a later
# reprocessing pass can tell which rows used which rules.
SCHEMA_VERSION = "1.0"
NORMALIZATION_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
#
# Policy (documented, not implicit):
#   - A value with explicit timezone/UTC offset information is converted
#     to UTC as given -- "parsed_aware".
#   - A value with NO timezone information (a naive timestamp, or a
#     bare date) is ASSUMED to already be UTC -- "assumed_utc". This
# mirrors the exact behavior shipped with; it is a
#     documented assumption, not a silent one, and the policy actually
#     applied is recorded on the returned NormalizedTimestamp so it can
#     be surfaced in provenance rather than lost.
#   - A value that cannot be parsed at all is reported as invalid
#     (`None`) -- never defaulted to "now" or any other guessed value.


@dataclass(frozen=True)
class NormalizedTimestamp:
    value: Optional[datetime]  # None means "could not be parsed"
    raw: object  # the original, unmodified input
    policy: str  # "parsed_aware" | "assumed_utc" | "unparseable"


def normalize_timestamp(value) -> NormalizedTimestamp:
    if value is None or value == "":
        return NormalizedTimestamp(value=None, raw=value, policy="unparseable")

    if isinstance(value, (int, float)):
        # Epoch seconds are unambiguous -- always UTC by definition.
        try:
            return NormalizedTimestamp(value=datetime.fromtimestamp(value, tz=timezone.utc), raw=value, policy="parsed_aware")
        except (OverflowError, OSError, ValueError):
            return NormalizedTimestamp(value=None, raw=value, policy="unparseable")

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return NormalizedTimestamp(value=None, raw=value, policy="unparseable")

    if dt.tzinfo is None:
        return NormalizedTimestamp(value=dt.replace(tzinfo=timezone.utc), raw=value, policy="assumed_utc")
    return NormalizedTimestamp(value=dt.astimezone(timezone.utc), raw=value, policy="parsed_aware")


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------
#
# Policy: a missing coordinate stays missing -- it is NEVER defaulted to
# (0, 0) or any other placeholder (Section 7 spec,
# preserved unchanged here). An out-of-range pair is invalid and the
# caller must reject/quarantine the record rather than clamp or guess.


def normalize_coordinates(lat, lon) -> tuple[Optional[float], Optional[float]]:
    if lat in (None, "") or lon in (None, ""):
        return None, None
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"coordinate could not be parsed as a number: lat={lat!r}, lon={lon!r}") from exc
    if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lon_f <= 180.0):
        raise ValueError(f"coordinate out of range: lat={lat_f}, lon={lon_f}")
    return lat_f, lon_f


# ---------------------------------------------------------------------------
# Severity -> priority mapping
# ---------------------------------------------------------------------------
#
# source_severity (whatever the source said, verbatim) and priority
# (this platform's own triage value) are stored separately on Event --
# never collapsed into one field. This mapping is the
# DEFAULT, explicit and documented; an unrecognized label is left
# unmapped (priority=None) rather than silently escalated to the
# highest priority -- escalating an unknown label would manufacture
# urgency the source never actually reported.

PRIORITY_LEVELS = ("low", "medium", "high", "critical")

DEFAULT_SEVERITY_TO_PRIORITY: dict[str, str] = {
    "low": "low",
    "minor": "low",
    "info": "low",
    "informational": "low",
    "medium": "medium",
    "moderate": "medium",
    "warning": "medium",
    "high": "high",
    "major": "high",
    "severe": "high",
    "critical": "critical",
    "emergency": "critical",
    "catastrophic": "critical",
}


def map_severity_to_priority(source_severity: Optional[str], mapping: Optional[dict[str, str]] = None) -> tuple[Optional[str], bool]:
    """Returns (priority_or_none, was_recognized). A None/blank input is
    recognized-but-absent (no warning warranted); a non-blank value not
    found in the mapping is unrecognized (caller should warn, never
    escalate)."""
    if source_severity in (None, ""):
        return None, True
    mapping = mapping or DEFAULT_SEVERITY_TO_PRIORITY
    key = str(source_severity).strip().lower()
    if key in mapping:
        return mapping[key], True
    return None, False


# ---------------------------------------------------------------------------
# Event type mapping
# ---------------------------------------------------------------------------
#
# Policy: event_type is always preserved verbatim (never discarded).
# This platform recognizes a documented set of "known" types for
# analytics/filtering purposes, but an unrecognized-but-syntactically-
# valid type is NOT rejected and does NOT lose the source's original
# value -- it is simply flagged as not-yet-mapped so an analyst can
# extend the taxonomy later.

KNOWN_EVENT_TYPES = (
    "perimeter_motion",
    "unidentified_vehicle",
    "access_attempt",
    "sensor_offline",
    "anomalous_pattern",
    "intrusion",
    "equipment_malfunction",
    "personnel_movement",
    "communications_intercept",
    "other",
)


def classify_event_type(event_type: str) -> bool:
    """True if event_type is in the known taxonomy. False does not mean
    invalid -- only "not yet in the known list," which is not an error."""
    return str(event_type).strip().lower() in KNOWN_EVENT_TYPES


# ---------------------------------------------------------------------------
# Content fingerprint (fallback dedup key)
# ---------------------------------------------------------------------------


def content_fingerprint(record: dict) -> str:
    """A deterministic fallback identifier for sources that never supply
    a stable external_id -- a hash of the record's own content, never a
    fabricated identifier. Documented versioned algorithm: sha256 over
    the record's keys sorted, JSON-encoded with str() fallback for
    non-serializable values, truncated to 32 hex characters. Changing
    this algorithm is a breaking change for existing fingerprints and
    must bump NORMALIZATION_VERSION."""
    canonical = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
