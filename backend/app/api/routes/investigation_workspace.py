"""Phase 11 investigation workspace routes: members, lifecycle, record
links, evidence registry, integrity, timeline, notes, search, export.

Authorization: route-level permission (RBAC) + service-level access check
(`get_accessible`: org isolation and restricted investigations). Services
flush; each handler commits once so state, history and audit are atomic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, has_permission, require_permission
from app.db.session import get_db
from app.models.investigation import Investigation
from app.models.investigation_workspace import InvestigationNote, NOTE_KINDS
from app.schemas.investigation import InvestigationResponse
from app.schemas.investigation_workspace import (
    EvidenceDetailResponse, IntegrityCheckResponse, LinkRequest, LinkResponse, MemberRequest, MemberResponse,
    NoteCreateRequest, NoteResponse, NoteRevisionResponse, NoteUpdateRequest, ReasonRequest, RegisterEvidenceRequest,
    RegisterEvidenceResponse, ReviewStatusRequest, StatusHistoryResponse, SupersedeRequest, TransitionRequest,
)
from app.services import (
    evidence_registry_service as registry,
    investigation_export_service, investigation_links_service as links, investigation_notes_service as notes_svc,
    investigation_search_service, investigation_service, investigation_timeline_service,
)
from app.services.workspace_errors import forbidden, not_found

router = APIRouter(prefix="/investigations", tags=["investigation-workspace"])
evidence_router = APIRouter(prefix="/evidence", tags=["evidence-registry"])
dashboard_router = APIRouter(prefix="/investigation-dashboard", tags=["investigation-workspace"])

READ = Permission.INVESTIGATION_READ
MANAGE = Permission.INVESTIGATION_MANAGE


def _rid(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _inv(db: Session, user: AuthenticatedUser, investigation_id: str) -> Investigation:
    return investigation_service.get_accessible(db, user, investigation_id)


# ---- lifecycle ------------------------------------------------------------

@router.post("/{investigation_id}/transition", response_model=InvestigationResponse)
def transition(investigation_id: str, payload: TransitionRequest, request: Request,
               user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    investigation_service.transition(db, inv, to_status=payload.to_status, actor_user_id=user.id, reason=payload.reason, request_id=_rid(request))
    db.commit()
    db.refresh(inv)
    return InvestigationResponse.model_validate(inv)


@router.post("/{investigation_id}/close", response_model=InvestigationResponse)
def close(investigation_id: str, payload: ReasonRequest, request: Request,
          user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    investigation_service.transition(db, inv, to_status="closed", actor_user_id=user.id, reason=payload.reason, request_id=_rid(request))
    db.commit()
    db.refresh(inv)
    return InvestigationResponse.model_validate(inv)


@router.post("/{investigation_id}/archive", response_model=InvestigationResponse)
def archive(investigation_id: str, payload: ReasonRequest, request: Request,
            user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    investigation_service.transition(db, inv, to_status="archived", actor_user_id=user.id, reason=payload.reason, request_id=_rid(request))
    db.commit()
    db.refresh(inv)
    return InvestigationResponse.model_validate(inv)


@router.get("/{investigation_id}/status-history", response_model=list[StatusHistoryResponse])
def status_history(investigation_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return investigation_service.list_status_history(db, _inv(db, user, investigation_id))


# ---- members --------------------------------------------------------------

@router.get("/{investigation_id}/members", response_model=list[MemberResponse])
def list_members(investigation_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return investigation_service.list_members(db, _inv(db, user, investigation_id))


@router.post("/{investigation_id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
def add_member(investigation_id: str, payload: MemberRequest, request: Request,
               user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    m = investigation_service.add_member(db, inv, user_id=payload.user_id, role=payload.role, actor_user_id=user.id, request_id=_rid(request))
    db.commit()
    db.refresh(m)
    return m


@router.delete("/{investigation_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(investigation_id: str, member_user_id: str, request: Request,
                  user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    investigation_service.remove_member(db, inv, user_id=member_user_id, actor_user_id=user.id, request_id=_rid(request))
    db.commit()
    return Response(status_code=204)


# ---- links ----------------------------------------------------------------

@router.get("/{investigation_id}/links", response_model=list[LinkResponse])
def list_links(investigation_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    out = []
    for l in links.list_links(db, inv):
        row = links.resolve_record(db, inv.organization_id, l.record_type, l.record_id)
        summary = None
        if row is not None and not (l.record_type == "evidence" and not registry.evidence_visible(user, row)):
            summary = links.describe(l.record_type, row)
        out.append(LinkResponse(id=l.id, record_type=l.record_type, record_id=l.record_id, note=l.note, created_at=l.created_at,
                                linked_by_user_id=l.linked_by_user_id, summary=summary, resolvable=row is not None))
    return out


@router.post("/{investigation_id}/links", response_model=LinkResponse, status_code=status.HTTP_201_CREATED)
def add_link(investigation_id: str, payload: LinkRequest, request: Request,
             user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    row = links.resolve_record(db, inv.organization_id, payload.record_type, payload.record_id)
    if row is not None and payload.record_type == "evidence" and not registry.evidence_visible(user, row):
        raise not_found(payload.record_type)
    l = links.link_record(db, inv, record_type=payload.record_type, record_id=payload.record_id, note=payload.note,
                          actor_user_id=user.id, request_id=_rid(request))
    db.commit()
    return LinkResponse(id=l.id, record_type=l.record_type, record_id=l.record_id, note=l.note, created_at=l.created_at,
                        linked_by_user_id=l.linked_by_user_id, summary=links.describe(l.record_type, row), resolvable=True)


@router.delete("/{investigation_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_link(investigation_id: str, link_id: str, request: Request,
                user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    links.unlink_record(db, inv, link_id=link_id, actor_user_id=user.id, request_id=_rid(request))
    db.commit()
    return Response(status_code=204)


# ---- evidence in an investigation -----------------------------------------

@router.get("/{investigation_id}/evidence", response_model=list[EvidenceDetailResponse])
def list_investigation_evidence(investigation_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    return [r["row"] for r in links.effective_records(db, inv)
            if r["record_type"] == "evidence" and r["row"] is not None and registry.evidence_visible(user, r["row"])]


@router.post("/{investigation_id}/evidence", response_model=RegisterEvidenceResponse, status_code=status.HTTP_201_CREATED)
def register_evidence(investigation_id: str, payload: RegisterEvidenceRequest, request: Request,
                      user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    if not has_permission(user.role, Permission.EVIDENCE_MANAGE):
        raise forbidden(f"Missing permission: {Permission.EVIDENCE_MANAGE.value}")
    inv = _inv(db, user, investigation_id)
    evidence, reused, link = registry.register_evidence(
        db, inv, actor_user_id=user.id, request_id=_rid(request), **payload.model_dump())
    db.commit()
    db.refresh(evidence)
    return RegisterEvidenceResponse(evidence=EvidenceDetailResponse.model_validate(evidence), reused_existing=reused, link_id=link.id)


# ---- timeline / search / relationships ------------------------------------

@router.get("/{investigation_id}/timeline")
def timeline(
    investigation_id: str,
    start: Optional[datetime] = None, end: Optional[datetime] = None,
    record_type: Optional[list[str]] = Query(default=None), time_kind: Optional[list[str]] = Query(default=None),
    source_id: Optional[str] = Query(default=None, max_length=36), include_unknown_times: bool = True,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
    user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db),
):
    inv = _inv(db, user, investigation_id)
    return investigation_timeline_service.get_timeline(
        db, inv, start=start, end=end, record_types=record_type, time_kinds=time_kind, source_id=source_id,
        include_unknown_times=include_unknown_times, page=page, page_size=page_size)


@router.get("/{investigation_id}/search")
def search(
    investigation_id: str, q: Optional[str] = Query(default=None, max_length=200),
    record_type: Optional[list[str]] = Query(default=None), source_id: Optional[str] = Query(default=None, max_length=36),
    start: Optional[datetime] = None, end: Optional[datetime] = None,
    evidence_status: Optional[str] = Query(default=None, max_length=20), review_status: Optional[str] = Query(default=None, max_length=30),
    data_quality: Optional[str] = Query(default=None, pattern="^(clean|flagged|unknown)$"), tag: Optional[str] = Query(default=None, max_length=50),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db),
):
    inv = _inv(db, user, investigation_id)
    return investigation_search_service.search(
        db, inv, q=q, record_types=record_type, source_id=source_id, start=start, end=end, evidence_status=evidence_status,
        review_status=review_status, data_quality=data_quality, tag=tag, page=page, page_size=page_size,
        evidence_filter=lambda ev: registry.evidence_visible(user, ev))


@router.get("/{investigation_id}/relationships")
def relationships(investigation_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return investigation_search_service.relationships(db, _inv(db, user, investigation_id))


# ---- notes ----------------------------------------------------------------

@router.get("/{investigation_id}/notes", response_model=list[NoteResponse])
def list_notes(investigation_id: str, evidence_id: Optional[str] = Query(default=None, max_length=36),
               note_kind: Optional[str] = Query(default=None, max_length=30), unresolved_only: bool = False,
               tag: Optional[str] = Query(default=None, max_length=50),
               user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    return notes_svc.list_notes(db, inv, evidence_id=evidence_id, note_kind=note_kind, unresolved_only=unresolved_only, tag=tag)


@router.get("/{investigation_id}/note-kinds")
def note_kinds(investigation_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    _inv(db, user, investigation_id)
    return [{"kind": k, "description": notes_svc.KIND_DESCRIPTIONS[k]} for k in NOTE_KINDS]


@router.post("/{investigation_id}/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(investigation_id: str, payload: NoteCreateRequest, request: Request,
                user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    n = notes_svc.create_note(db, inv, actor_user_id=user.id, request_id=_rid(request), **payload.model_dump())
    db.commit()
    db.refresh(n)
    return n


@router.patch("/{investigation_id}/notes/{note_id}", response_model=NoteResponse)
def update_note(investigation_id: str, note_id: str, payload: NoteUpdateRequest, request: Request,
                user: AuthenticatedUser = Depends(require_permission(MANAGE)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    note = notes_svc.get_note(db, inv, note_id)
    notes_svc.update_note(db, inv, note, user=user, request_id=_rid(request), **payload.model_dump())
    db.commit()
    db.refresh(note)
    return note


@router.get("/{investigation_id}/notes/{note_id}/revisions", response_model=list[NoteRevisionResponse])
def note_revisions(investigation_id: str, note_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    return notes_svc.list_revisions(db, notes_svc.get_note(db, inv, note_id))


# ---- export ---------------------------------------------------------------

@router.post("/{investigation_id}/export")
def export(investigation_id: str, request: Request, format: str = Query(default="json"), include_media: bool = False,
           user: AuthenticatedUser = Depends(require_permission(Permission.INVESTIGATION_EXPORT)), db: Session = Depends(get_db)):
    inv = _inv(db, user, investigation_id)
    as_json, as_zip = investigation_export_service.export_investigation(
        db, inv, user, fmt=format, include_media=include_media, request_id=_rid(request))
    db.commit()
    if as_zip is not None:
        return Response(content=as_zip, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="investigation-{inv.id}.zip"'})
    return as_json


@router.get("/{investigation_id}/audit")
def audit_history(investigation_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    from app.services import audit_service
    inv = _inv(db, user, investigation_id)
    rows = audit_service.list_for_target(db, inv.organization_id, target_type="investigation", target_id=inv.id)
    return [{"id": r.id, "action": r.action, "actor_user_id": r.actor_user_id, "outcome": r.outcome,
             "created_at": r.created_at, "details": r.context_metadata} for r in rows]


# ---- evidence registry detail ---------------------------------------------

@evidence_router.get("/{evidence_id}/provenance")
def evidence_provenance(evidence_id: str, user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_READ)), db: Session = Depends(get_db)):
    return registry.build_provenance(db, registry.get_evidence_for_user(db, user, evidence_id))


@evidence_router.get("/{evidence_id}/integrity-checks", response_model=list[IntegrityCheckResponse])
def integrity_checks(evidence_id: str, user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_READ)), db: Session = Depends(get_db)):
    ev = registry.get_evidence_for_user(db, user, evidence_id)
    return [IntegrityCheckResponse.model_validate(c) for c in registry.list_integrity_checks(db, ev)]


@evidence_router.post("/{evidence_id}/verify-integrity", response_model=IntegrityCheckResponse)
def verify_integrity(evidence_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_MANAGE)), db: Session = Depends(get_db)):
    ev = registry.get_evidence_for_user(db, user, evidence_id)
    check = registry.verify_integrity(db, ev, actor_user_id=user.id, request_id=_rid(request))
    db.commit()
    db.refresh(check)
    out = IntegrityCheckResponse.model_validate(check)
    out.disclaimer = registry.INTEGRITY_DISCLAIMER
    return out


@evidence_router.post("/{evidence_id}/review-status", response_model=EvidenceDetailResponse)
def evidence_review_status(evidence_id: str, payload: ReviewStatusRequest, request: Request,
                           user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_MANAGE)), db: Session = Depends(get_db)):
    ev = registry.get_evidence_for_user(db, user, evidence_id)
    registry.set_review_status(db, ev, review_status=payload.review_status, note=payload.note, actor_user_id=user.id, request_id=_rid(request))
    db.commit()
    db.refresh(ev)
    return ev


@evidence_router.post("/{evidence_id}/supersede", response_model=EvidenceDetailResponse, status_code=status.HTTP_201_CREATED)
def evidence_supersede(evidence_id: str, payload: SupersedeRequest, request: Request,
                       user: AuthenticatedUser = Depends(require_permission(Permission.EVIDENCE_MANAGE)), db: Session = Depends(get_db)):
    ev = registry.get_evidence_for_user(db, user, evidence_id)
    new = registry.supersede(db, ev, actor_user_id=user.id, reason=payload.reason, title=payload.title,
                             summary=payload.summary, content=payload.content, request_id=_rid(request))
    db.commit()
    db.refresh(new)
    return new


# ---- dashboard --------------------------------------------------------------

@dashboard_router.get("/summary")
def dashboard_summary(user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    base = investigation_service.list_investigations_query(user.organization_id, user=user, include_archived=True).subquery()
    by_status = dict(db.execute(select(base.c.status, func.count()).group_by(base.c.status)).all())
    by_priority = dict(db.execute(select(base.c.priority, func.count()).where(base.c.status.notin_(("closed", "archived"))).group_by(base.c.priority)).all())
    accessible_ids = select(base.c.id)
    my_questions = db.scalar(select(func.count()).select_from(InvestigationNote).where(
        InvestigationNote.organization_id == user.organization_id, InvestigationNote.investigation_id.in_(accessible_ids),
        InvestigationNote.note_kind == "review_question", InvestigationNote.resolution_status == "open",
        InvestigationNote.assignee_user_id == user.id)) or 0
    open_questions = db.scalar(select(func.count()).select_from(InvestigationNote).where(
        InvestigationNote.organization_id == user.organization_id, InvestigationNote.investigation_id.in_(accessible_ids),
        InvestigationNote.note_kind == "review_question", InvestigationNote.resolution_status == "open")) or 0
    recent = db.execute(investigation_service.list_investigations_query(
        user.organization_id, user=user, sort_by="updated_at", sort_dir="desc").limit(8)).scalars().all()
    return {
        "by_status": by_status, "open_by_priority": by_priority, "total": sum(by_status.values()),
        "open_review_questions": open_questions, "review_questions_assigned_to_me": my_questions,
        "recent_activity": [{"id": i.id, "title": i.title, "status": i.status, "priority": i.priority, "updated_at": i.updated_at} for i in recent],
    }
