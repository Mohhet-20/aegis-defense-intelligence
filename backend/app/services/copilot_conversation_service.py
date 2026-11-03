"""Phase 12: per-user copilot conversations.

* A conversation belongs to exactly one user; others (including administrators)
  get the same 404 as for a missing one.
* Messages are a history of what was asked and answered. They are NOT evidence:
  they are never indexed and never fed back into retrieval or prompts.
* Opening a conversation re-verifies every citation against live records and the
  user's CURRENT permissions; content that is no longer readable is withheld.
* Deletion is a hard delete (messages cascade). Conversations idle for longer
  than COPILOT_CONVERSATION_RETENTION_DAYS are removed by `purge_expired`."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser
from app.models.retrieval import CopilotConversation, CopilotMessage
from app.services import retrieval_citation_service as cites
from app.services.workspace_errors import not_found

settings = get_settings()
WITHHELD = "[Content withheld: you can no longer access the source record.]"


def create(db: Session, user: AuthenticatedUser, *, title: Optional[str] = None, investigation_id: Optional[str] = None) -> CopilotConversation:
    conv = CopilotConversation(organization_id=user.organization_id, owner_user_id=user.id,
                               investigation_id=investigation_id, title=(title or None) and title[:200])
    db.add(conv)
    db.flush()
    return conv


def get_owned(db: Session, user: AuthenticatedUser, conversation_id: str) -> CopilotConversation:
    conv = db.execute(select(CopilotConversation).where(
        CopilotConversation.id == conversation_id, CopilotConversation.organization_id == user.organization_id,
        CopilotConversation.owner_user_id == user.id)).scalar_one_or_none() if conversation_id and len(conversation_id) <= 36 else None
    if conv is None:
        raise not_found("Conversation")
    return conv


def add_exchange(db: Session, user: AuthenticatedUser, conv: CopilotConversation, *, question: str, task: str, answer: dict) -> tuple[CopilotMessage, CopilotMessage]:
    if not conv.title:
        conv.title = " ".join(question.split())[:80] or None
    um = CopilotMessage(organization_id=user.organization_id, conversation_id=conv.id, role="user", content=question[:4000], task=task)
    am = CopilotMessage(organization_id=user.organization_id, conversation_id=conv.id, role="assistant", task=task, answer=answer,
                        answer_mode=answer.get("mode"))
    db.add_all([um, am])
    conv.updated_at = datetime.now(timezone.utc)
    db.flush()
    return um, am


def list_conversations(db: Session, user: AuthenticatedUser, *, page: int = 1, page_size: int = 20) -> dict:
    base = (CopilotConversation.organization_id == user.organization_id, CopilotConversation.owner_user_id == user.id)
    total = db.execute(select(func.count()).select_from(CopilotConversation).where(*base)).scalar_one()
    rows = db.execute(select(CopilotConversation).where(*base).order_by(CopilotConversation.updated_at.desc(), CopilotConversation.id)
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    counts = dict(db.execute(select(CopilotMessage.conversation_id, func.count()).where(
        CopilotMessage.conversation_id.in_([r.id for r in rows] or [""])).group_by(CopilotMessage.conversation_id)).all())
    return {"items": [{"id": r.id, "title": r.title, "investigation_id": r.investigation_id, "message_count": counts.get(r.id, 0),
                       "created_at": r.created_at, "updated_at": r.updated_at} for r in rows],
            "total": total, "page": page, "page_size": page_size}


def reverify_answer(db: Session, user: AuthenticatedUser, answer: Optional[dict]) -> Optional[dict]:
    """Return a copy of a stored answer with citations re-checked now. Anything
    that depended on a no-longer-readable record is withheld."""
    if not answer:
        return answer
    out = dict(answer)
    cits = [cites.verify_citation(db, user, c) for c in answer.get("citations", [])]
    status = {c["id"]: c["status"] for c in cits if "id" in c}
    for c in cits:
        if c["status"] in ("access_revoked", "unavailable"):
            c.update(title=None, quote=None, link=None, source_time=None)
    out["citations"] = cits
    bad = {i for i, s in status.items() if s in ("access_revoked", "unavailable")}
    claims = []
    for c in answer.get("claims", []):
        c = dict(c)
        ids = c.get("citation_ids", [])
        if any(i in bad for i in ids):
            c["text"], c["withheld"] = WITHHELD, True
        elif any(status.get(i) == "source_changed" for i in ids):
            c["source_changed"] = True
        claims.append(c)
    out["claims"] = claims
    conflicts = []
    for cf in answer.get("conflicts", []):
        cf = dict(cf)
        if any(i in bad for i in cf.get("left_citation_ids", []) + cf.get("right_citation_ids", [])):
            cf["description"], cf["withheld"] = WITHHELD, True
        conflicts.append(cf)
    out["conflicts"] = conflicts
    out["records_used"] = [{"record_type": c["record_type"], "record_id": c["record_id"], "title": c["title"], "link": c["link"]}
                           for c in cits if c["status"] not in ("access_revoked", "unavailable")]
    if bad:
        out.pop("draft_markdown", None)
        out["draft_withheld"] = "draft_markdown" in answer
        out.pop("side_by_side", None)
        out["retrieval"] = {k: v for k, v in (answer.get("retrieval") or {}).items() if k != "weak_matches"}
        out["uncertainty"] = list(answer.get("uncertainty", [])) + ["Some cited records are no longer accessible to you; related content was withheld."]
    elif "side_by_side" in answer:
        out["side_by_side"] = answer["side_by_side"]
    out["reverified_at"] = datetime.now(timezone.utc).isoformat()
    return out


def get_detail(db: Session, user: AuthenticatedUser, conversation_id: str) -> dict:
    conv = get_owned(db, user, conversation_id)
    msgs = db.execute(select(CopilotMessage).where(CopilotMessage.conversation_id == conv.id)
                      .order_by(CopilotMessage.created_at, CopilotMessage.id)).scalars().all()
    return {"id": conv.id, "title": conv.title, "investigation_id": conv.investigation_id, "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "task": m.task, "created_at": m.created_at,
                          "answer_mode": m.answer_mode, "answer": reverify_answer(db, user, m.answer)} for m in msgs],
            "notice": "History is a record of past questions and answers, not evidence. Citations were re-checked against your current access when opened."}


def delete_conversation(db: Session, user: AuthenticatedUser, conversation_id: str) -> int:
    conv = get_owned(db, user, conversation_id)
    n = db.execute(delete(CopilotMessage).where(CopilotMessage.conversation_id == conv.id)).rowcount or 0
    db.delete(conv)
    db.flush()
    return n


def purge_expired(db: Session, organization_id: str, *, retention_days: Optional[int] = None) -> int:
    days = settings.COPILOT_CONVERSATION_RETENTION_DAYS if retention_days is None else retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    ids = [i for (i,) in db.execute(select(CopilotConversation.id).where(
        CopilotConversation.organization_id == organization_id, CopilotConversation.updated_at < cutoff)).all()]
    if ids:
        db.execute(delete(CopilotMessage).where(CopilotMessage.conversation_id.in_(ids)))
        db.execute(delete(CopilotConversation).where(CopilotConversation.id.in_(ids)))
    db.flush()
    return len(ids)
