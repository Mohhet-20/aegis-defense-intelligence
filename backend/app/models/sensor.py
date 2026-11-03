from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime
from app.models.mixins import GeoLocationMixin

# Phase 1's original simple connectivity flag. Kept exactly as-is for
# backward compatibility with every existing route/test/seed row --
# see `lifecycle_status` below for the richer Phase 6 state machine.
# This field is NOT removed or repurposed; it continues to mean exactly
# what it meant in Phase 1.
SENSOR_STATUSES = ("active", "inactive", "fault", "unknown")

# Phase 6 sensor lifecycle. Deliberately a SEPARATE field
# from `status` above -- collapsing them would either break every
# existing caller of `status` or silently redefine what "active" meant
# for a Phase-1 sensor that never opted into the richer model.
#
# Explicit, documented transition rules (enforced in
# app/services/sensor_service.py / app/services/sensor_health_service.py,
# never left implicit):
#   registered  -> active       first valid observation is ingested.
#   active      -> degraded     measurement quality or anomaly rate
#                                crosses a configured threshold while
#                                observations are still arriving.
#   active      -> offline      no valid observation within the
#                                configured heartbeat window.
#   degraded    -> active       quality/anomaly rate recovers.
#   degraded    -> offline      heartbeat window also elapses.
#   offline     -> active       a new valid observation arrives.
#   *           -> maintenance  explicit analyst action only -- never
#                                inferred from data.
#   maintenance -> active       explicit analyst action only.
#   *           -> retired      explicit analyst action only; terminal
#                                -- a retired sensor accepts no further
#                                observation batches (enforced in
#                                sensor_ingestion_service.py), but its
#                                historical data remains fully queryable
#                                ("a disconnected sensor may
#                                still have historical data available").
SENSOR_LIFECYCLE_STATUSES = ("registered", "active", "degraded", "offline", "maintenance", "retired")

# A move INTO maintenance or retired is always an explicit analyst
# action (never computed by the health service); every other
# transition above is computed. This set is what
# sensor_service.transition_lifecycle_status() consults to decide
# whether a transition requires `actor_user_id`.
SENSOR_LIFECYCLE_MANUAL_ONLY_TARGETS = ("maintenance", "retired")


class Sensor(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, GeoLocationMixin):
    """Registry foundation extended in Phase 6 with the
    richer metadata/lifecycle fields docs/architecture/
    MULTISENSOR_CONTRACTS.md promised: category/subtype, manufacturer/
    model, configured measurement types and units, operating range,
    nominal sampling interval, expected data format, and an explicit
    lifecycle state machine distinct from the legacy `status` flag.

    This model still stores identity/configuration, not COMPUTED
    health -- health/quality are always derived on demand by
    app/services/sensor_health_service.py from this sensor's own
    Observation rows, never cached here (same "no stale summary"
    principle app/services/quality_service.py already established)."""

    __tablename__ = "sensors"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sensor_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown", index=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    config_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    capability_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Phase 6 additions (richer registry metadata) -----

    # Broad grouping distinct from `sensor_type` (which Phase 1 already
    # uses as a free-text subtype, e.g. "camera"/"gps"/"environmental").
    # Nullable -- an existing Phase 1 sensor has no category until an
    # analyst sets one; never backfilled with a guess.
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    asset_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)

    # Configured measurement types this sensor is authorized/expected to
    # report (e.g. ["temperature_c", "battery_voltage"]). An empty list
    # means "not yet configured" -- the quality/analytics engines treat
    # an unconfigured measurement type as "no validation rule exists
    # for this," never as an automatic rejection.
    measurement_types: Mapped[list] = mapped_column(JSON, default=list)
    # measurement_type -> unit string, e.g. {"temperature_c": "celsius"}.
    measurement_units: Mapped[dict] = mapped_column(JSON, default=dict)
    # measurement_type -> {"min": float, "max": float}. Only checked
    # when both bounds are present for that type.
    operating_range: Mapped[dict] = mapped_column(JSON, default=dict)
    nominal_sampling_interval_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_data_format: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sensor_timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC")

    lifecycle_status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered", index=True)
    last_ingestion_success_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    # "explicit device-reported health state, if supplied."
    # Populated ONLY when an ingested record's payload explicitly
    # carries a device-reported status field -- never inferred from
    # connectivity or quality. See app/sensors/ingestion.py.
    device_reported_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    device_reported_status_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    retired_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    retired_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
