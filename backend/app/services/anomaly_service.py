"""Anomaly detection orchestration + review workflow (Phase 6, Section
9). Fetches a sensor+measurement_type's recent history, runs every
applicable heuristic from app/sensors/anomaly.py, and persists any
resulting candidate as an ObservationAnomaly -- never more than once
for the same (observation_id, detection_method) pair, so re-running
checks on an unchanged series is idempotent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.observation import Observation
from app.models.observation_anomaly import ANOMALY_REVIEW_STATUSES, ObservationAnomaly
from app.sensors import anomaly as anomaly_lib
from app.services.timeutil import ensure_utc

settings = get_settings()


# review_status -> the category an analyst's review action assigns.
# "analyst_confirmed" and "data_quality" are ONLY ever set via this
# mapping, during an explicit review action -- never computed by a
# detection method itself (Section 9's required separation).
_REVIEW_STATUS_CATEGORY = {
    "confirmed_unusual": "analyst_confirmed",
    "data_quality_issue": "data_quality",
}


class SensorMismatchError(ValueError):
    pass


def _recent_history(db: Session, organization_id: str, sensor_id: str, measurement_type: str, *, limit: int) -> list[Observation]:
    stmt = (
        select(Observation)
        .where(
            Observation.organization_id == organization_id,
            Observation.sensor_id == sensor_id,
            Observation.observation_type == measurement_type,
            Observation.measurement_value.is_not(None),
        )
        .order_by(Observation.observed_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())[::-1]  # ascending


def _existing_candidate(db: Session, organization_id: str, *, observation_id: Optional[str], detection_method: str, sensor_id: str) -> Optional[ObservationAnomaly]:
    if observation_id is None:
        return None
    stmt = select(ObservationAnomaly).where(
        ObservationAnomaly.organization_id == organization_id,
        ObservationAnomaly.sensor_id == sensor_id,
        ObservationAnomaly.observation_id == observation_id,
        ObservationAnomaly.detection_method == detection_method,
    )
    return db.execute(stmt).scalar_one_or_none()


def _persist(db: Session, organization_id: str, sensor_id: str, measurement_type: str, observation_id: Optional[str], candidate: anomaly_lib.AnomalyCandidate) -> tuple[ObservationAnomaly, bool]:
    existing = _existing_candidate(db, organization_id, observation_id=observation_id, detection_method=candidate.detection_method, sensor_id=sensor_id)
    if existing is not None:
        return existing, False
    row = ObservationAnomaly(
        organization_id=organization_id, sensor_id=sensor_id, measurement_type=measurement_type,
        observation_id=observation_id, window_start=candidate.window_start, window_end=candidate.window_end,
        detection_method=candidate.detection_method, method_version=candidate.method_version, config=candidate.config,
        observed_value=candidate.observed_value, observed_summary=candidate.observed_summary, baseline_summary=candidate.baseline_summary,
        explanation=candidate.explanation, severity=candidate.severity, category=candidate.category, quality_flags=candidate.quality_flags,
        review_status="unreviewed",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, True


def run_checks(db: Session, *, organization_id: str, sensor, measurement_type: str) -> dict:
    """Runs every applicable method against this sensor+measurement
    type's current state. Returns a dict with `created` (newly
    persisted ObservationAnomaly rows), `already_known` (candidates
    that matched an existing row), and `insufficient_baseline` (method
    -> reason, for methods that could not run at all -- Section 9:
    "report that limitation rather than manufacturing a baseline")."""
    window = settings.SENSOR_ANOMALY_ROLLING_WINDOW
    history = _recent_history(db, organization_id, sensor.id, measurement_type, limit=window + 1)
    created: list[ObservationAnomaly] = []
    already_known: list[ObservationAnomaly] = []
    insufficient: dict[str, str] = {}
    now = datetime.now(timezone.utc)

    operating_range = (sensor.operating_range or {}).get(measurement_type)

    if history:
        latest = history[-1]
        prior = history[:-1]
        recent_values = [o.measurement_value for o in prior]

        results = [
            anomaly_lib.check_range_violation(latest.measurement_value, latest.observed_at, operating_range=operating_range),
            anomaly_lib.check_rolling_zscore(
                latest.measurement_value, latest.observed_at, recent_values=recent_values,
                min_baseline_samples=settings.SENSOR_ANOMALY_MIN_BASELINE_SAMPLES, threshold=settings.SENSOR_ANOMALY_ZSCORE_THRESHOLD,
            ),
            anomaly_lib.check_median_absolute_deviation(
                latest.measurement_value, latest.observed_at, recent_values=recent_values,
                min_baseline_samples=settings.SENSOR_ANOMALY_MIN_BASELINE_SAMPLES, threshold=settings.SENSOR_ANOMALY_MAD_THRESHOLD,
            ),
            anomaly_lib.check_repeated_value_anomaly(latest.measurement_value, latest.observed_at, recent_values=recent_values, max_identical_run=settings.SENSOR_MAX_IDENTICAL_RUN),
        ]
        if len(prior) >= 2:
            rates = [
                (prior[i].measurement_value - prior[i - 1].measurement_value) / max((prior[i].observed_at - prior[i - 1].observed_at).total_seconds(), 1e-9)
                for i in range(1, len(prior))
            ]
            results.append(anomaly_lib.check_rate_of_change(
                latest.measurement_value, latest.observed_at, previous_value=prior[-1].measurement_value, previous_observed_at=prior[-1].observed_at,
                recent_rates=rates, min_baseline_samples=settings.SENSOR_ANOMALY_MIN_BASELINE_SAMPLES, threshold=settings.SENSOR_ANOMALY_ZSCORE_THRESHOLD,
            ))
        results.append(anomaly_lib.check_sampling_gap_anomaly(
            latest.observed_at, latest_prior_observed_at=prior[-1].observed_at if prior else None,
            nominal_interval_seconds=sensor.nominal_sampling_interval_seconds, missed_multiple=settings.SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE,
        ))

        for result in results:
            if result.insufficient_baseline:
                insufficient[result.reason or "insufficient_baseline"] = result.reason or ""
            if result.candidate is not None:
                row, is_new = _persist(db, organization_id, sensor.id, measurement_type, latest.id, result.candidate)
                (created if is_new else already_known).append(row)

        last_valid_observed_at = ensure_utc(latest.observed_at)
    else:
        last_valid_observed_at = None

    heartbeat_result = anomaly_lib.check_missing_heartbeat(
        last_valid_observed_at=last_valid_observed_at, now=now, nominal_interval_seconds=sensor.nominal_sampling_interval_seconds,
        default_interval_seconds=settings.SENSOR_HEARTBEAT_DEFAULT_SECONDS, missed_multiple=settings.SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE,
    )
    if heartbeat_result.candidate is not None:
        # Window-based -- never anchored to one observation_id.
        existing = None
        stmt = select(ObservationAnomaly).where(
            ObservationAnomaly.organization_id == organization_id, ObservationAnomaly.sensor_id == sensor.id,
            ObservationAnomaly.measurement_type == measurement_type, ObservationAnomaly.detection_method == "missing_heartbeat",
            ObservationAnomaly.review_status == "unreviewed",
        )
        existing = db.execute(stmt).scalars().first()
        if existing is None:
            row, _ = _persist(db, organization_id, sensor.id, measurement_type, None, heartbeat_result.candidate)
            created.append(row)
        else:
            already_known.append(existing)

    return {"created": created, "already_known": already_known, "insufficient_baseline": insufficient}


def get_anomaly(db: Session, organization_id: str, anomaly_id: str) -> Optional[ObservationAnomaly]:
    stmt = select(ObservationAnomaly).where(ObservationAnomaly.id == anomaly_id, ObservationAnomaly.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_anomalies_query(
    organization_id: str, *, sensor_id: Optional[str] = None, measurement_type: Optional[str] = None,
    review_status: Optional[str] = None, category: Optional[str] = None,
):
    stmt = select(ObservationAnomaly).where(ObservationAnomaly.organization_id == organization_id)
    if sensor_id:
        stmt = stmt.where(ObservationAnomaly.sensor_id == sensor_id)
    if measurement_type:
        stmt = stmt.where(ObservationAnomaly.measurement_type == measurement_type)
    if review_status:
        stmt = stmt.where(ObservationAnomaly.review_status == review_status)
    if category:
        stmt = stmt.where(ObservationAnomaly.category == category)
    return stmt.order_by(ObservationAnomaly.created_at.desc())


def review_anomaly(db: Session, anomaly: ObservationAnomaly, *, reviewer_user_id: str, review_status: str, review_note: Optional[str]) -> ObservationAnomaly:
    if review_status not in ANOMALY_REVIEW_STATUSES:
        raise ValueError(f"'{review_status}' is not a valid review_status (must be one of {ANOMALY_REVIEW_STATUSES})")
    anomaly.review_status = review_status
    anomaly.reviewed_by_user_id = reviewer_user_id
    anomaly.reviewed_at = datetime.now(timezone.utc)
    if review_note is not None:
        anomaly.review_note = review_note
    new_category = _REVIEW_STATUS_CATEGORY.get(review_status)
    if new_category:
        anomaly.category = new_category
    db.add(anomaly)
    db.commit()
    db.refresh(anomaly)
    return anomaly
