"""Service-level tests for app/services/timeseries_service.py (
the multi-sensor layer, Section 7) -- bounded time-series queries, deterministic stride
downsampling, and statistics over a real ingested series."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.models.sensor import Sensor
from app.services import sensor_ingestion_service as ingest_svc
from app.services import timeseries_service

settings = get_settings()


def _make_sensor(db, org, source, **overrides) -> Sensor:
    defaults = dict(
        organization_id=org.id, source_id=source.id, name="Timeseries Test Sensor", sensor_type="environmental",
        status="active", lifecycle_status="registered",
        measurement_types=["temperature_c"], measurement_units={"temperature_c": "celsius"},
        nominal_sampling_interval_seconds=60.0,
    )
    defaults.update(overrides)
    sensor = Sensor(**defaults)
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


def test_validate_time_range_defaults_to_7_days():
    since, until = timeseries_service.validate_time_range(None, None)
    assert (until - since) == timedelta(days=7)


def test_validate_time_range_rejects_since_after_until():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        timeseries_service.validate_time_range(now, now - timedelta(hours=1))


def test_validate_time_range_rejects_too_wide_a_range():
    now = datetime.now(timezone.utc)
    with pytest.raises(timeseries_service.QueryRangeTooLargeError):
        timeseries_service.validate_time_range(now - timedelta(days=settings.SENSOR_MAX_QUERY_RANGE_DAYS + 10), now)


def test_fetch_series_returns_real_ingested_observations(db, org, source):
    sensor = _make_sensor(db, org, source)
    ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 15, "seed": 40, "start_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
    )
    since, until = timeseries_service.validate_time_range(None, None)
    rows, truncated = timeseries_service.fetch_series(db, org.id, sensor.id, "temperature_c", since, until)
    assert len(rows) == 15
    assert truncated is False
    # Ascending order.
    assert all(rows[i].observed_at <= rows[i + 1].observed_at for i in range(len(rows) - 1))


def test_fetch_series_reports_truncation_honestly(db, org, source):
    sensor = _make_sensor(db, org, source)
    ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={"sensor_id": sensor.id, "measurement_type": "temperature_c", "count": 10, "seed": 41, "start_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
    )
    since, until = timeseries_service.validate_time_range(None, None)
    rows, truncated = timeseries_service.fetch_series(db, org.id, sensor.id, "temperature_c", since, until, max_samples=5)
    assert len(rows) == 5
    assert truncated is True


def test_downsample_keeps_first_and_last():
    class _Fake:
        def __init__(self, i):
            self.i = i

    observations = [_Fake(i) for i in range(100)]
    sampled = timeseries_service.downsample(observations, target_points=10)
    assert sampled[0] is observations[0]
    assert sampled[-1] is observations[-1]
    assert len(sampled) <= 12  # stride-based, not an exact count


def test_downsample_noop_when_already_under_target():
    observations = [1, 2, 3]
    assert timeseries_service.downsample(observations, target_points=10) == observations


def test_compute_statistics_over_real_series(db, org, source):
    sensor = _make_sensor(db, org, source)
    ingest_svc.submit_synthetic_batch(
        db, organization_id=org.id, source_id=source.id, created_by_user_id=None,
        config={
            "sensor_id": sensor.id, "measurement_type": "temperature_c", "unit": "celsius", "count": 20, "seed": 42,
            "base_value": 22.0, "noise_amplitude": 1.0, "start_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        },
    )
    since, until = timeseries_service.validate_time_range(None, None)
    stats = timeseries_service.compute_statistics(db, org.id, sensor.id, "temperature_c", since, until, unit="celsius", nominal_interval_seconds=60.0)
    assert stats.valid_count == 20
    assert stats.insufficient_sample is False
    assert 18.0 < stats.mean < 26.0
    assert stats.measurement_type == "temperature_c"


def test_compute_statistics_empty_window_is_insufficient_sample(db, org, source):
    sensor = _make_sensor(db, org, source)
    since, until = timeseries_service.validate_time_range(None, None)
    stats = timeseries_service.compute_statistics(db, org.id, sensor.id, "temperature_c", since, until)
    assert stats.insufficient_sample is True
    assert stats.valid_count == 0
