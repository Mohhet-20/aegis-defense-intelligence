"""Aggregated geospatial overview (Section 6 "Overview" tab).
Composes already-existing services into one summary object -- this
module implements NO new counting or validation logic of its own; it
only reads what geo_query_service, location_quality_service,
relationship_service, and conflict_service already compute. Keeping
this thin is deliberate: a bug in "what counts as valid" should only
ever need fixing in app/geo/validation.py, never here too.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.conflict import Conflict
from app.models.evidence_relationship import EvidenceRelationship
from app.schemas.geospatial import GeospatialOverviewResponse
from app.services import location_quality_service
from app.services.geo_query_service import RECORD_TYPE_MODELS, SELECTABLE_TIMESTAMP_TYPES, fetch_record_type, resolve_record_types

# How many "recent" located records the Overview tab shows -- a small,
# fixed preview, never the full dataset (that's what the Interactive
# Map Explorer / Timeline Explorer are for).
_RECENT_RECORDS_LIMIT = 20

# How many rows of each record type are fetched to compute the
# overview's totals/recent list -- bounded, same discipline as every
# other aggregation in this subsystem.
_OVERVIEW_SAMPLE_LIMIT = 500

# A conflict's `conflicting_fields` is a JSON list of {"field": ...}
# entries (app/services/conflict_service.py's `_spatial_conflict`) --
# this is the one field name that means "these two events' recorded
# locations disagree." Counting unresolved conflicts over a bounded
# sample, not the whole table, mirrors every other bounded count here.
_LOCATION_CONFLICT_FIELD = "location"
_MAX_CONFLICT_SAMPLE_ROWS = 5000


def _located_counts(db: Session, organization_id: str, types: list[str]):
    by_type: dict[str, int] = {}
    total = 0
    excluded_total = 0
    recent = []
    for rt in types:
        result = fetch_record_type(db, organization_id, rt, limit=_OVERVIEW_SAMPLE_LIMIT)
        by_type[rt] = len(result.items)
        total += len(result.items)
        excluded_total += result.excluded_unusable
        recent.extend(result.items)
    recent.sort(key=lambda r: r.timestamp, reverse=True)
    return by_type, total, excluded_total, recent[:_RECENT_RECORDS_LIMIT]


def _temporal_coverage(db: Session, organization_id: str, types: list[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    """Earliest/latest value of each record type's DEFAULT timestamp
    column (never collapses observed_at/ingested_at/
    registered_at into one generic "date" -- this picks the single
    most meaningful one per type, the same default fetch_record_type
    itself falls back to)."""
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None
    for rt in types:
        model = RECORD_TYPE_MODELS[rt]
        default_timestamp_type = SELECTABLE_TIMESTAMP_TYPES[rt][0]
        column = model.created_at if default_timestamp_type == "registered_at" else getattr(model, default_timestamp_type)
        row_min, row_max = db.execute(
            select(func.min(column), func.max(column)).where(model.organization_id == organization_id)
        ).one()
        if row_min is not None and (earliest is None or row_min < earliest):
            earliest = row_min
        if row_max is not None and (latest is None or row_max > latest):
            latest = row_max
    return earliest, latest


def _unreviewed_spatial_relationship_count(db: Session, organization_id: str) -> int:
    stmt = select(func.count()).where(
        EvidenceRelationship.organization_id == organization_id,
        EvidenceRelationship.relationship_type == "spatially_associated",
        EvidenceRelationship.review_status == "candidate",
    )
    return db.scalar(stmt) or 0


def _unreviewed_location_conflict_count(db: Session, organization_id: str) -> int:
    stmt = select(Conflict).where(
        Conflict.organization_id == organization_id, Conflict.review_status == "unresolved",
    ).limit(_MAX_CONFLICT_SAMPLE_ROWS)
    rows = db.execute(stmt).scalars().all()
    return sum(1 for c in rows if any(f.get("field") == _LOCATION_CONFLICT_FIELD for f in (c.conflicting_fields or [])))


def build_overview(db: Session, organization_id: str, *, record_types: Optional[list[str]] = None) -> GeospatialOverviewResponse:
    types = resolve_record_types(record_types)
    by_type, total, excluded_total, recent = _located_counts(db, organization_id, types)
    earliest, latest = _temporal_coverage(db, organization_id, types)
    quality_summary = location_quality_service.quality_summary(db, organization_id, record_types=types)

    return GeospatialOverviewResponse(
        located_records_total=total,
        located_records_by_type=by_type,
        missing_or_invalid_location_total=excluded_total,
        recent_located_records=recent,
        spatial_relationship_candidates_unreviewed=_unreviewed_spatial_relationship_count(db, organization_id),
        location_conflicts_unreviewed=_unreviewed_location_conflict_count(db, organization_id),
        temporal_coverage_earliest=earliest,
        temporal_coverage_latest=latest,
        data_quality_summary=quality_summary,
    )
