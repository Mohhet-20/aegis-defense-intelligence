from __future__ import annotations

from typing import Optional

from sqlalchemy import JSON, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

AUDIT_OUTCOMES = ("success", "failure", "denied")


class AuditRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only. No API route updates or deletes a row of this
    table -- see docs/security/SECURITY_BASELINE.md "Audit history" for
    the explicit append-oriented-vs-tamper-evident distinction Section
    16 requires."""

    __tablename__ = "audit_records"

    organization_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    context_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditImmutableError(RuntimeError):
    """Raised when application code tries to UPDATE or DELETE an audit row
    through the ORM. This is an application-level guard only: raw SQL, bulk
    Core statements and anyone with direct database privileges can still
    modify the table (migration c-series adds DB triggers as a second
    layer, which a database administrator can also drop). See
    docs/security/AUDIT_GOVERNANCE.md."""


@event.listens_for(AuditRecord, "before_update")
def _block_audit_update(mapper, connection, target):  # noqa: ARG001
    raise AuditImmutableError("audit records are append-only and cannot be updated")


@event.listens_for(AuditRecord, "before_delete")
def _block_audit_delete(mapper, connection, target):  # noqa: ARG001
    raise AuditImmutableError("audit records are append-only and cannot be deleted")
