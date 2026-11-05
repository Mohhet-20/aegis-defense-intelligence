"""Temporal exploration over location-bearing records (Section 5C/8/9). Shares app/services/geo_query_service.py's per-type
fetch/validation machinery -- a timeline query is a geospatial query
with no bounding box, not a parallel implementation.

"Historical playback" is a bounded, ascending-by-time
fetch of REAL stored records -- it never interpolates a position
between two records, never invents an in-between timestamp, and never
pretends to be a live stream. The frontend steps through the returned
list; nothing here holds server-side playback state.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.geospatial import (
    GeospatialQueryResponse,
    TemporalGapResponse,
    TimeBucketCountResponse,
    TimeRangeSearched,
)
from app.services.geo_query_service import (
    RECORD_TYPE_MODELS,
    SELECTABLE_TIMESTAMP_TYPES,
    fetch_record_type,
    resolve_record_types,
)
from app.services.timeutil import ensure_utc

settings = get_settings()

# A hard ceiling on how many raw timestamps a bucketing/gap-analysis
# query will ever pull into Python -- Section 9: "bound query ranges
# and output sizes." Beyond this, the result says so explicitly
# (`is_approximate`) rather than silently sampling.
MAX_TEMPORAL_SAMPLE_ROWS = 5000


class TimeRangeTooLargeError(ValueError):
    pass


def _validate_range(since: datetime, until: datetime) -> None:
    if since >= until:
        raise ValueError("since must be before until")
    span_days = (until - since).total_seconds() / 86400.0
    if span_days > settings.GEOSPATIAL_MAX_TIME_RANGE_DAYS:
        raise TimeRangeTooLargeError(
            f"requested range ({span_days:.1f} days) exceeds GEOSPATIAL_MAX_TIME_RANGE_DAYS ({settings.GEOSPATIAL_MAX_TIME_RANGE_DAYS})"
        )


def query_timeline(
    db: Session, organization_id: str, *,
    since: datetime, until: datetime,
    record_types: Optional[list[str]] = None,
    timestamp_type: Optional[str] = None,
    max_results: Optional[int] = None,
    ascending: bool = False,
) -> GeospatialQueryResponse:
    """A bounded, time-filtered fetch across the requested record
    types -- used directly by both the Timeline Explorer (Section 8,
    `ascending=False` for "most recent first") and historical playback
    (`ascending=True`, consumed in order by the frontend's step
    control)."""
    _validate_range(since, until)
    types = resolve_record_types(record_types)
    cap = min(max_results or settings.GEOSPATIAL_MAX_RESULTS, settings.GEOSPATIAL_MAX_RESULTS)

    all_items = []
    excluded_total = 0
    for rt in types:
        result = fetch_record_type(db, organization_id, rt, since=since, until=until, timestamp_type=timestamp_type, limit=cap)
        all_items.extend(result.items)
        excluded_total += result.excluded_unusable

    all_items.sort(key=lambda r: r.timestamp, reverse=not ascending)
    total_matched = len(all_items)
    truncated = total_matched > cap
    returned = all_items[:cap]

    return GeospatialQueryResponse(
        items=returned,
        total_matched=total_matched,
        returned_count=len(returned),
        truncated=truncated,
        max_results=cap,
        time_range_searched=TimeRangeSearched(since=since, until=until, timestamp_type=timestamp_type or "observed_at"),
        record_types_searched=types,
        missing_or_invalid_location_count=excluded_total,
    )


def _timestamps_for_bucketing(db: Session, organization_id: str, record_type: str, *, since: datetime, until: datetime, timestamp_type: Optional[str]) -> tuple[list[datetime], bool]:
    model = RECORD_TYPE_MODELS[record_type]
    options = SELECTABLE_TIMESTAMP_TYPES[record_type]
    chosen = timestamp_type if timestamp_type in options else options[0]
    column = model.created_at if chosen == "registered_at" else getattr(model, chosen)

    stmt = select(column).where(model.organization_id == organization_id, column >= since, column < until)
    rows = db.execute(stmt.limit(MAX_TEMPORAL_SAMPLE_ROWS + 1)).scalars().all()
    is_approximate = len(rows) > MAX_TEMPORAL_SAMPLE_ROWS
    return [ensure_utc(r) for r in rows[:MAX_TEMPORAL_SAMPLE_ROWS]], is_approximate


def time_bucket_counts(
    db: Session, organization_id: str, *,
    since: datetime, until: datetime, bucket_seconds: int,
    record_types: Optional[list[str]] = None, timestamp_type: Optional[str] = None,
) -> tuple[list[TimeBucketCountResponse], bool]:
    """Counts of records per fixed-width time bucket.
    Returns (buckets, is_approximate) -- is_approximate is True only
    when more than MAX_TEMPORAL_SAMPLE_ROWS timestamps existed in range
    for ANY included record type, in which case the counts are a
    bounded sample, not a claimed-complete total (never silently
    presented as exact)."""
    _validate_range(since, until)
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    types = resolve_record_types(record_types)

    bucket_count = max(1, math.ceil((until - since).total_seconds() / bucket_seconds))
    counts = [0] * bucket_count
    any_approximate = False

    for rt in types:
        timestamps, is_approximate = _timestamps_for_bucketing(db, organization_id, rt, since=since, until=until, timestamp_type=timestamp_type)
        any_approximate = any_approximate or is_approximate
        for ts in timestamps:
            idx = int((ts - since).total_seconds() // bucket_seconds)
            if 0 <= idx < bucket_count:
                counts[idx] += 1

    buckets = [
        TimeBucketCountResponse(
            bucket_start=since + timedelta(seconds=i * bucket_seconds),
            bucket_end=since + timedelta(seconds=(i + 1) * bucket_seconds),
            count=counts[i],
        )
        for i in range(bucket_count)
    ]
    return buckets, any_approximate


def temporal_gaps(
    db: Session, organization_id: str, *,
    record_type: str, since: datetime, until: datetime,
    min_gap_seconds: float, timestamp_type: Optional[str] = None,
) -> tuple[list[TemporalGapResponse], bool]:
    """Consecutive-record gaps >= min_gap_seconds for ONE record type
    (Section 9's "temporal gaps"). A gap here describes an absence of
    records in this project's own data, never a claim that nothing
    happened in the real world during that interval."""
    _validate_range(since, until)
    if record_type not in RECORD_TYPE_MODELS:
        raise ValueError(f"unknown record_type '{record_type}'")
    timestamps, is_approximate = _timestamps_for_bucketing(db, organization_id, record_type, since=since, until=until, timestamp_type=timestamp_type)
    timestamps.sort()

    gaps: list[TemporalGapResponse] = []
    for prev, cur in zip(timestamps, timestamps[1:]):
        delta = (cur - prev).total_seconds()
        if delta >= min_gap_seconds:
            gaps.append(TemporalGapResponse(record_type=record_type, gap_start=prev, gap_end=cur, gap_seconds=delta))
    return gaps, is_approximate
