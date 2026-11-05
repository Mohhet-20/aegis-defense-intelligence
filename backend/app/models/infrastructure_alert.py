"""Fleet infrastructure alerts. Deliberately a
SEPARATE model/queue from intelligence `Event`s, `ObservationAnomaly`
candidates, and `RiskAssessment`/threat records -- this table is about
the HEALTH OF THE FLEET ITSELF (a device went offline, a config drifted
from baseline, disk is nearly full), never about a sensed real-world
condition. The two concerns never share a table, a service, or a review
queue, the same deliberate separation drew between
`SyncConflict` (sync-protocol concern) and the `Conflict`
(event-fusion concern). See docs/operations/INFRASTRUCTURE_ALERTS.md.

Deduplication is enforced in the SERVICE layer, not by a DB unique
constraint (see fleet_alert_service.py's `evaluate_alerts_for_device`):
before creating a row it looks up the current open/acknowledged row for
the same (organization, dedup_key) and, if one exists, updates it in
place (`last_evaluated_at`, `occurrence_count`) instead of inserting a
duplicate. A dedup_key is free to recur across TIME -- once a condition
is resolved and later reoccurs, a brand new row is created so the alert
history shows each distinct occurrence rather than silently reusing a
closed one (no DB-level uniqueness is placed on dedup_key alone, since
that would make it impossible to ever record a second occurrence of the
same condition after the first was resolved).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

INFRA_ALERT_SEVERITIES = ("info", "warning", "serious", "critical")
INFRA_ALERT_STATUSES = ("open", "acknowledged", "resolved", "reopened")
INFRA_ALERT_TYPES = (
    "device_offline", "device_stale", "health_degraded", "config_drift",
    "sync_backlog", "capability_unhealthy",
)


class InfrastructureAlert(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "infrastructure_alerts"
    __table_args__ = (
        Index("ix_infra_alerts_org_dedup_key", "organization_id", "dedup_key"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=True, index=True)

    alert_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)

    # A stable key identifying "this ongoing condition" independent of
    # severity escalation -- e.g. "device_offline:{device_id}". Repeated
    # rule evaluation of the same condition updates the existing open
    # row rather than creating a duplicate; see module docstring.
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    acknowledged_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    resolved_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
