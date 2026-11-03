"""Sensor health. Everything here is computed
ON DEMAND from the sensor's own stored rows -- same "no stale summary
cache" principle app/services/quality_service.py already established
for data-platform-wide quality reporting. Four SEPARATE signals are
returned, never collapsed into one score (Section 10's explicit
requirement): connectivity/ingestion health, measurement quality,
analytical anomaly status, and device-reported status.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.observation import Observation
from app.models.observation_anomaly import ObservationAnomaly
from app.models.sensor import SENSOR_LIFECYCLE_MANUAL_ONLY_TARGETS, Sensor
from app.services import audit_service
from app.services.timeutil import ensure_utc

settings = get_settings()

HEALTH_RULE_VERSION = "1.0"

# How far back measurement-quality/anomaly-status look when computing
# health -- bounded, same discipline as every other windowed query in
# this codebase.
_QUALITY_WINDOW = timedelta(days=7)


@dataclass
class ConnectivityHealth:
    status: str  # "never_connected" | "connected" | "missed_heartbeat" | "offline"
    last_valid_observation_at: Optional[datetime]
    last_ingestion_success_at: Optional[datetime]
    explanation: str


@dataclass
class MeasurementQualityHealth:
    status: str  # "insufficient_data" | "good" | "degraded"
    sample_size: int
    invalid_count: int
    invalid_rate: Optional[float]
    warning_rate: Optional[float]
    explanation: str


@dataclass
class AnomalyStatusHealth:
    unresolved_count: int
    by_severity: dict
    explanation: str


@dataclass
class DeviceReportedHealth:
    status: Optional[str]
    as_of: Optional[datetime]
    explanation: str


@dataclass
class SensorHealth:
    sensor_id: str
    as_of: datetime
    rule_version: str
    connectivity: ConnectivityHealth
    measurement_quality: MeasurementQualityHealth
    anomaly_status: AnomalyStatusHealth
    device_reported: DeviceReportedHealth


def _connectivity(sensor: Sensor, now: datetime) -> ConnectivityHealth:
    # Every datetime surfaced on the SensorHealth response is normalized
    # to aware UTC here -- a DB-read value that round-tripped through
    # SQLite as naive would otherwise serialize differently (no "+00:00"
    # offset) than `now`/other aware fields on the same response, which
    # is a real, user-facing inconsistency for an API client, not just
    # an internal subtraction concern.
    last_seen_at = ensure_utc(sensor.last_seen_at)
    last_ingestion_success_at = ensure_utc(sensor.last_ingestion_success_at)
    if last_seen_at is None:
        return ConnectivityHealth(
            status="never_connected", last_valid_observation_at=None, last_ingestion_success_at=last_ingestion_success_at,
            explanation="no valid observation has ever been recorded for this sensor -- this is an absence of information, not a confirmed failure",
        )
    interval = sensor.nominal_sampling_interval_seconds or settings.SENSOR_HEARTBEAT_DEFAULT_SECONDS
    elapsed = (now - last_seen_at).total_seconds()
    threshold = interval * settings.SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE
    if elapsed > settings.SENSOR_OFFLINE_AFTER_SECONDS:
        status, explanation = "offline", f"{elapsed:.0f}s since the last valid observation exceeds the {settings.SENSOR_OFFLINE_AFTER_SECONDS:.0f}s offline threshold"
    elif elapsed > threshold:
        status, explanation = "missed_heartbeat", f"{elapsed:.0f}s since the last valid observation exceeds {settings.SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE}x the nominal interval ({interval:.0f}s)"
    else:
        status, explanation = "connected", f"last valid observation was {elapsed:.0f}s ago, within the expected interval"
    return ConnectivityHealth(status=status, last_valid_observation_at=last_seen_at, last_ingestion_success_at=last_ingestion_success_at, explanation=explanation)


def _measurement_quality(db: Session, organization_id: str, sensor_id: str, now: datetime) -> MeasurementQualityHealth:
    since = now - _QUALITY_WINDOW
    stmt = select(Observation.validation_status, func.count()).where(
        Observation.organization_id == organization_id, Observation.sensor_id == sensor_id, Observation.ingested_at >= since,
    ).group_by(Observation.validation_status)
    counts = dict(db.execute(stmt).all())
    total = sum(counts.values())
    if total == 0:
        return MeasurementQualityHealth(
            status="insufficient_data", sample_size=0, invalid_count=0, invalid_rate=None, warning_rate=None,
            explanation=f"no observations were ingested for this sensor in the last {_QUALITY_WINDOW.days} days -- connectivity may be fine; there is simply nothing to assess quality on",
        )
    invalid = counts.get("invalid", 0)
    warnings = counts.get("valid_with_warnings", 0) + counts.get("stale", 0) + counts.get("out_of_range", 0)
    invalid_rate = round(invalid / total, 4)
    warning_rate = round(warnings / total, 4)
    status = "degraded" if invalid_rate > 0.2 or warning_rate > 0.5 else "good"
    explanation = f"{invalid} of {total} observations in the last {_QUALITY_WINDOW.days} days were invalid ({invalid_rate:.0%}); {warnings} carried a quality warning ({warning_rate:.0%})"
    return MeasurementQualityHealth(status=status, sample_size=total, invalid_count=invalid, invalid_rate=invalid_rate, warning_rate=warning_rate, explanation=explanation)


def _anomaly_status(db: Session, organization_id: str, sensor_id: str, now: datetime) -> AnomalyStatusHealth:
    since = now - _QUALITY_WINDOW
    stmt = select(ObservationAnomaly.severity, func.count()).where(
        ObservationAnomaly.organization_id == organization_id, ObservationAnomaly.sensor_id == sensor_id,
        ObservationAnomaly.review_status == "unreviewed", ObservationAnomaly.created_at >= since,
    ).group_by(ObservationAnomaly.severity)
    by_severity = dict(db.execute(stmt).all())
    total = sum(by_severity.values())
    explanation = (
        f"{total} unreviewed anomaly candidate(s) in the last {_QUALITY_WINDOW.days} days -- a statistical observation, not a confirmed threat or fault"
        if total else f"no unreviewed anomaly candidates in the last {_QUALITY_WINDOW.days} days"
    )
    return AnomalyStatusHealth(unresolved_count=total, by_severity=by_severity, explanation=explanation)


def _device_reported(sensor: Sensor) -> DeviceReportedHealth:
    if sensor.device_reported_status is None:
        return DeviceReportedHealth(status=None, as_of=None, explanation="no connector payload for this sensor has ever explicitly supplied a device-reported status field")
    return DeviceReportedHealth(status=sensor.device_reported_status, as_of=ensure_utc(sensor.device_reported_status_at), explanation="verbatim status from the sensor's own connector payload -- never inferred")


def compute_health(db: Session, organization_id: str, sensor: Sensor) -> SensorHealth:
    now = datetime.now(timezone.utc)
    return SensorHealth(
        sensor_id=sensor.id, as_of=now, rule_version=HEALTH_RULE_VERSION,
        connectivity=_connectivity(sensor, now),
        measurement_quality=_measurement_quality(db, organization_id, sensor.id, now),
        anomaly_status=_anomaly_status(db, organization_id, sensor.id, now),
        device_reported=_device_reported(sensor),
    )


def recompute_lifecycle_status(db: Session, organization_id: str, sensor: Sensor, *, actor_user_id: Optional[str]) -> tuple[Sensor, SensorHealth]:
    """Applies `compute_health()`'s result to `sensor.lifecycle_status`,
    UNLESS the sensor is currently in "maintenance" or "retired" --
    those are manual-only states this function never overrides
    (Section 3's documented transition rules). Always an explicit,
    audited action -- never run implicitly on every read."""
    health = compute_health(db, organization_id, sensor)
    previous_status = sensor.lifecycle_status
    if previous_status not in SENSOR_LIFECYCLE_MANUAL_ONLY_TARGETS:
        if health.connectivity.status == "offline":
            new_status = "offline"
        elif health.connectivity.status == "never_connected":
            new_status = "registered"
        elif health.measurement_quality.status == "degraded" or health.anomaly_status.unresolved_count > 0:
            new_status = "degraded"
        else:
            new_status = "active"
        if new_status != previous_status:
            sensor.lifecycle_status = new_status
            db.add(sensor)
            db.commit()
            db.refresh(sensor)
            audit_service.record(
                db, action="sensor.lifecycle_status_recomputed", actor_user_id=actor_user_id, organization_id=organization_id,
                target_type="sensor", target_id=sensor.id,
                context_metadata={"previous_status": previous_status, "new_status": new_status, "rule_version": HEALTH_RULE_VERSION},
            )
            db.commit()
    return sensor, health
