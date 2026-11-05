"""Notes and annotations.

Notes are separate rows that point at an investigation (and optionally an
evidence item); they never modify the evidence or any model output. Every
edit bumps `version` and appends a full-content revision. Edits require the
caller's `expected_version`; a stale value is rejected with 409 so a
concurrent edit is never silently overwritten.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Role
from app.models.evidence import Evidence
from app.models.investigation import Investigation
from app.models.investigation_workspace import (
    NOTE_KINDS,
    NOTE_RESOLUTION_STATUSES,
    InvestigationLink,
    InvestigationNote,
    InvestigationNoteRevision,
)
from app.models.user import User
from app.services import audit_service
from app.services.investigation_service import assert_mutable
from app.services.workspace_errors import conflict, forbidden, invalid, not_found

KIND_DESCRIPTIONS = {
    "observed_fact": "Something directly observed in a record.",
    "analyst_interpretation": "An analyst's reading of the records; may be wrong.",
    "hypothesis": "An unresolved possibility that has not been confirmed.",
    "review_question": "A question that needs an answer; can be assigned and resolved.",
}


def _clean_tags(tags) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        t = str(t).strip().lower()
        if t and len(t) <= 50 and t not in out:
            out.append(t)
    if len(out) > 20:
        raise invalid("At most 20 tags per note")
    return out


def _check_user(db: Session, org: str, user_id: Optional[str]) -> None:
    if user_id and db.scalar(select(User.id).where(User.id == user_id, User.organization_id == org)) is None:
        raise invalid("Unknown assignee for this organization")


def _revision(db: Session, note: InvestigationNote, actor_id: str, summary: Optional[str]) -> None:
    db.add(InvestigationNoteRevision(
        organization_id=note.organization_id, note_id=note.id, version=note.version, note_kind=note.note_kind,
        body=note.body, tags=list(note.tags or []), changed_by_user_id=actor_id, change_summary=summary,
    ))


def get_note(db: Session, investigation: Investigation, note_id: str) -> InvestigationNote:
    note = db.execute(select(InvestigationNote).where(
        InvestigationNote.id == note_id, InvestigationNote.investigation_id == investigation.id,
        InvestigationNote.organization_id == investigation.organization_id)).scalar_one_or_none()
    if note is None:
        raise not_found("Note")
    return note


def create_note(
    db: Session, investigation: Investigation, *, actor_user_id: str, body: str, note_kind: str,
    tags=None, category: Optional[str] = None, evidence_id: Optional[str] = None,
    parent_note_id: Optional[str] = None, assignee_user_id: Optional[str] = None, request_id: Optional[str] = None,
) -> InvestigationNote:
    assert_mutable(investigation)
    if note_kind not in NOTE_KINDS:
        raise invalid(f"note_kind must be one of {NOTE_KINDS}")
    body = (body or "").strip()
    if not body:
        raise invalid("Note body must not be empty")
    org = investigation.organization_id
    if evidence_id:
        ev = db.execute(select(Evidence).where(Evidence.id == evidence_id, Evidence.organization_id == org)).scalar_one_or_none()
        linked = db.scalar(select(InvestigationLink.id).where(
            InvestigationLink.investigation_id == investigation.id, InvestigationLink.record_type == "evidence",
            InvestigationLink.record_id == evidence_id))
        if ev is None or linked is None:
            raise invalid("evidence_id must be evidence linked to this investigation")
    if parent_note_id:
        parent = get_note(db, investigation, parent_note_id)
        if parent.parent_note_id:
            raise invalid("Replies can only be one level deep")
        evidence_id = evidence_id or parent.evidence_id
    _check_user(db, org, assignee_user_id)
    if assignee_user_id and note_kind != "review_question":
        raise invalid("Only review questions can be assigned")
    note = InvestigationNote(
        organization_id=org, investigation_id=investigation.id, evidence_id=evidence_id, parent_note_id=parent_note_id,
        note_kind=note_kind, body=body, tags=_clean_tags(tags), category=(category or None), author_user_id=actor_user_id,
        assignee_user_id=assignee_user_id, resolution_status=("open" if note_kind == "review_question" else None), version=1,
    )
    db.add(note)
    db.flush()
    _revision(db, note, actor_user_id, "created")
    audit_service.record(
        db, action="investigation.note_create", actor_user_id=actor_user_id, organization_id=org,
        target_type="investigation_note", target_id=note.id, request_id=request_id,
        context_metadata={"investigation_id": investigation.id, "note_kind": note_kind, "evidence_id": evidence_id},
    )
    db.flush()
    return note


def update_note(
    db: Session, investigation: Investigation, note: InvestigationNote, *, user: AuthenticatedUser, expected_version: int,
    body: Optional[str] = None, note_kind: Optional[str] = None, tags=None, category: Optional[str] = None,
    assignee_user_id: Optional[str] = None, resolution_status: Optional[str] = None, change_summary: Optional[str] = None,
    request_id: Optional[str] = None,
) -> InvestigationNote:
    assert_mutable(investigation)
    if note.version != expected_version:
        raise conflict(f"Note was changed by someone else (current version {note.version}, you edited {expected_version}). Reload and retry.")
    content_edit = body is not None or note_kind is not None or tags is not None
    if content_edit and note.author_user_id != user.id and user.role != Role.ADMINISTRATOR:
        raise forbidden("Only the note's author (or an administrator) can edit its content")
    changed: dict = {}
    if body is not None:
        body = body.strip()
        if not body:
            raise invalid("Note body must not be empty")
        if body != note.body:
            changed["body"] = True
            note.body = body
    if note_kind is not None and note_kind != note.note_kind:
        if note_kind not in NOTE_KINDS:
            raise invalid(f"note_kind must be one of {NOTE_KINDS}")
        changed["note_kind"] = [note.note_kind, note_kind]
        note.note_kind = note_kind
        if note_kind != "review_question":
            note.assignee_user_id, note.resolution_status = None, None
        elif note.resolution_status is None:
            note.resolution_status = "open"
    if tags is not None:
        new_tags = _clean_tags(tags)
        if new_tags != list(note.tags or []):
            changed["tags"] = True
            note.tags = new_tags
    if category is not None:
        note.category = category or None
        changed["category"] = True
    if assignee_user_id is not None:
        if note.note_kind != "review_question":
            raise invalid("Only review questions can be assigned")
        _check_user(db, note.organization_id, assignee_user_id)
        note.assignee_user_id = assignee_user_id
        changed["assignee"] = assignee_user_id
    if resolution_status is not None:
        if note.note_kind != "review_question":
            raise invalid("Only review questions have a resolution status")
        if resolution_status not in NOTE_RESOLUTION_STATUSES:
            raise invalid(f"resolution_status must be one of {NOTE_RESOLUTION_STATUSES}")
        changed["resolution_status"] = [note.resolution_status, resolution_status]
        note.resolution_status = resolution_status
        if resolution_status == "open":
            note.resolved_by_user_id, note.resolved_at = None, None
        else:
            note.resolved_by_user_id, note.resolved_at = user.id, datetime.now(timezone.utc)
    if not changed:
        raise invalid("No changes supplied")
    note.version += 1
    db.add(note)
    _revision(db, note, user.id, change_summary)
    audit_service.record(
        db, action="investigation.note_update", actor_user_id=user.id, organization_id=note.organization_id,
        target_type="investigation_note", target_id=note.id, request_id=request_id,
        context_metadata={"investigation_id": investigation.id, "new_version": note.version, "changed": sorted(changed)},
    )
    db.flush()
    return note


def list_notes(db: Session, investigation: Investigation, *, evidence_id: Optional[str] = None, note_kind: Optional[str] = None,
               unresolved_only: bool = False, tag: Optional[str] = None) -> list[InvestigationNote]:
    stmt = select(InvestigationNote).where(InvestigationNote.investigation_id == investigation.id)
    if evidence_id:
        stmt = stmt.where(InvestigationNote.evidence_id == evidence_id)
    if note_kind:
        stmt = stmt.where(InvestigationNote.note_kind == note_kind)
    if unresolved_only:
        stmt = stmt.where(InvestigationNote.note_kind == "review_question", InvestigationNote.resolution_status == "open")
    rows = list(db.execute(stmt.order_by(InvestigationNote.created_at.asc(), InvestigationNote.id.asc())).scalars())
    if tag:
        rows = [r for r in rows if tag.strip().lower() in (r.tags or [])]
    return rows


def list_revisions(db: Session, note: InvestigationNote) -> list[InvestigationNoteRevision]:
    return list(db.execute(select(InvestigationNoteRevision).where(InvestigationNoteRevision.note_id == note.id)
                           .order_by(InvestigationNoteRevision.version.asc())).scalars())
