"""Investigation lifecycle + access (the fusion layer CRUD, extended).

Authorization lives here, at the data-access boundary: every lookup is
org-scoped (cross-org -> not found) and a `is_restricted` investigation is
only visible to its owner, explicit members and administrators. Functions
that change several rows only flush; the route commits once so the change,
its history row and its audit event succeed or fail together.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Role
from app.models.investigation import INVESTIGATION_TRANSITIONS, Investigation
from app.models.investigation_workspace import (
    MEMBER_ROLES,
    InvestigationMember,
    InvestigationStatusHistory,
)
from app.models.user import User
from app.services import audit_service
from app.services.workspace_errors import conflict, invalid, not_found

SORT_COLUMNS = {
    "created_at": Investigation.created_at,
    "updated_at": Investigation.updated_at,
    "title": Investigation.title,
    "priority": Investigation.priority,
    "status": Investigation.status,
}


def _member_exists(db: Session, investigation_id: str, user_id: str) -> bool:
    return (
        db.scalar(
            select(InvestigationMember.id).where(
                InvestigationMember.investigation_id == investigation_id, InvestigationMember.user_id == user_id
            )
        )
        is not None
    )


def user_can_access(db: Session, user: AuthenticatedUser, investigation: Investigation) -> bool:
    if investigation.organization_id != user.organization_id:
        return False
    if not investigation.is_restricted:
        return True
    if user.role == Role.ADMINISTRATOR or investigation.assigned_user_id == user.id:
        return True
    return _member_exists(db, investigation.id, user.id)


def _assert_org_users(db: Session, organization_id: str, user_ids: list[str]) -> None:
    ids = {u for u in user_ids if u}
    if not ids:
        return
    found = set(db.execute(select(User.id).where(User.id.in_(ids), User.organization_id == organization_id)).scalars())
    missing = ids - found
    if missing:
        raise invalid(f"Unknown user id(s) for this organization: {sorted(missing)}")


def create_investigation(db: Session, *, organization_id: str, actor_user_id: Optional[str] = None, **fields) -> Investigation:
    _assert_org_users(db, organization_id, [fields.get("assigned_user_id")] + list(fields.get("collaborator_user_ids") or []))
    initial = fields.pop("initial_status", "open") or "open"
    if initial not in ("draft", "open"):
        raise invalid("initial_status must be 'draft' or 'open'")
    investigation = Investigation(organization_id=organization_id, status=initial, **fields)
    db.add(investigation)
    db.flush()
    db.add(
        InvestigationStatusHistory(
            organization_id=organization_id, investigation_id=investigation.id, from_status=None,
            to_status=initial, reason="created", changed_by_user_id=actor_user_id,
        )
    )
    db.flush()
    return investigation


def get_investigation(db: Session, organization_id: str, investigation_id: str) -> Optional[Investigation]:
    """Org-scoped lookup WITHOUT the per-investigation restriction check.
    Request handlers should use get_accessible()."""
    stmt = select(Investigation).where(Investigation.id == investigation_id, Investigation.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def get_accessible(db: Session, user: AuthenticatedUser, investigation_id: str) -> Investigation:
    inv = get_investigation(db, user.organization_id, investigation_id)
    if inv is None or not user_can_access(db, user, inv):
        raise not_found("Investigation")  # same answer for 'missing' and 'not yours'
    return inv


def list_investigations_query(
    organization_id: str,
    *,
    status: Optional[str] = None,
    user: Optional[AuthenticatedUser] = None,
    priority: Optional[str] = None,
    q: Optional[str] = None,
    tag: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    reviewer_user_id: Optional[str] = None,
    include_archived: bool = False,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
):
    stmt = select(Investigation).where(Investigation.organization_id == organization_id)
    if status:
        stmt = stmt.where(Investigation.status == status)
    elif not include_archived:
        stmt = stmt.where(Investigation.status != "archived")
    if priority:
        stmt = stmt.where(Investigation.priority == priority)
    if assigned_user_id:
        stmt = stmt.where(Investigation.assigned_user_id == assigned_user_id)
    if reviewer_user_id:
        stmt = stmt.where(
            Investigation.id.in_(
                select(InvestigationMember.investigation_id).where(
                    InvestigationMember.user_id == reviewer_user_id, InvestigationMember.role == "reviewer"
                )
            )
        )
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Investigation.title).like(like), func.lower(func.coalesce(Investigation.description, "")).like(like)))
    if tag:
        # JSON list membership; portable substring match on the serialized list
        stmt = stmt.where(func.lower(cast(Investigation.tags, String)).like(f'%"{tag.strip().lower()}"%'))
    if user is not None and user.role != Role.ADMINISTRATOR:
        stmt = stmt.where(
            or_(
                Investigation.is_restricted.is_(False),
                Investigation.assigned_user_id == user.id,
                Investigation.id.in_(select(InvestigationMember.investigation_id).where(InvestigationMember.user_id == user.id)),
            )
        )
    col = SORT_COLUMNS.get(sort_by, Investigation.created_at)
    stmt = stmt.order_by(col.asc() if sort_dir == "asc" else col.desc(), Investigation.id.asc())
    return stmt


def transition(
    db: Session,
    investigation: Investigation,
    *,
    to_status: str,
    actor_user_id: str,
    reason: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Investigation:
    from_status = investigation.status
    if to_status == from_status:
        raise conflict(f"Investigation is already '{to_status}'")
    allowed = INVESTIGATION_TRANSITIONS.get(from_status, ())
    if to_status not in allowed:
        raise conflict(f"Transition '{from_status}' -> '{to_status}' is not allowed (allowed from '{from_status}': {list(allowed) or 'none'})")
    now = datetime.now(timezone.utc)
    if to_status == "closed":
        reason = (reason or investigation.resolution_notes or "").strip()
        if not reason:
            raise invalid("Closing an investigation requires a closure reason")
        investigation.closure_reason = reason[:2000]
        investigation.closed_at = now
    elif to_status == "archived":
        investigation.archived_at = now
    elif from_status == "closed" and to_status == "open":
        investigation.closed_at = None  # reopened; the earlier closure stays in status history
    investigation.status = to_status
    db.add(investigation)
    db.add(
        InvestigationStatusHistory(
            organization_id=investigation.organization_id, investigation_id=investigation.id,
            from_status=from_status, to_status=to_status, reason=(reason or None), changed_by_user_id=actor_user_id,
        )
    )
    audit_service.record(
        db, action="investigation.transition", actor_user_id=actor_user_id, organization_id=investigation.organization_id,
        target_type="investigation", target_id=investigation.id, request_id=request_id,
        context_metadata={"from": from_status, "to": to_status, "reason": reason},
    )
    db.flush()
    return investigation


def assert_mutable(investigation: Investigation) -> None:
    if investigation.status == "archived":
        raise conflict("Investigation is archived and read-only")


_PLAIN_FIELDS = (
    "title", "description", "priority", "linked_event_ids", "evidence_refs", "review_status",
    "resolution_notes", "purpose", "scope", "collaborator_user_ids", "tags", "is_restricted", "assigned_user_id",
)


def update_investigation(
    db: Session,
    investigation: Investigation,
    *,
    actor_user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    status: Optional[str] = None,
    closure_reason: Optional[str] = None,
    **fields,
) -> Investigation:
    if investigation.status == "archived" and (status is None or status == "archived"):
        raise conflict("Investigation is archived and read-only")
    _assert_org_users(
        db, investigation.organization_id,
        [fields.get("assigned_user_id")] + list(fields.get("collaborator_user_ids") or []),
    )
    for key in _PLAIN_FIELDS:
        value = fields.get(key)
        if value is not None:
            setattr(investigation, key, value)
    db.add(investigation)
    if status is not None and status != investigation.status:
        transition(
            db, investigation, to_status=status, actor_user_id=actor_user_id or "",
            reason=closure_reason or fields.get("resolution_notes"), request_id=request_id,
        )
    db.flush()
    return investigation


# ---- membership ---------------------------------------------------------

def list_members(db: Session, investigation: Investigation) -> list[InvestigationMember]:
    return list(
        db.execute(
            select(InvestigationMember)
            .where(InvestigationMember.investigation_id == investigation.id)
            .order_by(InvestigationMember.created_at.asc(), InvestigationMember.id.asc())
        ).scalars()
    )


def add_member(db: Session, investigation: Investigation, *, user_id: str, role: str, actor_user_id: str, request_id: Optional[str] = None) -> InvestigationMember:
    if role not in MEMBER_ROLES:
        raise invalid(f"role must be one of {MEMBER_ROLES}")
    assert_mutable(investigation)
    _assert_org_users(db, investigation.organization_id, [user_id])
    existing = db.execute(
        select(InvestigationMember).where(InvestigationMember.investigation_id == investigation.id, InvestigationMember.user_id == user_id)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.role == role:
            raise conflict("User is already a member with that role")
        previous = existing.role
        existing.role = role
        db.add(existing)
        audit_service.record(
            db, action="investigation.member_role_change", actor_user_id=actor_user_id, organization_id=investigation.organization_id,
            target_type="investigation", target_id=investigation.id, request_id=request_id,
            context_metadata={"user_id": user_id, "from": previous, "to": role},
        )
        db.flush()
        return existing
    member = InvestigationMember(
        organization_id=investigation.organization_id, investigation_id=investigation.id, user_id=user_id,
        role=role, added_by_user_id=actor_user_id,
    )
    db.add(member)
    audit_service.record(
        db, action="investigation.member_add", actor_user_id=actor_user_id, organization_id=investigation.organization_id,
        target_type="investigation", target_id=investigation.id, request_id=request_id,
        context_metadata={"user_id": user_id, "role": role},
    )
    db.flush()
    return member


def remove_member(db: Session, investigation: Investigation, *, user_id: str, actor_user_id: str, request_id: Optional[str] = None) -> None:
    assert_mutable(investigation)
    member = db.execute(
        select(InvestigationMember).where(InvestigationMember.investigation_id == investigation.id, InvestigationMember.user_id == user_id)
    ).scalar_one_or_none()
    if member is None:
        raise not_found("Member")
    db.delete(member)
    audit_service.record(
        db, action="investigation.member_remove", actor_user_id=actor_user_id, organization_id=investigation.organization_id,
        target_type="investigation", target_id=investigation.id, request_id=request_id, context_metadata={"user_id": user_id},
    )
    db.flush()


def list_status_history(db: Session, investigation: Investigation) -> list[InvestigationStatusHistory]:
    return list(
        db.execute(
            select(InvestigationStatusHistory)
            .where(InvestigationStatusHistory.investigation_id == investigation.id)
            .order_by(InvestigationStatusHistory.created_at.asc(), InvestigationStatusHistory.id.asc())
        ).scalars()
    )
