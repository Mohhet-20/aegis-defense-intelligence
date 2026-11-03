"""Phase 12 routes: authorized retrieval search, indexing, the evidence-grounded
copilot, citation verification, conversations and the synthetic evaluation.

Every handler applies RBAC at the route, and per-record authorization in the
services (investigation membership, restricted evidence, per-type read
permission, organization isolation). Missing, other-organization and
unauthorized references all yield the same 404."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, has_permission, require_permission
from app.db.session import get_db
from app.retrieval import providers
from app.schemas.copilot import (
    AskRequest, AskResponse, ConversationCreate, ConversationDetail, ConversationList, ConversationSummary,
    IndexRequest, SearchResponse, VerifyCitationsRequest, VerifyCitationsResponse,
)
from app.services import (
    audit_service, copilot_conversation_service as convs, copilot_service as copilot, investigation_service,
    retrieval_citation_service as cites, retrieval_eval_service, retrieval_index_service as indexer,
    retrieval_search_service as search_svc, retrieval_sources as src,
)
from app.services.workspace_errors import invalid

settings = get_settings()
router = APIRouter(prefix="/retrieval", tags=["retrieval"])
copilot_router = APIRouter(prefix="/copilot", tags=["copilot"])

READ = Permission.RETRIEVAL_READ
INDEX = Permission.RETRIEVAL_INDEX
EVALUATE = Permission.RETRIEVAL_EVALUATE

# ---- small in-process per-user sliding-window limiter (single-process; see docs) ----
_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = threading.Lock()


def _limit(user: AuthenticatedUser, bucket: str) -> None:
    limit = settings.COPILOT_RATE_LIMIT_PER_MINUTE
    if limit <= 0:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[(user.id, bucket)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(60 - (now - q[0])))
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests; please slow down.",
                                headers={"Retry-After": str(retry)})
        q.append(now)


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()


def _rid(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _audit(db: Session, request: Request, user: AuthenticatedUser, action: str, target_type: Optional[str] = None,
           target_id: Optional[str] = None, outcome: str = "success", **meta) -> None:
    audit_service.record(db, action=action, actor_user_id=user.id, organization_id=user.organization_id, target_type=target_type,
                         target_id=target_id, outcome=outcome, request_id=_rid(request), context_metadata=meta)


# ---------------------------------------------------------------- capabilities

@router.get("/capabilities")
def capabilities(user: AuthenticatedUser = Depends(require_permission(READ))):
    gen = providers.generation_status()
    avail, pname, reason = providers.provider_available()
    return {
        "keyword_search": {"available": True, "method": "bm25"},
        "semantic_search": providers.embedding_status(),
        "generation": {"available": avail, "provider": pname, "reason": reason, "external": gen["external"]},
        "record_types": src.allowed_record_types(user),
        "limits": {"max_query_chars": settings.RETRIEVAL_MAX_QUERY_CHARS, "max_results": settings.RETRIEVAL_MAX_RESULTS,
                   "max_question_chars": settings.COPILOT_MAX_QUESTION_CHARS, "rate_limit_per_minute": settings.COPILOT_RATE_LIMIT_PER_MINUTE},
        "can_index": has_permission(user.role, INDEX), "can_evaluate": has_permission(user.role, EVALUATE),
    }


# --------------------------------------------------------------------- search

@router.get("/search", response_model=SearchResponse)
def search(request: Request, q: str = Query(..., max_length=2000), record_type: Optional[list[str]] = Query(default=None, max_length=10),
           investigation_id: Optional[str] = Query(default=None, max_length=36), source_id: Optional[str] = Query(default=None, max_length=36),
           review_status: Optional[str] = Query(default=None, max_length=30), time_from: Optional[datetime] = None,
           time_to: Optional[datetime] = None, document_version: Optional[int] = Query(default=None, ge=1),
           page: int = Query(1, ge=1, le=1000), page_size: int = Query(10, ge=1, le=50),
           user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    _limit(user, "search")
    res = search_svc.search(db, user, q, filters=search_svc.SearchFilters(
        record_types=record_type, investigation_id=investigation_id, source_id=source_id, review_status=review_status,
        time_from=time_from, time_to=time_to, document_version=document_version), page=page, page_size=page_size)
    _audit(db, request, user, "retrieval.search", "retrieval", None, query_chars=len(q), results=res.total,
           investigation_id=investigation_id, record_types=res.filters_applied["record_types"])
    db.commit()
    return res.as_dict()


@router.get("/documents/{record_type}/{record_id}")
def document(record_type: str, record_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(READ)),
             db: Session = Depends(get_db)):
    try:
        out = search_svc.document_detail(db, user, record_type, record_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            _audit(db, request, user, "retrieval.document_read", record_type, record_id, outcome="denied")
            db.commit()
        raise
    _audit(db, request, user, "retrieval.document_read", record_type, record_id)
    db.commit()
    return out


# ------------------------------------------------------------------- indexing

@router.post("/index")
def trigger_index(payload: IndexRequest, request: Request, user: AuthenticatedUser = Depends(require_permission(INDEX)),
                  db: Session = Depends(get_db)):
    _limit(user, "index")
    run = indexer.run_index(db, organization_id=user.organization_id, user_id=user.id, record_types=payload.record_types,
                            investigation_id=payload.investigation_id)
    _audit(db, request, user, "retrieval.index_run", "retrieval_index_run", run.id, scope=run.scope, status=run.status, counts=run.counts)
    db.commit()
    return {"run_id": run.id, "scope": run.scope, "status": run.status, "counts": run.counts, "errors": run.errors,
            "started_at": run.started_at, "finished_at": run.finished_at}


@router.get("/index/status")
def index_status(user: AuthenticatedUser = Depends(require_permission(INDEX)), db: Session = Depends(get_db)):
    return indexer.index_status(db, user.organization_id)


@router.post("/index/purge")
def purge(request: Request, user: AuthenticatedUser = Depends(require_permission(INDEX)), db: Session = Depends(get_db)):
    tomb = indexer.purge_tombstones(db, user.organization_id)
    convo = convs.purge_expired(db, user.organization_id)
    _audit(db, request, user, "retrieval.purge", "retrieval", None, tombstones_removed=tomb, conversations_removed=convo)
    db.commit()
    return {"tombstones_removed": tomb, "conversations_removed": convo,
            "policy": {"tombstone_days": settings.RETRIEVAL_TOMBSTONE_DAYS, "conversation_retention_days": settings.COPILOT_CONVERSATION_RETENTION_DAYS}}


@router.post("/evaluate")
def evaluate(request: Request, user: AuthenticatedUser = Depends(require_permission(EVALUATE)), db: Session = Depends(get_db)):
    out = retrieval_eval_service.run()
    _audit(db, request, user, "retrieval.evaluate", "retrieval", None, dataset=out["dataset"])
    db.commit()
    return out


# -------------------------------------------------------------------- copilot

def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise invalid(msg)


@copilot_router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, request: Request, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    _limit(user, "ask")
    t = payload.task
    refs = [(r.record_type, r.record_id) for r in (payload.record_refs or [])]
    if t == "question":
        _require(bool((payload.question or "").strip()), "question is required")
        answer = copilot.answer_question(db, user, payload.question, investigation_id=payload.investigation_id,
                                         record_types=payload.record_types)
    elif t in ("summarize_investigation", "chronology", "report_draft"):
        _require(bool(payload.investigation_id), "investigation_id is required for this task")
        if t == "summarize_investigation":
            answer = copilot.summarize_investigation(db, user, payload.investigation_id)
        elif t == "chronology":
            answer = copilot.chronology(db, user, payload.investigation_id)
        else:
            answer = copilot.report_draft(db, user, payload.investigation_id, title=payload.report_title)
    elif t == "compare":
        _require(2 <= len(refs) <= 6, "compare requires 2 to 6 record_refs")
        answer = copilot.compare_records(db, user, refs)
    else:  # related
        _require(len(refs) == 1, "related requires exactly one record_ref")
        answer = copilot.find_related(db, user, *refs[0])
    conv_id = msg_id = None
    if payload.save:
        conv = convs.get_owned(db, user, payload.conversation_id) if payload.conversation_id else convs.create(
            db, user, title=payload.title, investigation_id=payload.investigation_id)
        label = (payload.question or "").strip() or f"[{t}]"
        _, am = convs.add_exchange(db, user, conv, question=label, task=t, answer=answer)
        conv_id, msg_id = conv.id, am.id
    _audit(db, request, user, "copilot.ask", "copilot_conversation" if conv_id else None, conv_id, task=t, mode=answer["mode"],
           status=answer["status"], citations=len(answer["citations"]), question_chars=len(payload.question or ""),
           investigation_id=payload.investigation_id, generation_note=bool(answer["generation"].get("notice")))
    db.commit()
    return {"answer": answer, "conversation_id": conv_id, "message_id": msg_id}


@copilot_router.post("/citations/verify", response_model=VerifyCitationsResponse)
def verify(payload: VerifyCitationsRequest, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    _limit(user, "verify")
    out = []
    for c in payload.citations:
        v = cites.verify_citation(db, user, c.model_dump())
        if v["status"] in ("access_revoked", "unavailable"):
            v.update(title=None, quote=None, link=None, source_time=None)
        out.append(v)
    return {"citations": out}


@copilot_router.post("/conversations", response_model=ConversationSummary, status_code=201)
def create_conversation(payload: ConversationCreate, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    if payload.investigation_id:
        investigation_service.get_accessible(db, user, payload.investigation_id)
    conv = convs.create(db, user, title=payload.title, investigation_id=payload.investigation_id)
    db.commit()
    return {"id": conv.id, "title": conv.title, "investigation_id": conv.investigation_id, "message_count": 0,
            "created_at": conv.created_at, "updated_at": conv.updated_at}


@copilot_router.get("/conversations", response_model=ConversationList)
def list_conversations(page: int = Query(1, ge=1, le=1000), page_size: int = Query(20, ge=1, le=100),
                       user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return convs.list_conversations(db, user, page=page, page_size=page_size)


@copilot_router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(READ)),
                     db: Session = Depends(get_db)):
    out = convs.get_detail(db, user, conversation_id)
    _audit(db, request, user, "copilot.conversation_open", "copilot_conversation", conversation_id)
    db.commit()
    return out


@copilot_router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(READ)),
                        db: Session = Depends(get_db)):
    n = convs.delete_conversation(db, user, conversation_id)
    _audit(db, request, user, "copilot.conversation_delete", "copilot_conversation", conversation_id, messages_deleted=n)
    db.commit()
    return Response(status_code=204)
