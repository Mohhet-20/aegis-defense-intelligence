"""Infrastructure alerting with deduplication.
See app/models/infrastructure_alert.py for the dedup/history model.

Deliberately SEPARATE from intelligence `Event`s,
`ObservationAnomaly`/anomaly review, and `RiskAssessment` -- this
service only ever evaluates FLEET HEALTH conditions (presence,
resource thresholds, configuration drift), never a sensed real-world
condition. No real external notification (email/SMS) is sent by this
module -- Part 9 is explicit that none should be unless already
properly configured, and nothing in this project is, so alerts surface
only through the API/UI (the Fleet Operations Center's Alert Center)
and the audit trail.

`evaluate_alerts_for_device` is idempotent and safe to call on every
health-report submission (the existing ingestion path) -- it
never creates a duplicate open alert for an already-open condition
(see `_get_open_alert`'s dedup_key lookup), and it auto-resolves an
alert once its underlying condition is no longer observed, always
leaving a `resolution_note` explaining why.

Correctness note on presence-based alerts (`device_offline`/
`device_stale`): calling `evaluate_alerts_for_device` ONLY from inside
the health-report-submission path is not sufficient to ever actually
raise those two alert types, by construction -- a device has to
successfully submit a report for that code path to run at all, and
submitting a report is itself evidence the device is online, so
`derive_presence_state` would see a freshly-updated `last_seen_at` and
never compute "stale"/"offline" at that exact moment. A device that
has gone genuinely silent produces no inbound request of any kind, so
nothing would ever re-evaluate it. `evaluate_alerts_for_all_devices`
below exists specifically to close this gap: an explicit,
operator/scheduler-triggered sweep (the same pattern the
`edge_sync_service.recover_stale_syncing_records` already established
for its own "detect the absence of an expected update" problem,
exposed the same way via `POST /fleet/alerts/evaluate-sweep`) that
evaluates every device's presence/health/drift state regardless of
whether it has reported recently. A real deployment would schedule
this sweep on an interval (e.g. every few minutes) via an external
cron hitting that endpoint -- this project has no in-process background
scheduler (deliberately; see the own "no duplicate concurrent
workers" discipline), so no code here invents one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.device import Device
from app.models.infrastructure_alert import InfrastructureAlert
from app.services import audit_service, fleet_config_service, fleet_health_service

_OPEN_LIKE_STATUSES = ("open", "acknowledged", "reopened")


class InvalidAlertTransitionError(ValueError):
    pass


def _get_open_alert(db: Session, organization_id: str, dedup_key: str) -> Optional[InfrastructureAlert]:
    stmt = (
        select(InfrastructureAlert)
        .where(InfrastructureAlert.organization_id == organization_id, InfrastructureAlert.dedup_key == dedup_key, InfrastructureAlert.status.in_(_OPEN_LIKE_STATUSES))
        .order_by(InfrastructureAlert.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _upsert_open_alert(db: Session, device: Device, *, alert_type: str, severity: str, dedup_key: str, title: str, evidence: dict, explanation: str, now: datetime) -> InfrastructureAlert:
    existing = _get_open_alert(db, device.organization_id, dedup_key)
    if existing is not None:
        existing.severity = severity
        existing.evidence = evidence
        existing.explanation = explanation
        existing.occurrence_count += 1
        existing.last_evaluated_at = now
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing
    alert = InfrastructureAlert(
        organization_id=device.organization_id, device_id=device.id, alert_type=alert_type, severity=severity,
        status="open", dedup_key=dedup_key, title=title, evidence=evidence, explanation=explanation,
        occurrence_count=1, first_detected_at=now, last_evaluated_at=now,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def _auto_resolve_if_open(db: Session, device: Device, dedup_key: str, *, now: datetime, note: str) -> None:
    existing = _get_open_alert(db, device.organization_id, dedup_key)
    if existing is None:
        return
    existing.status = "resolved"
    existing.resolved_at = now
    existing.resolution_note = note
    db.add(existing)
    db.commit()


def evaluate_alerts_for_device(db: Session, device: Device, *, settings: Optional[Settings] = None, now: Optional[datetime] = None) -> list[InfrastructureAlert]:
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    findings_by_key = {f["rule_key"]: f for f in fleet_health_service.evaluate_health_findings(db, device, settings=settings, now=now)}
    touched: list[InfrastructureAlert] = []

    offline_dedup, stale_dedup = f"device_offline:{device.id}", f"device_stale:{device.id}"
    if "presence_offline" in findings_by_key:
        f = findings_by_key["presence_offline"]
        touched.append(_upsert_open_alert(
            db, device, alert_type="device_offline", severity=f["severity"], dedup_key=offline_dedup,
            title=f"{device.device_name} is offline", evidence=f["evidence"], explanation=f["explanation"], now=now,
        ))
        _auto_resolve_if_open(db, device, stale_dedup, now=now, note="superseded -- escalated to offline")
    elif "presence_stale" in findings_by_key:
        f = findings_by_key["presence_stale"]
        touched.append(_upsert_open_alert(
            db, device, alert_type="device_stale", severity=f["severity"], dedup_key=stale_dedup,
            title=f"{device.device_name} has not reported recently", evidence=f["evidence"], explanation=f["explanation"], now=now,
        ))
        _auto_resolve_if_open(db, device, offline_dedup, now=now, note="device is reporting again (recovered to stale, not yet fully online)")
    else:
        _auto_resolve_if_open(db, device, offline_dedup, now=now, note="device is online again")
        _auto_resolve_if_open(db, device, stale_dedup, now=now, note="device is online again")

    for rule_key, alert_type in (("disk_usage_high", "health_degraded"), ("battery_low", "health_degraded"), ("sync_queue_backlog", "sync_backlog")):
        dedup = f"{rule_key}:{device.id}"
        if rule_key in findings_by_key:
            f = findings_by_key[rule_key]
            touched.append(_upsert_open_alert(
                db, device, alert_type=alert_type, severity=f["severity"], dedup_key=dedup,
                title=f"{device.device_name}: {rule_key.replace('_', ' ')}", evidence=f["evidence"], explanation=f["explanation"], now=now,
            ))
        else:
            _auto_resolve_if_open(db, device, dedup, now=now, note="metric is back within the normal range")

    drift = fleet_config_service.compute_drift(db, device)
    drift_dedup = f"config_drift:{device.id}"
    if drift.get("evaluated") and drift.get("has_drift"):
        touched.append(_upsert_open_alert(
            db, device, alert_type="config_drift", severity="warning", dedup_key=drift_dedup,
            title=f"{device.device_name} configuration has drifted from its assigned baseline",
            evidence=drift, explanation=f"{len(drift['differences'])} configuration key(s) differ from the assigned baseline.", now=now,
        ))
    elif drift.get("evaluated"):
        _auto_resolve_if_open(db, device, drift_dedup, now=now, note="configuration matches the assigned baseline again")
    # drift["evaluated"] is False (no baseline assigned, or it was
    # deleted) -- deliberately leaves any existing open config_drift
    # alert untouched rather than auto-resolving it based on an
    # unevaluated condition.

    return touched


def evaluate_alerts_for_all_devices(db: Session, *, organization_id: Optional[str] = None, settings: Optional[Settings] = None, now: Optional[datetime] = None) -> dict:
    """The sweep that actually makes `device_offline`/`device_stale`
    detection possible -- see the module docstring's "Correctness note."
    Evaluates every Device (optionally scoped to one organization) even
    though none of them necessarily made any request this call. Mirrors
    `edge_sync_service.recover_stale_syncing_records`'s own shape: an
    explicit, operator/scheduler-triggered sweep, never an in-process
    background job. Returns a plain summary dict, never per-device
    detail (a caller wanting that can list `/fleet/alerts` afterward)."""
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    stmt = select(Device)
    if organization_id is not None:
        stmt = stmt.where(Device.organization_id == organization_id)
    devices = list(db.execute(stmt).scalars().all())
    alerts_touched = 0
    for device in devices:
        alerts_touched += len(evaluate_alerts_for_device(db, device, settings=settings, now=now))
    return {"evaluated_device_count": len(devices), "alerts_touched_count": alerts_touched}


def get_alert(db: Session, organization_id: str, alert_id: str) -> Optional[InfrastructureAlert]:
    stmt = select(InfrastructureAlert).where(InfrastructureAlert.id == alert_id, InfrastructureAlert.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_alerts_query(organization_id: str, *, status: Optional[str] = None, severity: Optional[str] = None, device_id: Optional[str] = None, alert_type: Optional[str] = None):
    stmt = select(InfrastructureAlert).where(InfrastructureAlert.organization_id == organization_id)
    if status:
        stmt = stmt.where(InfrastructureAlert.status == status)
    if severity:
        stmt = stmt.where(InfrastructureAlert.severity == severity)
    if device_id:
        stmt = stmt.where(InfrastructureAlert.device_id == device_id)
    if alert_type:
        stmt = stmt.where(InfrastructureAlert.alert_type == alert_type)
    return stmt.order_by(InfrastructureAlert.last_evaluated_at.desc())


def acknowledge_alert(db: Session, alert: InfrastructureAlert, *, actor_user_id: str, note: Optional[str] = None) -> InfrastructureAlert:
    if alert.status not in ("open", "reopened"):
        raise InvalidAlertTransitionError(f"cannot acknowledge an alert in status '{alert.status}'")
    alert.status = "acknowledged"
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by_user_id = actor_user_id
    db.add(alert)
    db.commit()
    db.refresh(alert)
    audit_service.record(
        db, action="fleet.alert_acknowledge", actor_user_id=actor_user_id, organization_id=alert.organization_id,
        target_type="infrastructure_alert", target_id=alert.id, context_metadata={"note": note},
    )
    db.commit()
    return alert


def resolve_alert(db: Session, alert: InfrastructureAlert, *, actor_user_id: str, note: Optional[str] = None) -> InfrastructureAlert:
    if alert.status not in ("open", "acknowledged", "reopened"):
        raise InvalidAlertTransitionError(f"cannot resolve an alert in status '{alert.status}'")
    alert.status = "resolved"
    alert.resolved_at = datetime.now(timezone.utc)
    alert.resolved_by_user_id = actor_user_id
    alert.resolution_note = note
    db.add(alert)
    db.commit()
    db.refresh(alert)
    audit_service.record(
        db, action="fleet.alert_resolve", actor_user_id=actor_user_id, organization_id=alert.organization_id,
        target_type="infrastructure_alert", target_id=alert.id, context_metadata={"note": note},
    )
    db.commit()
    return alert


def reopen_alert(db: Session, alert: InfrastructureAlert, *, actor_user_id: str, note: Optional[str] = None) -> InfrastructureAlert:
    """A human explicitly disagreeing with an auto-resolution (or a
    resolved condition recurring before the next automatic
    evaluation) -- never performed automatically."""
    if alert.status != "resolved":
        raise InvalidAlertTransitionError(f"cannot reopen an alert in status '{alert.status}' (only a resolved alert can be reopened)")
    alert.status = "reopened"
    alert.occurrence_count += 1
    alert.last_evaluated_at = datetime.now(timezone.utc)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    audit_service.record(
        db, action="fleet.alert_reopen", actor_user_id=actor_user_id, organization_id=alert.organization_id,
        target_type="infrastructure_alert", target_id=alert.id, context_metadata={"note": note},
    )
    db.commit()
    return alert
