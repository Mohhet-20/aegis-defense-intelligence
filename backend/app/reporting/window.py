"""Time-window and filter semantics shared by every analytics section and report.

* All instants are UTC. Naive input datetimes are interpreted as UTC.
* A window is HALF-OPEN: ``start <= t < end``. A record exactly at ``end`` belongs
  to the next window, so adjacent windows never double count.
* ``time_basis`` says WHICH timestamp is windowed: ``event`` (the source-reported
  ``observed_at``) or ``ingestion`` (when AEGIS stored it, ``ingested_at``).
  The two are never mixed in one series.
* Windows are bounded (``ANALYTICS_MAX_WINDOW_DAYS``) and bucket counts are bounded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import get_settings
from app.core.errors import MlopsValidationError
from app.services.timeutil import ensure_utc

TIME_BASES = ("event", "ingestion")
MAX_BUCKETS = 400
MAX_FILTER_CHARS = 100


class AnalyticsInputError(MlopsValidationError):
    """422 with a message that is safe to show to the caller."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return ensure_utc(value)  # type: ignore[return-value]  # never None for a datetime


@dataclass(frozen=True)
class AnalyticsWindow:
    start: datetime
    end: datetime
    bucket: str  # "hour" | "day"
    time_basis: str = "event"

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def bucket_labels(self) -> list[str]:
        step = timedelta(hours=1) if self.bucket == "hour" else timedelta(days=1)
        cur = self.start.replace(minute=0, second=0, microsecond=0)
        if self.bucket == "day":
            cur = cur.replace(hour=0)
        labels = []
        while cur < self.end:
            labels.append(label_for(cur, self.bucket))
            cur += step
        return labels

    def describe(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "bucket": self.bucket, "time_basis": self.time_basis,
                "timezone": "UTC", "interval": "start <= t < end", "days": round(self.seconds / 86400, 3)}


def label_for(dt: datetime, bucket: str) -> str:
    return dt.strftime("%Y-%m-%dT%H:00:00Z") if bucket == "hour" else dt.strftime("%Y-%m-%d")


def build_window(start: Optional[datetime], end: Optional[datetime], days: Optional[int], bucket: str = "auto", time_basis: str = "event") -> AnalyticsWindow:
    s = get_settings()
    if time_basis not in TIME_BASES:
        raise AnalyticsInputError(f"time_basis must be one of {TIME_BASES}")
    now = now_utc()
    if start is None and end is None:
        d = days if days is not None else s.ANALYTICS_DEFAULT_WINDOW_DAYS
        if not 1 <= d <= s.ANALYTICS_MAX_WINDOW_DAYS:
            raise AnalyticsInputError(f"days must be between 1 and {s.ANALYTICS_MAX_WINDOW_DAYS}")
        end_v = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)  # include the current hour
        start_v = end_v - timedelta(days=d)
    elif start is not None and end is not None:
        if days is not None:
            raise AnalyticsInputError("give either days or start/end, not both")
        start_v, end_v = as_utc(start), as_utc(end)
    else:
        raise AnalyticsInputError("start and end must be given together")
    if end_v <= start_v:
        raise AnalyticsInputError("end must be after start")
    if end_v - start_v > timedelta(days=s.ANALYTICS_MAX_WINDOW_DAYS):
        raise AnalyticsInputError(f"the window may span at most {s.ANALYTICS_MAX_WINDOW_DAYS} days")
    if end_v > now + timedelta(days=1):
        raise AnalyticsInputError("end cannot be more than one day in the future")
    if bucket not in ("auto", "hour", "day"):
        raise AnalyticsInputError("bucket must be auto, hour or day")
    span_h = (end_v - start_v).total_seconds() / 3600
    chosen = ("hour" if span_h <= 72 else "day") if bucket == "auto" else bucket
    n = span_h if chosen == "hour" else span_h / 24
    if n > MAX_BUCKETS:
        raise AnalyticsInputError(f"bucket={chosen} would produce more than {MAX_BUCKETS} points; use a coarser bucket or a shorter window")
    return AnalyticsWindow(start=start_v, end=end_v, bucket=chosen, time_basis=time_basis)


@dataclass(frozen=True)
class AnalyticsFilters:
    source_id: Optional[str] = None
    category: Optional[str] = None  # events.event_type / observations.observation_type
    include_archived: bool = False

    def describe(self) -> dict:
        return {"source_id": self.source_id, "category": self.category, "include_archived": self.include_archived}


def build_filters(source_id: Optional[str], category: Optional[str], include_archived: bool = False) -> AnalyticsFilters:
    for name, v in (("source_id", source_id), ("category", category)):
        if v is not None and (not v.strip() or len(v) > MAX_FILTER_CHARS):
            raise AnalyticsInputError(f"{name} must be 1-{MAX_FILTER_CHARS} characters")
    return AnalyticsFilters(source_id=source_id.strip() if source_id else None, category=category.strip() if category else None, include_archived=include_archived)


def percentile(sorted_values: list[float], p: float) -> Optional[float]:
    """Nearest-rank percentile of an ascending list; None when empty."""
    if not sorted_values:
        return None
    k = max(0, min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1)))))
    return sorted_values[k]
