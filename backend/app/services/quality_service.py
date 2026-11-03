"""Data-quality summaries. Every number here is
computed ON THE FLY from stored RawRecord / IngestionJob rows via
aggregate queries -- there is deliberately NO separate "quality
summary" table (a conscious simplicity decision: a summary is always
reproducible from the records it describes, so there is never a stale
cache and never a second source of truth to keep in sync with it).

Every summary states its own denominator and time window explicitly --
never an unlabeled percentage -- per Section 13's "no single opaque
truth-probability score" rule. These are DATA-QUALITY metrics (did the
record parse, was it well-formed) -- never a claim about whether the
underlying event is true, see docs/analytics/SOURCE_RELIABILITY.md for
that distinction.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ingestion_job import IngestionJob
from app.models.raw_record import RawRecord

# How many individual raw records to actually inspect when building a
# rejection/warning category breakdown -- bounded so a summary request
# can never force an unbounded table scan of JSON blobs. A caller
# wanting an exact count over a huge window should narrow the time
# window rather than this engine attempting a full scan.
MAX_RECORDS_FOR_CATEGORY_BREAKDOWN = 5000


def _scope(stmt, *, organization_id: str, source_id: Optional[str], since: Optional[datetime], until: Optional[datetime]):
    stmt = stmt.where(RawRecord.organization_id == organization_id)
    if source_id:
        stmt = stmt.where(RawRecord.source_id == source_id)
    if since:
        stmt = stmt.where(RawRecord.received_at >= since)
    if until:
        stmt = stmt.where(RawRecord.received_at <= until)
    return stmt


def summarize_data_quality(
    db: Session,
    organization_id: str,
    *,
    source_id: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> dict:
    """The headline data-quality summary for a source/time window:
    counts, NOT a single score. `total` is the explicit denominator
    every rate below is computed against."""
    base = _scope(select(RawRecord.id), organization_id=organization_id, source_id=source_id, since=since, until=until)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    if total == 0:
        return {
            "total": 0, "valid": 0, "invalid": 0, "duplicate": 0,
            "acceptance_rate": None, "rejection_rate": None, "duplicate_rate": None,
            "rejection_categories": {}, "warning_categories": {},
            "source_id": source_id, "since": since, "until": until,
        }

    valid = db.execute(select(func.count()).select_from(_scope(select(RawRecord.id).where(RawRecord.validation_status == "valid"), organization_id=organization_id, source_id=source_id, since=since, until=until).subquery())).scalar_one()
    invalid = db.execute(select(func.count()).select_from(_scope(select(RawRecord.id).where(RawRecord.validation_status == "invalid"), organization_id=organization_id, source_id=source_id, since=since, until=until).subquery())).scalar_one()
    duplicate = db.execute(select(func.count()).select_from(_scope(select(RawRecord.id).where(RawRecord.is_duplicate.is_(True)), organization_id=organization_id, source_id=source_id, since=since, until=until).subquery())).scalar_one()
    accepted = db.execute(select(func.count()).select_from(_scope(select(RawRecord.id).where(RawRecord.event_id.is_not(None)), organization_id=organization_id, source_id=source_id, since=since, until=until).subquery())).scalar_one()

    rejection_categories, warning_categories = _category_breakdown(db, organization_id=organization_id, source_id=source_id, since=since, until=until)

    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "duplicate": duplicate,
        "accepted": accepted,
        "acceptance_rate": round(accepted / total, 4),
        "rejection_rate": round(invalid / total, 4),
        "duplicate_rate": round(duplicate / total, 4),
        "rejection_categories": rejection_categories,
        "warning_categories": warning_categories,
        "source_id": source_id,
        "since": since,
        "until": until,
    }


def _category_breakdown(db: Session, *, organization_id: str, source_id: Optional[str], since: Optional[datetime], until: Optional[datetime]) -> tuple[dict, dict]:
    """Tallies error/warning CODES (not raw messages) across up to
    MAX_RECORDS_FOR_CATEGORY_BREAKDOWN raw records. Done in Python
    (not SQL) because validation_errors/warnings are stored as JSON
    lists -- a portable, explicit, bounded scan beats a
    dialect-specific JSON-aggregate query for a count this small."""
    stmt = _scope(
        select(RawRecord.validation_errors, RawRecord.validation_warnings),
        organization_id=organization_id, source_id=source_id, since=since, until=until,
    ).limit(MAX_RECORDS_FOR_CATEGORY_BREAKDOWN)

    rejection_categories: dict[str, int] = {}
    warning_categories: dict[str, int] = {}
    for errors, warnings in db.execute(stmt).all():
        for issue in errors or []:
            code = issue.get("code", "unknown")
            rejection_categories[code] = rejection_categories.get(code, 0) + 1
        for issue in warnings or []:
            code = issue.get("code", "unknown")
            warning_categories[code] = warning_categories.get(code, 0) + 1
    return rejection_categories, warning_categories


def summarize_jobs(
    db: Session,
    organization_id: str,
    *,
    source_id: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> dict:
    """Operational ingestion-job summary -- job outcomes, not
    record-level quality (see summarize_data_quality for that)."""
    stmt = select(IngestionJob).where(IngestionJob.organization_id == organization_id)
    if source_id:
        stmt = stmt.where(IngestionJob.source_id == source_id)
    if since:
        stmt = stmt.where(IngestionJob.started_at >= since)
    if until:
        stmt = stmt.where(IngestionJob.started_at <= until)

    jobs = db.execute(stmt).scalars().all()
    by_status: dict[str, int] = {}
    accepted_total = rejected_total = duplicate_total = 0
    for job in jobs:
        by_status[job.status] = by_status.get(job.status, 0) + 1
        accepted_total += job.accepted_count
        rejected_total += job.rejected_count
        duplicate_total += job.duplicate_count

    return {
        "total_jobs": len(jobs),
        "by_status": by_status,
        "accepted_total": accepted_total,
        "rejected_total": rejected_total,
        "duplicate_total": duplicate_total,
        "source_id": source_id,
        "since": since,
        "until": until,
    }
