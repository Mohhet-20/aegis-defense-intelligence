"""Standardized device health-finding rules.

Binding measurement-quality rules this module follows, verbatim from
the prompt:
  - Missing data stays missing -- a metric a device never reported
    produces NO finding for that metric, never a fabricated 0/100.
  - Stale vs fresh are distinguished -- every finding this module
    returns carries the `as_of` timestamp of the DeviceHealthReport it
    was computed from, so a caller can tell a finding is based on data
    from five minutes ago vs five hours ago.
  - Device-reported vs server-computed are distinguished -- every
    finding's `source` is either "device_reported" (the raw metric
    value came from the device itself, e.g. disk/battery percentage)
    or "server_computed" (the server derived the finding, e.g.
    presence/staleness, which the device cannot itself know from its
    own vantage point).

Rules are deliberately simple, explicit, and configurable via
app.core.config.Settings (FLEET_HEALTH_*) rather than hard-coded magic
numbers -- an operator can retune thresholds without a code change, and
every finding's `evidence` includes both the observed value and the
threshold it was compared against, so a finding is always independently
checkable, never just an opaque label.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.device import Device
from app.models.device_health_report import DeviceHealthReport
from app.services.fleet_presence_service import derive_presence_state

HEALTH_FINDING_SEVERITIES = ("info", "warning", "serious", "critical")


def get_latest_health_report(db: Session, device: Device) -> Optional[DeviceHealthReport]:
    stmt = (
        select(DeviceHealthReport)
        .where(DeviceHealthReport.organization_id == device.organization_id, DeviceHealthReport.device_id == device.id)
        .order_by(DeviceHealthReport.reported_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _metric_finding(rule_key: str, value: float, *, warning: float, critical: float, label: str, as_of: datetime, higher_is_worse: bool = True) -> Optional[dict]:
    if higher_is_worse:
        if value >= critical:
            severity = "critical"
        elif value >= warning:
            severity = "warning"
        else:
            return None
    else:
        if value <= critical:
            severity = "critical"
        elif value <= warning:
            severity = "warning"
        else:
            return None
    return {
        "rule_key": rule_key,
        "severity": severity,
        "source": "device_reported",
        "as_of": as_of,
        "evidence": {"value": value, "warning_threshold": warning, "critical_threshold": critical},
        "explanation": f"{label} is {value} (warning >= {warning}, critical >= {critical})" if higher_is_worse
        else f"{label} is {value} (warning <= {warning}, critical <= {critical})",
    }


def evaluate_health_findings(db: Session, device: Device, *, settings: Settings, now: Optional[datetime] = None) -> list[dict]:
    """Returns a list of findings for `device`, each a plain dict with
    keys: rule_key, severity, source, as_of, evidence, explanation.
    Never raises on a device with no health history at all -- it simply
    returns only the server-computed presence finding (or none)."""
    findings: list[dict] = []

    presence = derive_presence_state(device.last_seen_at, settings=settings, now=now)
    if presence == "offline":
        findings.append({
            "rule_key": "presence_offline",
            "severity": "critical",
            "source": "server_computed",
            "as_of": device.last_seen_at,
            "evidence": {"presence_state": presence, "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
                         "offline_after_seconds": settings.FLEET_PRESENCE_OFFLINE_AFTER_SECONDS},
            "explanation": "The device has not been seen within the configured offline threshold.",
        })
    elif presence == "stale":
        findings.append({
            "rule_key": "presence_stale",
            "severity": "warning",
            "source": "server_computed",
            "as_of": device.last_seen_at,
            "evidence": {"presence_state": presence, "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
                         "stale_after_seconds": settings.FLEET_PRESENCE_STALE_AFTER_SECONDS},
            "explanation": "The device has not been seen within the configured stale threshold, but is not yet considered offline.",
        })
    # presence == "online" or "unknown": no presence finding -- a brand
    # new device that has never reported produces no fabricated
    # "offline" finding either (Part 4: missing data stays missing).

    latest = get_latest_health_report(db, device)
    if latest is None:
        return findings

    metrics = latest.resource_metrics or {}

    disk_pct = metrics.get("disk_used_pct")
    if disk_pct is not None:
        finding = _metric_finding(
            "disk_usage_high", float(disk_pct), warning=settings.FLEET_HEALTH_DISK_WARNING_PCT,
            critical=settings.FLEET_HEALTH_DISK_CRITICAL_PCT, label="Disk used", as_of=latest.reported_at,
        )
        if finding:
            findings.append(finding)

    battery_pct = metrics.get("battery_pct")
    if battery_pct is not None:
        finding = _metric_finding(
            "battery_low", float(battery_pct), warning=settings.FLEET_HEALTH_BATTERY_WARNING_PCT,
            critical=settings.FLEET_HEALTH_BATTERY_CRITICAL_PCT, label="Battery", as_of=latest.reported_at, higher_is_worse=False,
        )
        if finding:
            findings.append(finding)

    if latest.queue_depth is not None:
        finding = _metric_finding(
            "sync_queue_backlog", float(latest.queue_depth), warning=float(settings.FLEET_HEALTH_QUEUE_DEPTH_WARNING),
            critical=float(settings.FLEET_HEALTH_QUEUE_DEPTH_CRITICAL), label="Local sync queue depth", as_of=latest.reported_at,
        )
        if finding:
            findings.append(finding)

    return findings
