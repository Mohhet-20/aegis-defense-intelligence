from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditRecord

logger = logging.getLogger("aegis.audit")

_SENSITIVE_EXACT = {
    "password", "new_password", "current_password", "password_hash", "secret", "secret_key", "api_key", "apikey",
    "authorization", "access_token", "refresh_token", "cookie", "x-device-api-key", "client_secret", "private_key",
}
_SENSITIVE_SUFFIXES = ("_password", "_secret", "_api_key", "_apikey", "_private_key")
_MAX_STR = 2000
_MAX_DEPTH = 6
REDACTED = "[REDACTED]"


def redact(value: Any, _depth: int = 0) -> Any:
    """Returns a copy of `value` with secret-looking keys masked and long
    strings truncated. Applied to every audit row's context_metadata so a
    caller that accidentally passes a request body cannot persist a
    password or token."""
    if _depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k)
            lk = key.lower()
            if lk in _SENSITIVE_EXACT or lk.endswith(_SENSITIVE_SUFFIXES):
                out[key] = REDACTED
            else:
                out[key] = redact(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in list(value)[:200]]
    if isinstance(value, str) and len(value) > _MAX_STR:
        return value[:_MAX_STR] + "...[truncated]"
    return value


def record(
    db: Session,
    *,
    action: str,
    actor_user_id: Optional[str],
    organization_id: Optional[str],
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: str = "success",
    request_id: Optional[str] = None,
    context_metadata: Optional[dict] = None,
) -> AuditRecord:
    """Writes one append-only audit row. Called by every mutating
    service (users, sources, investigations, ingestion, risk review) --
    never called from a route directly, so the action name stays
    consistent with whatever the service actually did. No function in
    this module updates or deletes an existing row."""
    # Reliability policy (documented, not configurable): the row is
    # added to the CALLER'S transaction, so if this write fails the exception
    # propagates and the audited change is rolled back with it ("fail
    # closed"). There is no silent best-effort path except the explicit
    # authz.denied recorder in app/core/security.py, which is allowed to
    # fail without masking the 403.
    entry = AuditRecord(
        action=action,
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        request_id=request_id,
        context_metadata=redact(context_metadata or {}),
    )
    db.add(entry)
    db.flush()
    return entry


def list_for_target(db: Session, organization_id: str, *, target_type: str, target_id: str) -> list[AuditRecord]:
    """The review-history view for a single relationship/conflict/
    assessment row (Section 11: "preserve historical
    decisions"). Deliberately reuses this append-only table rather than
    a parallel per-domain history log -- every analyst review action
    already calls `record()` above with the acting user, the prior/new
    state in `context_metadata`, and this exact (target_type, target_id)
    pair, so this is a real, complete history, not a partial one."""
    stmt = (
        select(AuditRecord)
        .where(
            AuditRecord.organization_id == organization_id,
            AuditRecord.target_type == target_type,
            AuditRecord.target_id == target_id,
        )
        .order_by(AuditRecord.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())


def build_query(
    organization_id: str,
    *,
    actor_user_id: Optional[str] = None,
    action: Optional[str] = None,
    action_prefix: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: Optional[str] = None,
    request_id: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
):
    """Org-scoped audit query. Rows with organization_id NULL (system-level
    events such as a login attempt for an unknown identifier) are NOT
    returned to any organization -- they exist only for operators with
    database access."""
    stmt = select(AuditRecord).where(AuditRecord.organization_id == organization_id)
    if actor_user_id:
        stmt = stmt.where(AuditRecord.actor_user_id == actor_user_id)
    if action:
        stmt = stmt.where(AuditRecord.action == action)
    if action_prefix:
        escaped = action_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(AuditRecord.action.like(escaped + "%", escape="\\"))
    if target_type:
        stmt = stmt.where(AuditRecord.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditRecord.target_id == target_id)
    if outcome:
        stmt = stmt.where(AuditRecord.outcome == outcome)
    if request_id:
        stmt = stmt.where(AuditRecord.request_id == request_id)
    if created_from:
        stmt = stmt.where(AuditRecord.created_at >= created_from)
    if created_to:
        stmt = stmt.where(AuditRecord.created_at <= created_to)
    return stmt.order_by(AuditRecord.created_at.desc(), AuditRecord.id.desc())


def distinct_actions(db: Session, organization_id: str) -> list[str]:
    rows = db.execute(
        select(AuditRecord.action).where(AuditRecord.organization_id == organization_id).distinct().order_by(AuditRecord.action).limit(500)
    ).scalars().all()
    return list(rows)
