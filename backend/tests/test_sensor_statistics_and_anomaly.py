"""Unit tests for app/sensors/statistics.py and app/sensors/anomaly.py.
Pure functions, no DB access."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.sensors import anomaly as anomaly_lib
from app.sensors import statistics as stats_lib

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _series(values: list[float], *, interval_seconds: float = 60.0, start: datetime = NOW) -> list[stats_lib.TimedValue]:
    return [stats_lib.TimedValue(observed_at=start + timedelta(seconds=interval_seconds * i), value=v) for i, v in enumerate(values)]


# --- statistics.py -----------------------------------------------------


def test_empty_series_is_insufficient_sample():
    result = stats_lib.compute_descriptive_statistics([], measurement_type="temperature_c", unit="celsius")
    assert result.insufficient_sample is True
    assert result.valid_count == 0


def test_single_point_series_is_insufficient_sample_but_not_empty():
    result = stats_lib.compute_descriptive_statistics(_series([20.0]), measurement_type="temperature_c", unit="celsius")
    assert result.valid_count == 1
    assert result.insufficient_sample is True
    assert result.minimum == 20.0


def test_basic_descriptive_statistics():
    result = stats_lib.compute_descriptive_statistics(_series([10.0, 20.0, 30.0]), measurement_type="temperature_c", unit="celsius")
    assert result.minimum == 10.0
    assert result.maximum == 30.0
    assert result.mean == 20.0
    assert result.median == 20.0
    assert result.valid_count == 3
    assert result.insufficient_sample is False


def test_invalid_points_excluded_from_statistics():
    series = [
        stats_lib.TimedValue(observed_at=NOW, value=10.0, is_valid=False),
        stats_lib.TimedValue(observed_at=NOW + timedelta(seconds=60), value=20.0, is_valid=True),
    ]
    result = stats_lib.compute_descriptive_statistics(series, measurement_type="temperature_c", unit="celsius")
    assert result.valid_count == 1
    assert result.invalid_count == 1
    assert result.mean == 20.0


def test_rate_of_change_computed_between_last_two_points():
    result = stats_lib.compute_descriptive_statistics(_series([10.0, 20.0], interval_seconds=10.0), measurement_type="t", unit=None)
    assert result.rate_of_change_per_second == 1.0  # (20-10)/10s


def test_gap_summary_detects_gap_exceeding_nominal_interval():
    series = [
        stats_lib.TimedValue(observed_at=NOW, value=1.0),
        stats_lib.TimedValue(observed_at=NOW + timedelta(seconds=1000), value=2.0),
    ]
    result = stats_lib.compute_descriptive_statistics(series, measurement_type="t", unit=None, nominal_interval_seconds=60.0)
    assert result.gap_summary.gap_count == 1
    assert result.gap_summary.missing_frame_like is True


def test_no_nan_or_infinite_values_ever_returned():
    series = [stats_lib.TimedValue(observed_at=NOW, value=float("inf")), stats_lib.TimedValue(observed_at=NOW + timedelta(seconds=60), value=1.0)]
    result = stats_lib.compute_descriptive_statistics(series, measurement_type="t", unit=None)
    assert result.maximum != float("inf")
    assert result.maximum is None or result.maximum == 1.0


# --- anomaly.py ----------------------------------------------------------


def test_range_violation_detected():
    result = anomaly_lib.check_range_violation(99.0, NOW, operating_range={"min": -10.0, "max": 45.0})
    assert result.candidate is not None
    assert result.candidate.detection_method == "range_violation"
    assert result.candidate.severity != "critical"  # never a threat-sounding severity
    assert result.candidate.category == "statistical_deviation"


def test_range_violation_no_configured_range_is_insufficient_not_a_false_pass():
    result = anomaly_lib.check_range_violation(99.0, NOW, operating_range=None)
    assert result.candidate is None
    assert result.reason is not None


def test_rolling_zscore_insufficient_baseline_reported_honestly():
    result = anomaly_lib.check_rolling_zscore(100.0, NOW, recent_values=[20.0, 21.0], min_baseline_samples=5, threshold=3.0)
    assert result.insufficient_baseline is True
    assert result.candidate is None
    assert "insufficient" in (result.reason or "").lower() or "required" in (result.reason or "")


def test_rolling_zscore_detects_outlier_with_sufficient_baseline():
    baseline = [20.0, 20.1, 19.9, 20.2, 19.8, 20.0, 20.1]
    result = anomaly_lib.check_rolling_zscore(100.0, NOW, recent_values=baseline, min_baseline_samples=5, threshold=3.0)
    assert result.candidate is not None
    assert result.candidate.detection_method == "rolling_zscore"


def test_rolling_zscore_within_threshold_no_candidate():
    baseline = [20.0, 20.1, 19.9, 20.2, 19.8, 20.0, 20.1]
    result = anomaly_lib.check_rolling_zscore(20.05, NOW, recent_values=baseline, min_baseline_samples=5, threshold=3.0)
    assert result.candidate is None
    assert result.insufficient_baseline is False


def test_zero_variance_baseline_is_undefined_not_a_crash():
    result = anomaly_lib.check_rolling_zscore(20.0, NOW, recent_values=[20.0, 20.0, 20.0, 20.0, 20.0], min_baseline_samples=5, threshold=3.0)
    assert result.candidate is None
    assert "undefined" in (result.reason or "")


def test_median_absolute_deviation_detects_outlier():
    baseline = [20.0, 20.1, 19.9, 20.2, 19.8, 20.0, 20.1]
    result = anomaly_lib.check_median_absolute_deviation(100.0, NOW, recent_values=baseline, min_baseline_samples=5, threshold=3.0)
    assert result.candidate is not None
    assert result.candidate.detection_method == "median_absolute_deviation"


def test_rate_of_change_no_previous_value_is_a_reason_not_a_candidate():
    result = anomaly_lib.check_rate_of_change(20.0, NOW, previous_value=None, previous_observed_at=None, recent_rates=[], min_baseline_samples=5, threshold=3.0)
    assert result.candidate is None
    assert result.insufficient_baseline is False


def test_rate_of_change_insufficient_baseline():
    result = anomaly_lib.check_rate_of_change(
        20.0, NOW, previous_value=19.0, previous_observed_at=NOW - timedelta(seconds=60),
        recent_rates=[0.01], min_baseline_samples=5, threshold=3.0,
    )
    assert result.insufficient_baseline is True


def test_missing_heartbeat_never_connected_candidate():
    result = anomaly_lib.check_missing_heartbeat(
        last_valid_observed_at=None, now=NOW, nominal_interval_seconds=60.0, default_interval_seconds=300.0, missed_multiple=3.0,
    )
    assert result.candidate is not None
    assert result.candidate.category == "sensor_health"


def test_missing_heartbeat_within_interval_no_candidate():
    result = anomaly_lib.check_missing_heartbeat(
        last_valid_observed_at=NOW - timedelta(seconds=30), now=NOW, nominal_interval_seconds=60.0, default_interval_seconds=300.0, missed_multiple=3.0,
    )
    assert result.candidate is None


def test_missing_heartbeat_exceeded_interval_candidate():
    result = anomaly_lib.check_missing_heartbeat(
        last_valid_observed_at=NOW - timedelta(seconds=1000), now=NOW, nominal_interval_seconds=60.0, default_interval_seconds=300.0, missed_multiple=3.0,
    )
    assert result.candidate is not None
    assert result.candidate.detection_method == "missing_heartbeat"


def test_repeated_value_anomaly_detected():
    result = anomaly_lib.check_repeated_value_anomaly(20.0, NOW, recent_values=[20.0] * 5, max_identical_run=5)
    assert result.candidate is not None
    assert result.candidate.category == "data_quality"  # never analyst_confirmed/data_quality set by a method -- wait this IS data_quality by design


def test_sampling_gap_anomaly_detected():
    result = anomaly_lib.check_sampling_gap_anomaly(NOW, latest_prior_observed_at=NOW - timedelta(seconds=1000), nominal_interval_seconds=60.0, missed_multiple=3.0)
    assert result.candidate is not None
    assert result.candidate.category == "data_quality"


def test_no_anomaly_severity_is_threat_sounding():
    """Section 9: severities are a closed, non-threat-sounding set."""
    from app.models.observation_anomaly import ANOMALY_SEVERITIES

    for forbidden in ("critical", "hostile", "threat", "danger"):
        assert forbidden not in ANOMALY_SEVERITIES
