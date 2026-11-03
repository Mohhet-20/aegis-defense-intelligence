"""Location validation and quality findings.

Pure functions only -- nothing here touches the database. A "finding"
describes the state of a SINGLE location-bearing record's coordinates;
app/services/location_quality_service.py is what runs this over real
rows and aggregates the results.

Section 10's own list of potential findings is intentionally broader
than what this project can actually detect today (e.g. "conflicting
source coordinates" needs two independent sources for the SAME
real-world thing, which is a cross-record concern handled by
app/services/spatial_relationship_service.py, not a single-record
finding). What IS implemented here is honestly documented below rather
than silently narrowed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.models.mixins import (
    SUPPORTED_COORDINATE_REFERENCE_SYSTEMS,
)
from app.services.timeutil import ensure_utc

# Finding codes this module actually produces. Each maps 1:1 to
# something app/models/mixins.py's LOCATION_VALIDATION_STATUSES can
# hold, PLUS "missing_coordinates" -- which is never written to a row
# (there is nothing to write it to: latitude is simply None) but is
# still a real finding a quality report needs to surface.
FINDING_MISSING = "missing_coordinates"
FINDING_INVALID_RANGE = "invalid_range"
FINDING_NON_FINITE = "non_finite"
FINDING_UNSUPPORTED_CRS = "unsupported_crs"
FINDING_STALE_SOURCE_TIMESTAMP = "stale_location_timestamp"
FINDING_UNCERTAINTY_UNAVAILABLE = "uncertainty_unavailable"
FINDING_VALID = "valid"

_EXPLANATIONS = {
    FINDING_MISSING: "no latitude/longitude is recorded for this record -- this is an absence of data, not a location of (0, 0), and is never plotted on the map or included in a spatial query result.",
    FINDING_INVALID_RANGE: "the recorded latitude or longitude is outside the valid WGS84 range (-90..90 / -180..180) -- this is a data-entry or source error, not a usable location.",
    FINDING_NON_FINITE: "the recorded latitude or longitude is NaN or infinite -- rejected outright, never treated as a real coordinate.",
    FINDING_UNSUPPORTED_CRS: "the record's coordinate_reference_system is not one this project knows how to interpret as WGS84 -- the raw latitude/longitude values are preserved but NOT plotted or used in a distance calculation until a documented transformation exists (never silently interpret projected coordinates as latitude/longitude).",
    FINDING_STALE_SOURCE_TIMESTAMP: "this location's own source timestamp is older than the configured staleness threshold -- the coordinate may no longer reflect where the record actually is/was.",
    FINDING_UNCERTAINTY_UNAVAILABLE: "no positional uncertainty was ever supplied for this location -- absence is read as UNKNOWN uncertainty, never as zero uncertainty.",
    FINDING_VALID: "coordinates are present, finite, in range, and in a supported coordinate reference system.",
}


@dataclass(frozen=True)
class LocationFinding:
    code: str
    is_error: bool  # True = the coordinates are unusable; False = informational
    explanation: str


def _is_finite(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(value)


def validate_coordinates(
    latitude: Optional[float],
    longitude: Optional[float],
    *,
    coordinate_reference_system: str = "WGS84",
    location_uncertainty_m: Optional[float] = None,
    location_source_observed_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    stale_after_seconds: Optional[float] = None,
) -> list[LocationFinding]:
    """Classify one location's current state. Returns every applicable
    finding (not just the first) -- e.g. a present-but-stale, present-
    but-uncertainty-unknown location returns both informational
    findings alongside FINDING_VALID, since neither disqualifies the
    coordinate from being usable, unlike FINDING_INVALID_RANGE/
    FINDING_NON_FINITE/FINDING_UNSUPPORTED_CRS which are mutually
    exclusive with FINDING_VALID and returned alone."""
    if latitude is None or longitude is None:
        return [LocationFinding(FINDING_MISSING, is_error=False, explanation=_EXPLANATIONS[FINDING_MISSING])]

    if not _is_finite(latitude) or not _is_finite(longitude):
        return [LocationFinding(FINDING_NON_FINITE, is_error=True, explanation=_EXPLANATIONS[FINDING_NON_FINITE])]

    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        return [LocationFinding(FINDING_INVALID_RANGE, is_error=True, explanation=_EXPLANATIONS[FINDING_INVALID_RANGE])]

    if coordinate_reference_system not in SUPPORTED_COORDINATE_REFERENCE_SYSTEMS:
        return [LocationFinding(FINDING_UNSUPPORTED_CRS, is_error=True, explanation=_EXPLANATIONS[FINDING_UNSUPPORTED_CRS])]

    findings = [LocationFinding(FINDING_VALID, is_error=False, explanation=_EXPLANATIONS[FINDING_VALID])]

    if location_uncertainty_m is None:
        findings.append(LocationFinding(FINDING_UNCERTAINTY_UNAVAILABLE, is_error=False, explanation=_EXPLANATIONS[FINDING_UNCERTAINTY_UNAVAILABLE]))

    if location_source_observed_at is not None and now is not None and stale_after_seconds is not None:
        age_seconds = (ensure_utc(now) - ensure_utc(location_source_observed_at)).total_seconds()
        if age_seconds > stale_after_seconds:
            findings.append(LocationFinding(FINDING_STALE_SOURCE_TIMESTAMP, is_error=False, explanation=_EXPLANATIONS[FINDING_STALE_SOURCE_TIMESTAMP]))

    return findings


def classify_validation_status(latitude: Optional[float], longitude: Optional[float], *, coordinate_reference_system: str = "WGS84") -> Optional[str]:
    """The single status string written to a row's
    `location_validation_status` column (never written at all when
    latitude is None -- see FINDING_MISSING's docstring above). Returns
    one of LOCATION_VALIDATION_STATUSES, or None for a missing
    coordinate."""
    if latitude is None or longitude is None:
        return None
    if not _is_finite(latitude) or not _is_finite(longitude):
        return "non_finite"
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        return "invalid_range"
    if coordinate_reference_system not in SUPPORTED_COORDINATE_REFERENCE_SYSTEMS:
        return "unsupported_crs"
    return "valid"


def is_usable_for_mapping(latitude: Optional[float], longitude: Optional[float], *, coordinate_reference_system: str = "WGS84") -> bool:
    """True only for a location that should actually be plotted on the
    map or included in a spatial query result -- Section 7: a record
    with an unusable location goes in a separate missing/invalid list,
    never at an arbitrary map position."""
    return classify_validation_status(latitude, longitude, coordinate_reference_system=coordinate_reference_system) == "valid"
