"""Report runs.

One table. A ReportRun is the durable record of one generated report: who asked,
for what window/filters/sections, what it contained (sample summary, caveats live
in the artifact), the integrity hash of the stored artifact and when it expires.
The artifact itself is a file in private report storage, never a public URL.

Honesty rules enforced by the service layer (and tested):
 * status becomes "completed" only after the artifact file is fully written and
   hashed; a failure leaves status "failed" with no artifact path;
 * expired reports keep their row (audit trail) but lose the file ("expired").
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

REPORT_STATUSES = ("running", "completed", "failed", "expired")
REPORT_FORMATS = ("json", "csv", "html")
REPORT_VISIBILITIES = ("private", "organization")


def _in(values: tuple) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ReportRun(Base, UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "report_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_report_runs_org_idempotency_key"),
        CheckConstraint(f"status IN ({_in(REPORT_STATUSES)})", name="ck_report_runs_status"),
        CheckConstraint(f"format IN ({_in(REPORT_FORMATS)})", name="ck_report_runs_format"),
        CheckConstraint(f"visibility IN ({_in(REPORT_VISIBILITIES)})", name="ck_report_runs_visibility"),
        Index("ix_report_runs_org_created", "organization_id", "created_at"),
        Index("ix_report_runs_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    template_key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)  # validated window, filters, sections, detail level
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # analyst-written commentary (plain text)
    required_permissions: Mapped[list] = mapped_column(JSON, default=list)  # a reader needs all of these
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(10), nullable=False)

    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    sample_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    section_status: Mapped[dict] = mapped_column(JSON, default=dict)  # section -> included | not_authorized | error
    artifact_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)  # file name inside private report storage
    artifact_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # integrity check of the stored bytes only
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_category: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
