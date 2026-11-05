"""Investigation-scoped search and relationship view.

Only records tied to the investigation are searched, and each is resolved
with an organization filter. Relationships reuse EvidenceRelationship; the
response states whether a relationship came from a rule, a model or an
analyst and its review status. Nothing here promotes a candidate or
uncertain relationship to confirmed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.evidence_relationship import EvidenceRelationship
from app.models.investigation import Investigation
from app.models.investigation_workspace import InvestigationNote
from app.services import investigation_links_service as links
from app.services.timeutil import to_utc

DATA_QUALITY_STATES = ("clean", "flagged", "unknown")


def search(
    db: Session, investigation: Investigation, *, q: Optional[str] = None, record_types: Optional[list[str]] = None,
    source_id: Optional[str] = None, start: Optional[datetime] = None, end: Optional[datetime] = None,
    evidence_status: Optional[str] = None, review_status: Optional[str] = None, data_quality: Optional[str] = None,
    tag: Optional[str] = None, page: int = 1, page_size: int = 25, evidence_filter=None,
) -> dict:
    items: list[dict] = []
    for rec in links.effective_records(db, investigation):
        row = rec["row"]
        if row is None:
            continue
        if rec["record_type"] == "evidence" and evidence_filter is not None and not evidence_filter(row):
            continue
        d = links.describe(rec["record_type"], row)
        d["origin"] = rec["origin"]
        d["tags"] = []
        if rec["record_type"] == "evidence":
            d["evidence_status"] = row.review_status
            d["superseded"] = row.superseded_by_evidence_id is not None
        items.append(d)
    for n in db.execute(select(InvestigationNote).where(InvestigationNote.investigation_id == investigation.id)).scalars():
        items.append({
            "record_type": "note", "record_id": n.id, "title": f"{n.note_kind.replace('_', ' ')} note", "summary": n.body[:300],
            "source_id": None, "review_status": n.resolution_status, "data_quality": "unknown",
            "primary_time": to_utc(n.created_at)[0].isoformat().replace("+00:00", "Z"), "primary_time_kind": "note_time",
            "tags": list(n.tags or []), "origin": "note",
        })

    s, e = to_utc(start)[0], to_utc(end)[0]
    ql = q.strip().lower() if q else None

    def keep(x: dict) -> bool:
        if record_types and x["record_type"] not in record_types:
            return False
        if source_id and x["source_id"] != source_id:
            return False
        if evidence_status and x.get("evidence_status") != evidence_status:
            return False
        if review_status and x["review_status"] != review_status:
            return False
        if data_quality and x["data_quality"] != data_quality:
            return False
        if tag and tag.strip().lower() not in x["tags"]:
            return False
        if ql and ql not in f"{x['title'] or ''} {x['summary'] or ''}".lower():
            return False
        if s or e:
            if not x["primary_time"]:
                return False  # unknown time cannot satisfy a date range
            t = to_utc(datetime.fromisoformat(x["primary_time"].replace("Z", "+00:00")))[0]
            if (s and t < s) or (e and t > e):
                return False
        return True

    kept = [x for x in items if keep(x)]
    kept.sort(key=lambda x: (x["primary_time"] is None, x["primary_time"] or "", x["record_type"], x["record_id"]))
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    return {
        "items": kept[(page - 1) * page_size: page * page_size], "total": len(kept), "page": page, "page_size": page_size,
        "note": "Only records linked to this investigation are searched. 'data_quality' is 'unknown' when a record type carries no quality indicator.",
    }


def relationships(db: Session, investigation: Investigation) -> dict:
    recs = links.effective_records(db, investigation)
    event_ids = {r["record_id"] for r in recs if r["record_type"] == "event"}
    evidence_ids = {r["record_id"] for r in recs if r["record_type"] == "evidence"}
    if not event_ids and not evidence_ids:
        return {"items": [], "total": 0, "notice": _NOTICE}
    cond = or_(
        EvidenceRelationship.source_event_id.in_(event_ids), EvidenceRelationship.target_event_id.in_(event_ids),
        EvidenceRelationship.source_evidence_id.in_(evidence_ids), EvidenceRelationship.target_evidence_id.in_(evidence_ids),
    )
    rows = db.execute(select(EvidenceRelationship).where(
        EvidenceRelationship.organization_id == investigation.organization_id, EvidenceRelationship.is_reversed.is_(False), cond,
    ).order_by(EvidenceRelationship.created_at.asc(), EvidenceRelationship.id.asc()).limit(500)).scalars().all()
    items = []
    for r in rows:
        items.append({
            "relationship_id": r.id, "relationship_type": r.relationship_type,
            "source": {"record_type": "event" if r.source_event_id else "evidence", "record_id": r.source_event_id or r.source_evidence_id},
            "target": {"record_type": "event" if r.target_event_id else "evidence", "record_id": r.target_event_id or r.target_evidence_id},
            "origin": r.origin,
            "origin_label": {"rule_based": "Proposed by a rule", "model_assisted": "Proposed by a model", "analyst_created": "Recorded by an analyst"}.get(r.origin, r.origin),
            "review_status": r.review_status, "is_confirmed": r.review_status == "confirmed",
            "explanation": r.explanation,
        })
    return {"items": items, "total": len(items), "notice": _NOTICE}


_NOTICE = ("Relationships are shown as recorded. Only those with review_status 'confirmed' have been confirmed by a reviewer; "
           "candidate and uncertain relationships are not facts.")
