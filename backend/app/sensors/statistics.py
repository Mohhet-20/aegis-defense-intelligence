"""Time-series descriptive statistics. Pure
functions over an already-fetched, bounded list of observations -- no
database access, no unbounded scans. app/services/timeseries_service.py
owns the bounded query; this module only computes over what it's given.

Every function here is deterministic for deterministic input and never
raises for empty/degenerate input -- it returns an explicit "insufficient
data" shape instead ("handle empty series," "handle
insufficient sample counts"). NaN/infinity are never returned as a
summary value; see `_finite_or_none`.
"""
from __future__ import annotations

import math
import statistics as _stats
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

STATISTICS_METHOD_VERSION = "1.0"


@dataclass(frozen=True)
class TimedValue:
    observed_at: datetime
    value: Optional[float]  # None represents an invalid/missing measurement
    is_valid: bool = True


@dataclass
class GapSummary:
    gap_count: int
    max_gap_seconds: Optional[float]
    missing_frame_like: bool = False  # documents that this is sampling-interval-derived, not a hard count


@dataclass
class DescriptiveStatistics:
    measurement_type: str
    unit: Optional[str]
    valid_count: int
    invalid_count: int
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    stdev_sample: Optional[float] = None
    percentiles: dict = field(default_factory=dict)
    latest_valid_value: Optional[float] = None
    latest_valid_observed_at: Optional[datetime] = None
    rate_of_change_per_second: Optional[float] = None
    gap_summary: Optional[GapSummary] = None
    insufficient_sample: bool = False
    method_version: str = STATISTICS_METHOD_VERSION


def _finite_or_none(value: float) -> Optional[float]:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return value


def compute_descriptive_statistics(
    series: list[TimedValue],
    *,
    measurement_type: str,
    unit: Optional[str],
    percentile_points: tuple[float, ...] = (0.5, 0.9, 0.95, 0.99),
    nominal_interval_seconds: Optional[float] = None,
) -> DescriptiveStatistics:
    """`series` must already be sorted ascending by observed_at --
    callers (the time-series service) own that ordering since it comes
    straight from an ORDER BY query."""
    valid = [
        point for point in series
        if point.is_valid and point.value is not None and not math.isnan(point.value) and not math.isinf(point.value)
    ]
    invalid_count = len(series) - len(valid)

    if not valid:
        return DescriptiveStatistics(
            measurement_type=measurement_type, unit=unit, valid_count=0, invalid_count=invalid_count,
            insufficient_sample=True,
        )

    values = [p.value for p in valid]
    minimum = _finite_or_none(min(values))
    maximum = _finite_or_none(max(values))
    mean = _finite_or_none(_stats.fmean(values))
    median = _finite_or_none(_stats.median(values)) if len(values) >= 1 else None
    stdev_sample = _finite_or_none(_stats.stdev(values)) if len(values) >= 2 else None

    percentiles: dict = {}
    if len(values) >= 2:
        sorted_values = sorted(values)
        for p in percentile_points:
            idx = min(len(sorted_values) - 1, max(0, round(p * (len(sorted_values) - 1))))
            percentiles[f"p{int(p * 100)}"] = _finite_or_none(sorted_values[idx])

    latest = valid[-1]
    rate_of_change = None
    if len(valid) >= 2:
        prev = valid[-2]
        elapsed = (latest.observed_at - prev.observed_at).total_seconds()
        if elapsed > 0 and latest.value is not None and prev.value is not None:
            rate_of_change = _finite_or_none((latest.value - prev.value) / elapsed)

    gap_summary = _compute_gap_summary(series, nominal_interval_seconds=nominal_interval_seconds)

    return DescriptiveStatistics(
        measurement_type=measurement_type,
        unit=unit,
        valid_count=len(valid),
        invalid_count=invalid_count,
        minimum=minimum,
        maximum=maximum,
        mean=mean,
        median=median,
        stdev_sample=stdev_sample,
        percentiles=percentiles,
        latest_valid_value=latest.value,
        latest_valid_observed_at=latest.observed_at,
        rate_of_change_per_second=rate_of_change,
        gap_summary=gap_summary,
        insufficient_sample=len(valid) < 2,
    )


def _compute_gap_summary(series: list[TimedValue], *, nominal_interval_seconds: Optional[float]) -> GapSummary:
    if len(series) < 2:
        return GapSummary(gap_count=0, max_gap_seconds=None)
    gaps = [
        (series[i].observed_at - series[i - 1].observed_at).total_seconds()
        for i in range(1, len(series))
    ]
    max_gap = max(gaps) if gaps else None
    if nominal_interval_seconds and nominal_interval_seconds > 0:
        gap_count = sum(1 for g in gaps if g > nominal_interval_seconds * 1.5)
        return GapSummary(gap_count=gap_count, max_gap_seconds=max_gap, missing_frame_like=True)
    return GapSummary(gap_count=0, max_gap_seconds=max_gap, missing_frame_like=False)
