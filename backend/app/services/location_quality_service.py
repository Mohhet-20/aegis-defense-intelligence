"""Location quality reporting. Read-only --
nothing here mutates a record or "fixes" a bad coordinate; it only
explains what app/geo/validation.py finds and lets an authorized
analyst decide what to do about it (e.g. by editing the source record
through its own existing update path, or by creating a
spatially-associated candidate relationship via
spatial_relationship_service.py if a conflicting second source exists).

Exact vs. sampled counts: `missing_count` (latitude/longitude both
NULL) is always an exact SQL count -- cheap, indexable. Everything else
(invalid range, non-finite, unsupported CRS, uncertainty-unavailable,
stale) requires per-row Python classification via app/geo/validation.py,
so it runs over a BOUNDED sample (MAX_QUALITY_SAMPLE_ROWS per record
type) and the summary says so plainly (`is_approximate`) rather than
claiming a precise total it didn't actually count.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.geo.validation import validate_coordinates
from app.schemas.geospatial import (
    LocationFindingResponse,
    LocationQualityRecordResponse,
    LocationQualitySummaryResponse,
)
from app.services.geo_query_service import RECORD_TYPE_MODELS, resolve_record_types

settings = get_settings()

MAX_QUALITY_SAMPLE_ROWS = 5000


def _title(row, record_type: str) -> str:
    if record_type == "event":
        return row.title
    if record_type == "sensor":
        return f"Sensor: {row.name}"
    if record_type == "observation":
        return f"Observation: {row.observation_type}"
    return f"Asset: {row.name}"


def _missing_count(db: Session, organization_id: str, record_type: str) -> int:
    model = RECORD_TYPE_MODELS[record_type]
    stmt = select(func.count()).where(model.organization_id == organization_id, or_(model.latitude.is_(None), model.longitude.is_(None)))
    return db.scalar(stmt) or 0


def _sample_with_coordinates(db: Session, organization_id: str, record_type: str):
    model = RECORD_TYPE_MODELS[record_type]
    stmt = select(model).where(model.organization_id == organization_id, model.latitude.is_not(None), model.longitude.is_not(None))
    rows = db.execute(stmt.limit(MAX_QUALITY_SAMPLE_ROWS + 1)).scalars().all()
    return list(rows[:MAX_QUALITY_SAMPLE_ROWS]), len(rows) > MAX_QUALITY_SAMPLE_ROWS


def list_quality_issues(
    db: Session, organization_id: str, *,
    record_types: Optional[list[str]] = None,
    only_issues: bool = True,
    limit: int = 200,
) -> list[LocationQualityRecordResponse]:
    """Per-record findings. `only_issues=True` (the default) excludes
    fully-clean records (valid coordinates, uncertainty known, not
    stale) from the list -- this is a review queue, not a dump of every
    record."""
    types = resolve_record_types(record_types)
    out: list[LocationQualityRecordResponse] = []
    now = datetime.now(timezone.utc)
    per_type_limit = max(1, limit // max(1, len(types)))

    for rt in types:
        model = RECORD_TYPE_MODELS[rt]
        missing_stmt = select(model).where(model.organization_id == organization_id, or_(model.latitude.is_(None), model.longitude.is_(None))).limit(per_type_limit)
        for row in db.execute(missing_stmt).scalars().all():
            out.append(LocationQualityRecordResponse(
                record_type=rt, record_id=row.id, title=_title(row, rt),
                latitude=None, longitude=None, coordinate_reference_system=row.coordinate_reference_system,
                location_validation_status=None,
                findings=[LocationFindingResponse(code=f.code, is_error=f.is_error, explanation=f.explanation) for f in validate_coordinates(None, None)],
            ))

        present_stmt = select(model).where(model.organization_id == organization_id, model.latitude.is_not(None), model.longitude.is_not(None)).limit(per_type_limit)
        for row in db.execute(present_stmt).scalars().all():
            findings = validate_coordinates(
                row.latitude, row.longitude, coordinate_reference_system=row.coordinate_reference_system,
                location_uncertainty_m=row.location_uncertainty_m,
                location_source_observed_at=getattr(row, "observed_at", None),
                now=now, stale_after_seconds=settings.GEOSPATIAL_STALE_LOCATION_AFTER_SECONDS,
            )
            codes = [f.code for f in findings]
            is_clean = codes == ["valid"]
            if only_issues and is_clean:
                continue
            status = codes[0] if codes[0] != "valid" else "valid"
            out.append(LocationQualityRecordResponse(
                record_type=rt, record_id=row.id, title=_title(row, rt),
                latitude=row.latitude, longitude=row.longitude, coordinate_reference_system=row.coordinate_reference_system,
                location_validation_status=status,
                findings=[LocationFindingResponse(code=f.code, is_error=f.is_error, explanation=f.explanation) for f in findings],
            ))

    return out[:limit]


def quality_summary(db: Session, organization_id: str, *, record_types: Optional[list[str]] = None) -> LocationQualitySummaryResponse:
    types = resolve_record_types(record_types)
    now = datetime.now(timezone.utc)

    missing_total = 0
    invalid_range_total = 0
    non_finite_total = 0
    unsupported_crs_total = 0
    valid_total = 0
    uncertainty_unavailable_total = 0
    stale_total = 0
    checked_total = 0
    by_type: dict = {}

    for rt in types:
        missing = _missing_count(db, organization_id, rt)
        sample, is_approximate = _sample_with_coordinates(db, organization_id, rt)

        counts = {"missing": missing, "invalid_range": 0, "non_finite": 0, "unsupported_crs": 0, "valid": 0, "uncertainty_unavailable": 0, "stale": 0, "sampled": len(sample), "is_approximate": is_approximate}
        for row in sample:
            findings = validate_coordinates(
                row.latitude, row.longitude, coordinate_reference_system=row.coordinate_reference_system,
                location_uncertainty_m=row.location_uncertainty_m,
                location_source_observed_at=getattr(row, "observed_at", None),
                now=now, stale_after_seconds=settings.GEOSPATIAL_STALE_LOCATION_AFTER_SECONDS,
            )
            codes = {f.code for f in findings}
            if "invalid_range" in codes:
                counts["invalid_range"] += 1
            elif "non_finite" in codes:
                counts["non_finite"] += 1
            elif "unsupported_crs" in codes:
                counts["unsupported_crs"] += 1
            else:
                counts["valid"] += 1
                if "uncertainty_unavailable" in codes:
                    counts["uncertainty_unavailable"] += 1
                if "stale_location_timestamp" in codes:
                    counts["stale"] += 1

        by_type[rt] = counts
        missing_total += counts["missing"]
        invalid_range_total += counts["invalid_range"]
        non_finite_total += counts["non_finite"]
        unsupported_crs_total += counts["unsupported_crs"]
        valid_total += counts["valid"]
        uncertainty_unavailable_total += counts["uncertainty_unavailable"]
        stale_total += counts["stale"]
        checked_total += counts["missing"] + len(sample)

    return LocationQualitySummaryResponse(
        record_types_checked=types,
        total_records_checked=checked_total,
        missing_count=missing_total,
        invalid_range_count=invalid_range_total,
        non_finite_count=non_finite_total,
        unsupported_crs_count=unsupported_crs_total,
        valid_count=valid_total,
        uncertainty_unavailable_count=uncertainty_unavailable_total,
        stale_count=stale_total,
        by_record_type=by_type,
    )
