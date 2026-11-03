"""ObservationAnomaly. A persisted, explainable
STATISTICAL anomaly candidate -- never a threat classification. Mirrors
the review-field shape RiskAssessment and EvidenceRelationship
 already established: a mutable review_status/reviewed_by/
reviewed_at/review_note set, never a supersede chain, because reviewing
an anomaly candidate corrects an ANALYST'S INTERPRETATION OF IT, not the
underlying measurement (the Observation row itself is never rewritten).

`category` keeps Section 9's required separation explicit and queryable:
a rolling-window deviation is a "statistical_deviation"; a repeated-value
or sampling-gap finding is a "data_quality" issue; a missing-heartbeat
finding is a "sensor_health" warning; only an analyst's own review action
can ever set category to "analyst_confirmed" (see anomaly_service.py) --
nothing here ever computes that category on its own.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

# Heuristic, documented detection methods only -- Section 9 explicitly
# forbids unsupported machine-learning claims. Each is implemented in
# app/sensors/anomaly.py and versioned independently via `method_version`.
ANOMALY_DETECTION_METHODS = (
    "range_violation",
    "rolling_zscore",
    "median_absolute_deviation",
    "rate_of_change",
    "missing_heartbeat",
    "repeated_value",
    "sampling_gap",
)

# Section 9's explicit separation -- never collapsed into one score.
ANOMALY_CATEGORIES = ("statistical_deviation", "data_quality", "sensor_health", "analyst_confirmed")

# A DATA-QUALITY severity policy, never a threat/hostility scale.
# Explicitly excludes any "critical"/"threat"-sounding term (Section 9:
# "do not label anomalies as threats").
ANOMALY_SEVERITIES = ("info", "low", "medium", "high")

ANOMALY_REVIEW_STATUSES = (
    "unreviewed",
    "confirmed_unusual",
    "data_quality_issue",
    "expected_known_context",
    "unresolved",
)


class ObservationAnomaly(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "observation_anomalies"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    sensor_id: Mapped[str] = mapped_column(String(36), ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False, index=True)
    measurement_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # The single observation this candidate is anchored to, when the
    # method is point-based (range_violation, rolling_zscore, mad,
    # rate_of_change, repeated_value). NULL for a window-based finding
    # (missing_heartbeat, sampling_gap) that has no single triggering row.
    observation_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("observations.id", ondelete="SET NULL"), nullable=True, index=True)
    window_start: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    window_end: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    detection_method: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    method_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    # The exact threshold/window configuration USED for this run --
    # Section 9's "support configuration and version tracking so
    # results can be reproduced."
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    observed_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    # None (not {}) when there was insufficient history to compute one
    # -- app/sensors/anomaly.py never fabricates a baseline.
    baseline_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    explanation: Mapped[str] = mapped_column(String(2000), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="low", index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    quality_flags: Mapped[list] = mapped_column(JSON, default=list)

    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unreviewed", index=True)
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
