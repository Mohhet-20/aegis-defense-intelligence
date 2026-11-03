"""Explainable, heuristic anomaly detection. Every
method here is a documented STATISTICAL heuristic over a sensor's own
recent history -- never an unsupported machine-learning claim, and
NEVER a threat/hostility judgment. A result is a candidate for an
analyst to interpret, not a conclusion.

Pure functions only -- app/services/anomaly_service.py supplies the
already-fetched recent history and persists whichever candidates these
functions actually return.
"""
from __future__ import annotations

import statistics as _stats
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.sensors.quality import check_repeated_value, check_sampling_gap

ANOMALY_METHOD_VERSION = "1.0"


@dataclass(frozen=True)
class AnomalyCandidate:
    detection_method: str
    method_version: str
    config: dict
    observed_value: Optional[float]
    observed_summary: dict
    baseline_summary: Optional[dict]
    explanation: str
    severity: str  # one of ANOMALY_SEVERITIES -- a data-quality severity, never a threat level
    category: str  # one of ANOMALY_CATEGORIES
    quality_flags: list[str] = field(default_factory=list)
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


@dataclass(frozen=True)
class MethodResult:
    candidate: Optional[AnomalyCandidate] = None
    insufficient_baseline: bool = False
    reason: Optional[str] = None


def check_range_violation(value: float, observed_at: datetime, *, operating_range: Optional[dict]) -> MethodResult:
    if not operating_range:
        return MethodResult(reason="no configured operating range for this measurement type")
    low, high = operating_range.get("min"), operating_range.get("max")
    if low is None and high is None:
        return MethodResult(reason="no configured operating range for this measurement type")
    if low is not None and value < low:
        return MethodResult(candidate=AnomalyCandidate(
            detection_method="range_violation", method_version=ANOMALY_METHOD_VERSION,
            config={"min": low, "max": high}, observed_value=value, observed_summary={"value": value},
            baseline_summary={"min": low, "max": high},
            explanation=f"value {value} is below the configured minimum {low} for this measurement type",
            severity="medium", category="statistical_deviation", quality_flags=["below_configured_minimum"],
            window_end=observed_at,
        ))
    if high is not None and value > high:
        return MethodResult(candidate=AnomalyCandidate(
            detection_method="range_violation", method_version=ANOMALY_METHOD_VERSION,
            config={"min": low, "max": high}, observed_value=value, observed_summary={"value": value},
            baseline_summary={"min": low, "max": high},
            explanation=f"value {value} is above the configured maximum {high} for this measurement type",
            severity="medium", category="statistical_deviation", quality_flags=["above_configured_maximum"],
            window_end=observed_at,
        ))
    return MethodResult()


def check_rolling_zscore(
    value: float, observed_at: datetime, *, recent_values: list[float], min_baseline_samples: int, threshold: float,
) -> MethodResult:
    if len(recent_values) < min_baseline_samples:
        return MethodResult(insufficient_baseline=True, reason=f"only {len(recent_values)} prior samples available; {min_baseline_samples} required for a rolling z-score baseline")
    mean = _stats.fmean(recent_values)
    try:
        stdev = _stats.stdev(recent_values)
    except _stats.StatisticsError:
        stdev = 0.0
    if stdev == 0:
        return MethodResult(reason="baseline has zero variance -- a z-score is undefined")
    z = (value - mean) / stdev
    if abs(z) < threshold:
        return MethodResult()
    return MethodResult(candidate=AnomalyCandidate(
        detection_method="rolling_zscore", method_version=ANOMALY_METHOD_VERSION,
        config={"threshold": threshold, "window": len(recent_values)},
        observed_value=value, observed_summary={"value": value, "zscore": round(z, 3)},
        baseline_summary={"mean": round(mean, 6), "stdev": round(stdev, 6), "window": len(recent_values)},
        explanation=f"value {value} is {abs(z):.2f} standard deviations from the rolling mean {mean:.4g} (threshold {threshold})",
        severity="high" if abs(z) >= threshold * 1.5 else "medium",
        category="statistical_deviation", quality_flags=["rolling_zscore_deviation"],
        window_end=observed_at,
    ))


def check_median_absolute_deviation(
    value: float, observed_at: datetime, *, recent_values: list[float], min_baseline_samples: int, threshold: float,
) -> MethodResult:
    if len(recent_values) < min_baseline_samples:
        return MethodResult(insufficient_baseline=True, reason=f"only {len(recent_values)} prior samples available; {min_baseline_samples} required for a MAD baseline")
    median = _stats.median(recent_values)
    deviations = [abs(v - median) for v in recent_values]
    mad = _stats.median(deviations)
    if mad == 0:
        return MethodResult(reason="baseline median absolute deviation is zero -- a robust threshold is undefined")
    # 1.4826 is the standard consistency constant that scales MAD to
    # be comparable to a standard deviation under a normal distribution.
    robust_z = 0.6745 * (value - median) / mad
    if abs(robust_z) < threshold:
        return MethodResult()
    return MethodResult(candidate=AnomalyCandidate(
        detection_method="median_absolute_deviation", method_version=ANOMALY_METHOD_VERSION,
        config={"threshold": threshold, "window": len(recent_values)},
        observed_value=value, observed_summary={"value": value, "robust_zscore": round(robust_z, 3)},
        baseline_summary={"median": round(median, 6), "mad": round(mad, 6), "window": len(recent_values)},
        explanation=f"value {value} has a robust z-score of {abs(robust_z):.2f} against the median {median:.4g} (MAD-based threshold {threshold})",
        severity="high" if abs(robust_z) >= threshold * 1.5 else "medium",
        category="statistical_deviation", quality_flags=["mad_deviation"],
        window_end=observed_at,
    ))


