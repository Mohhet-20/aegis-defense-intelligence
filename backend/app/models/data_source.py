from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

DATA_SOURCE_STATUSES = ("active", "inactive", "error")

# How records reach this source. "file_upload" sources only ever
# receive a JSON/CSV upload; "polling" sources have a connector that
# can be "run" to fetch a fresh batch (http_api, synthetic_demo);
# "push" is reserved for a future inbound-webhook adapter; "internal"
# is another part of this same application. Documentation only --
# not DB-enforced, so existing Phase 1 sources never need a backfill.
DATA_SOURCE_CONNECTION_MODES = ("file_upload", "polling", "push", "internal")


class DataSource(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    """A registered origin of events/observations. Section 7: non-secret
    configuration metadata only -- credentials for a real connector
    belong in environment-managed secrets, never this JSON column."""

    __tablename__ = "data_sources"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)

    # Phase 3 (fusion) will compute/consume this; Phase 1 only stores a
    # configured starting weight -- see docs/architecture/MULTISENSOR_CONTRACTS.md.
    reliability_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    last_ingestion_attempt_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    last_ingestion_success_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    config_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Section 3: extend the source registry ------

    # Free-text "who owns this" -- never an auth mechanism, purely for
    # the registry UI/API to answer "who do I ask about this source."
    owner_team: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    connection_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="file_upload")

    # A disabled source is excluded from "run this source" and from
    # new ingestion jobs, but its history/config remain visible --
    # disabling is reversible and never deletes anything.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # The most recent connector error CATEGORY only (never the raw
    # error text, which may embed response bodies) -- enough for a
    # dashboard to show "this source is failing," never a payload leak.
    last_error_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Bumped every time config_metadata changes -- lets provenance
    # record "which version of the source's configuration produced
    # this batch" without duplicating the whole config into every job.
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Checkpoint for connectors with a reliable cursor.
    # Written ONLY after a batch's records are committed -- never
    # advanced speculatively -- so a crashed job safely re-fetches
    # from the last successful checkpoint rather than skipping records.
    last_checkpoint_cursor: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_checkpoint_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
