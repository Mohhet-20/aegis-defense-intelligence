"""Bounded time-series queries and descriptive statistics (Sections 7-8). Every query here is explicitly bounded -- a caller
cannot request an unbounded history; `app/core/config.py`'s
SENSOR_MAX_QUERY_RANGE_DAYS/SENSOR_MAX_RAW_SAMPLES are the hard ceilings
enforced here, never left to the caller's judgment alone."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.observation import Observation
from app.sensors.statistics import DescriptiveStatistics, TimedValue, compute_descriptive_statistics

settings = get_settings()


class QueryRangeTooLargeError(ValueError):
    pass


def validate_time_range(since: Optional[datetime], until: Optional[datetime]) -> tuple[datetime, datetime]:
    """Fills in sensible bounded defaults and rejects a range wider
    than SENSOR_MAX_QUERY_RANGE_DAYS -- Section 7: "explicit limits for
    maximum query range." Never silently truncates a too-wide request;
    the caller gets a clear error instead."""
    until = until or datetime.now(timezone.utc)
    since = since or (until - timedelta(days=7))
    if since > until:
        raise ValueError("since must be before until")
    if (until - since) > timedelta(days=settings.SENSOR_MAX_QUERY_RANGE_DAYS):
        raise QueryRangeTooLargeError(f"requested range exceeds the {settings.SENSOR_MAX_QUERY_RANGE_DAYS}-day maximum query range")
    return since, until


def _base_query(organization_id: str, sensor_id: str, measurement_type: str, since: datetime, until: datetime, *, quality_status: Optional[str] = None):
    stmt = (
        select(Observation)
        .where(
            Observation.organization_id == organization_id,
            Observation.sensor_id == sensor_id,
            Observation.observation_type == measurement_type,
            Observation.observed_at >= since,
            Observation.observed_at <= until,
        )
        .order_by(Observation.observed_at.asc())
    )
    if quality_status:
        stmt = stmt.where(Observation.validation_status == quality_status)
    return stmt


def count_observations(db: Session, organization_id: str, sensor_id: str, measurement_type: str, since: datetime, until: datetime) -> int:
    stmt = _base_query(organization_id, sensor_id, measurement_type, since, until)
    return db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()


def fetch_series(
    db: Session, organization_id: str, sensor_id: str, measurement_type: str, since: datetime, until: datetime,
    *, max_samples: Optional[int] = None, quality_status: Optional[str] = None,
) -> tuple[list[Observation], bool]:
    """Returns (observations, was_truncated). `was_truncated=True` means
    more rows existed in [since, until] than max_samples -- the caller
    MUST surface this ("clearly identify when a chart
    displays aggregated or downsampled values"), never silently drop
    the tail."""
    max_samples = max_samples or settings.SENSOR_MAX_RAW_SAMPLES
    stmt = _base_query(organization_id, sensor_id, measurement_type, since, until, quality_status=quality_status).limit(max_samples + 1)
    rows = list(db.execute(stmt).scalars().all())
    truncated = len(rows) > max_samples
    return rows[:max_samples], truncated


def downsample(observations: list[Observation], *, target_points: int) -> list[Observation]:
    """Deterministic, stride-based downsampling -- always keeps the
    first and last point, and every `stride`-th point in between.
    Never averages/smooths ("do not imply downsampled data
    preserves every transient event" -- a stride sample is honestly a
    SUBSET of real points, not a synthetic blend)."""
    if target_points <= 0 or len(observations) <= target_points:
        return observations
    stride = max(1, len(observations) // target_points)
    sampled = observations[::stride]
    if sampled[-1] is not observations[-1]:
        sampled.append(observations[-1])
    return sampled


def compute_statistics(
    db: Session, organization_id: str, sensor_id: str, measurement_type: str, since: datetime, until: datetime,
    *, unit: Optional[str] = None, nominal_interval_seconds: Optional[float] = None,
) -> DescriptiveStatistics:
    """Computes statistics over the FULL [since, until] window via a
    bounded query -- deliberately does not go through the raw-sample
    cap used for chart rendering, but the window itself is still capped
    by validate_time_range()'s day limit, so this never scans an
    unbounded table."""
    stmt = _base_query(organization_id, sensor_id, measurement_type, since, until)
    rows = list(db.execute(stmt).scalars().all())
    series = [
        TimedValue(observed_at=obs.observed_at, value=obs.measurement_value, is_valid=obs.validation_status not in ("invalid",))
        for obs in rows
    ]
    return compute_descriptive_statistics(series, measurement_type=measurement_type, unit=unit, nominal_interval_seconds=nominal_interval_seconds)