def check_rate_of_change(
    value: float, observed_at: datetime, *, previous_value: Optional[float], previous_observed_at: Optional[datetime],
    recent_rates: list[float], min_baseline_samples: int, threshold: float,
) -> MethodResult:
    if previous_value is None or previous_observed_at is None:
        return MethodResult(reason="no previous observation to compute a rate of change against")
    elapsed = (observed_at - previous_observed_at).total_seconds()
    if elapsed <= 0:
        return MethodResult(reason="non-positive elapsed time between observations")
    rate = (value - previous_value) / elapsed
    if len(recent_rates) < min_baseline_samples:
        return MethodResult(insufficient_baseline=True, reason=f"only {len(recent_rates)} prior rate samples available; {min_baseline_samples} required for a rate-of-change baseline")
    mean_rate = _stats.fmean(recent_rates)
    try:
        stdev_rate = _stats.stdev(recent_rates)
    except _stats.StatisticsError:
        stdev_rate = 0.0
    if stdev_rate == 0:
        return MethodResult(reason="baseline rate-of-change has zero variance")
    z = (rate - mean_rate) / stdev_rate
    if abs(z) < threshold:
        return MethodResult()
    return MethodResult(candidate=AnomalyCandidate(
        detection_method="rate_of_change", method_version=ANOMALY_METHOD_VERSION,
        config={"threshold": threshold, "window": len(recent_rates)},
        observed_value=value, observed_summary={"value": value, "rate_per_second": round(rate, 6), "zscore": round(z, 3)},
        baseline_summary={"mean_rate_per_second": round(mean_rate, 6), "stdev_rate_per_second": round(stdev_rate, 6)},
        explanation=f"rate of change {rate:.4g}/s is {abs(z):.2f} standard deviations from the recent baseline rate (threshold {threshold})",
        severity="medium", category="statistical_deviation", quality_flags=["rate_of_change_deviation"],
        window_end=observed_at,
    ))


def check_missing_heartbeat(
    *, last_valid_observed_at: Optional[datetime], now: datetime, nominal_interval_seconds: Optional[float],
    default_interval_seconds: float, missed_multiple: float,
) -> MethodResult:
    interval = nominal_interval_seconds or default_interval_seconds
    if last_valid_observed_at is None:
        return MethodResult(candidate=AnomalyCandidate(
            detection_method="missing_heartbeat", method_version=ANOMALY_METHOD_VERSION,
            config={"nominal_interval_seconds": interval, "missed_multiple": missed_multiple},
            observed_value=None, observed_summary={}, baseline_summary=None,
            explanation="no valid observation has ever been recorded for this sensor/measurement",
            severity="medium", category="sensor_health", quality_flags=["missing_heartbeat"],
            window_end=now,
        ))
    elapsed = (now - last_valid_observed_at).total_seconds()
    threshold = interval * missed_multiple
    if elapsed <= threshold:
        return MethodResult()
    return MethodResult(candidate=AnomalyCandidate(
        detection_method="missing_heartbeat", method_version=ANOMALY_METHOD_VERSION,
        config={"nominal_interval_seconds": interval, "missed_multiple": missed_multiple},
        observed_value=None, observed_summary={"elapsed_seconds": elapsed},
        baseline_summary={"nominal_interval_seconds": interval, "threshold_seconds": threshold},
        explanation=f"{elapsed:.0f}s have elapsed since the last valid observation, exceeding {missed_multiple}x the nominal interval ({interval:.0f}s)",
        severity="medium", category="sensor_health", quality_flags=["missing_heartbeat"],
        window_start=last_valid_observed_at, window_end=now,
    ))


def check_repeated_value_anomaly(
    value: float, observed_at: datetime, *, recent_values: list[float], max_identical_run: int,
) -> MethodResult:
    issues = check_repeated_value(value, recent_values=recent_values, max_identical_run=max_identical_run)
    if not issues:
        return MethodResult()
    run = sum(1 for v in reversed(recent_values) if v == value) + 1
    return MethodResult(candidate=AnomalyCandidate(
        detection_method="repeated_value", method_version=ANOMALY_METHOD_VERSION,
        config={"max_identical_run": max_identical_run},
        observed_value=value, observed_summary={"value": value, "run_length": run},
        baseline_summary=None,
        explanation=issues[0].message,
        severity="low", category="data_quality", quality_flags=["excessive_repeated_value"],
        window_end=observed_at,
    ))


def check_sampling_gap_anomaly(
    observed_at: datetime, *, latest_prior_observed_at: Optional[datetime], nominal_interval_seconds: Optional[float], missed_multiple: float,
) -> MethodResult:
    issues = check_sampling_gap(
        observed_at, latest_prior_observed_at=latest_prior_observed_at,
        nominal_interval_seconds=nominal_interval_seconds, missed_multiple=missed_multiple,
    )
    if not issues:
        return MethodResult()
    return MethodResult(candidate=AnomalyCandidate(
        detection_method="sampling_gap", method_version=ANOMALY_METHOD_VERSION,
        config={"nominal_interval_seconds": nominal_interval_seconds, "missed_multiple": missed_multiple},
        observed_value=None, observed_summary={}, baseline_summary=None,
        explanation=issues[0].message,
        severity="low", category="data_quality", quality_flags=["unexpected_sampling_gap"],
        window_start=latest_prior_observed_at, window_end=observed_at,
    ))
