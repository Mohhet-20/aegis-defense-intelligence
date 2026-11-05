from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime
from app.models.mixins import GeoLocationMixin

OBSERVATION_PROCESSING_STATUSES = ("ingested", "associated", "archived")
OBSERVATION_DATA_ORIGINS = ("synthetic_demo", "user_upload")

# Canonical validation/quality classification.
# Deliberately a flat, documented set rather than a single pass/fail
# bit -- "Valid with warnings" and "stale" are NOT the same thing as
# "invalid" (a validation failure vs. an unusual-but-maybe-valid
# measurement, Section 6's own required distinction).
OBSERVATION_VALIDATION_STATUSES = (
    "valid",
    "valid_with_warnings",
    "invalid",
    "stale",
    "duplicate",
    "incomplete",
    "out_of_range",
)

# Bumped whenever a change to how a canonical sensor observation is
# validated/normalized would affect how an already-stored row should be
# interpreted. Stored on every row (Section 4, requirement 9: "version
# the canonical schema").
SENSOR_OBSERVATION_SCHEMA_VERSION = "1.0"


class Observation(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, GeoLocationMixin):
    """Canonical sensor observation (storage shape, extended in
    Per docs/data/CANONICAL_SENSOR_OBSERVATION.md).

    `observation_type` doubles as the measurement type identifier for
    numeric telemetry (e.g. "temperature_c") -- does not add a
    second, redundant "measurement_type" column; the existing column is
    reused and documented. `payload` remains the generic structured
    value (used as-is by the non-numeric "detection_summary"
    rows); `measurement_value`/`unit` below are the EXPLICIT numeric
    fields the statistics/anomaly engines operate on -- they
    are None for a structured-only observation, never a fabricated 0.

    Event time (`observed_at`) and ingestion time (`ingested_at`) are
    always distinct columns, mirroring Event's own observed_at/
    ingested_at split (Section 4, requirement 1)."""

    __tablename__ = "observations"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    sensor_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("sensors.id", ondelete="SET NULL"), nullable=True, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True, index=True)

    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    observation_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    quality_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    processing_status: Mapped[str] = mapped_column(String(20), nullable=False, default="ingested")
    data_origin: Mapped[str] = mapped_column(String(30), nullable=False)

    # --- Additions (canonical observation schema) -

    # Ingestion time, distinct from observed_at above. Nullable at the
    # DB level only so the three original seed rows (predating this
    # column) remain valid without a backfill migration; the ingestion
    # service ALWAYS sets this for every row it creates.
    ingested_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True, index=True)

    measurement_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    validation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="valid", index=True)
    # List of short machine-readable flag codes, e.g. ["stale",
    # "out_of_range"] -- see app/sensors/quality.py for the closed set.
    quality_flags: Mapped[list] = mapped_column(JSON, default=list)

    # The RawRecord this canonical observation was normalized from.
    # NULL for the three original seed rows (created directly, not via
    # the ingestion pipeline) and for any future hand-created
    # observation -- Section 4 requires PRESERVING the source record
    # when one exists, not requiring one to exist.
    source_record_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("raw_records.id", ondelete="SET NULL"), nullable=True, index=True)
    ingestion_job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), nullable=True, index=True)

    schema_version: Mapped[str] = mapped_column(String(10), nullable=False, default=SENSOR_OBSERVATION_SCHEMA_VERSION)

    # Both NULL unless the source itself documented them -- Section 4's
    # "do not invent uncertainty, calibration, precision, or accuracy
    # metadata when the source does not provide it." See
    # app/sensors/units.py for the one place calibration_metadata is
    # ever populated (a documented, versioned unit conversion).
    calibration_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    uncertainty_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
