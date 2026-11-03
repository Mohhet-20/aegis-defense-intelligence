from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

INGESTION_JOB_STATUSES = ("running", "completed", "completed_with_errors", "failed", "cancelled")
INGESTION_JOB_TYPES = ("json_upload", "csv_upload", "http_api", "synthetic_demo")

# How the job came to exist -- "manual" (an analyst's upload/run),
# "retry" (a re-run of a previous failed/partial job), "api" (a
# connector-driven run triggered through the API, not a human upload).
# A scheduler/cron trigger type is left for when a real scheduler
# exists ("don't add a new queue without concrete need").
INGESTION_JOB_TRIGGER_TYPES = ("manual", "retry", "api")


class IngestionJob(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "ingestion_jobs"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running", index=True)

    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Per-record error reasons (never the raw uploaded payload --
    # Section 10 requirement 14 / SECURITY_BASELINE.md "Sensitive logging").
    error_summary: Mapped[list] = mapped_column(JSON, default=list)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)

    # --- Section 10: job orchestration --------------
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Propagates the request's correlation id (app.core.middleware) into
    # structured logs/observability for this job -- lets an operator
    # trace "this HTTP request" through to "this job's log lines."
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
