"""Authorized keyword (BM25) retrieval over the derived index.

Pipeline: validate -> SQL prefilter (org, active docs, record types the role
may read, filters, term LIKE) -> BM25 in Python -> LIVE per-record
authorization -> collapse to best chunk per record -> paginate.

Scores are BM25 relevance values for ordering only. They are not probabilities
and say nothing about whether a record is true or reliable."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser
from app.models.retrieval import INDEXABLE_RECORD_TYPES, SIMULATED_RECORD_TYPES, RetrievalChunk, RetrievalDocument
from app.retrieval.lexical import bm25_scores, excerpt, query_terms
from app.retrieval.text import body_text
from app.services import investigation_links_service, investigation_service, retrieval_sources as src
from app.services.timeutil import iso, to_utc
from app.services.workspace_errors import invalid, not_found

settings = get_settings()

SEARCHABLE_STATUSES = ("indexed", "unsupported")
RANKING_NOTE = ("Ranked by BM25 keyword relevance. Scores order results only; they are not probabilities and do not "
                "indicate that a record is accurate or reliable.")


@dataclass
class SearchFilters:
    record_types: Optional[list[str]] = None
    investigation_id: Optional[str] = None
    source_id: Optional[str] = None
    review_status: Optional[str] = None
    time_from: Optional[datetime] = None
    time_to: Optional[datetime] = None
    document_version: Optional[int] = None


@dataclass
class SearchResult:
    items: list[dict] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 10
    terms: list[str] = field(default_factory=list)
    truncated: bool = False
    notice: Optional[str] = None
    filters_applied: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "items": self.items, "total": self.total, "page": self.page, "page_size": self.page_size,
            "query_terms": self.terms, "candidates_truncated": self.truncated, "notice": self.notice,
            "filters_applied": self.filters_applied,
            "method": {"lexical": "bm25", "semantic": False,
                       "semantic_note": "No embedding provider is configured; results are keyword matches only.",
                       "ranking_note": RANKING_NOTE},
        }


def _like(col, term: str):
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return col.like(f"%{esc}%", escape="\\")


def validate_query(query: Optional[str]) -> str:
    q = (query or "").strip()
    if not q:
        raise invalid("query must not be empty")
    if len(q) > settings.RETRIEVAL_MAX_QUERY_CHARS:
        raise invalid(f"query must be at most {settings.RETRIEVAL_MAX_QUERY_CHARS} characters")
    return q


def _scope_ids(db: Session, user: AuthenticatedUser, investigation_id: str) -> set[str]:
    inv = investigation_service.get_accessible(db, user, investigation_id)  # 404 if no access
    ids = {inv.id}
    from app.models.investigation_workspace import InvestigationNote
    ids.update(r for (r,) in db.execute(select(InvestigationNote.id).where(InvestigationNote.investigation_id == inv.id)).all())
    for item in investigation_links_service.effective_records(db, inv):
        if item["row"] is not None:
            ids.add(item["record_id"])
            if item["record_type"] == "assessment":
                from app.models.assessment_review import AssessmentReview
                ids.update(r for (r,) in db.execute(select(AssessmentReview.id).where(AssessmentReview.assessment_id == item["record_id"])).all())
    from app.models.scenario import Scenario
    ids.update(r for (r,) in db.execute(select(Scenario.id).where(Scenario.investigation_id == inv.id,
                                                                    Scenario.organization_id == user.organization_id)).all())
    return ids


def _live_info(db: Session, user: AuthenticatedUser, cache: dict, rtype: str, rid: str):
    key = (rtype, rid)
    if key not in cache:
        row = src.load_live(db, user.organization_id, rtype, rid)
        ok = row is not None and src.can_view(db, user, rtype, row)
        cache[key] = (row if ok else None)
    return cache[key]


def search(db: Session, user: AuthenticatedUser, query: Optional[str], *, filters: Optional[SearchFilters] = None,
           page: int = 1, page_size: int = 10, include_text: bool = False) -> SearchResult:
    q = validate_query(query)
    f = filters or SearchFilters()
    if page < 1 or page_size < 1 or page_size > settings.RETRIEVAL_MAX_RESULTS:
        raise invalid(f"page must be >= 1 and page_size between 1 and {settings.RETRIEVAL_MAX_RESULTS}")
    if f.time_from and f.time_to and to_utc(f.time_from)[0] > to_utc(f.time_to)[0]:
        raise invalid("time_from must not be after time_to")
    if f.document_version is not None and f.document_version < 1:
        raise invalid("document_version must be >= 1")
    allowed = src.allowed_record_types(user)
    if f.record_types:
        unknown = [t for t in f.record_types if t not in INDEXABLE_RECORD_TYPES]
        if unknown:
            raise invalid(f"unknown record types: {unknown}")
        types = [t for t in f.record_types if t in allowed]
    else:
        # Hypothetical (simulated) record types never appear in default
        # searches; the caller must ask for them by type.
        types = [t for t in allowed if t not in SIMULATED_RECORD_TYPES]
    res = SearchResult(page=page, page_size=page_size)
    res.filters_applied = {
        "record_types": types, "investigation_id": f.investigation_id, "source_id": f.source_id,
        "review_status": f.review_status, "time_from": iso(f.time_from) if f.time_from else None,
        "time_to": iso(f.time_to) if f.time_to else None, "document_version": f.document_version}
    terms = query_terms(q)
    res.terms = terms
    if not terms:
        res.notice = "The query contains no searchable terms (only common words or symbols)."
        return res
    if not types:
        res.notice = "Your role cannot read any indexed record type."
        return res
    scope: Optional[set[str]] = _scope_ids(db, user, f.investigation_id) if f.investigation_id else None

    org = user.organization_id
    base = [RetrievalChunk.organization_id == org, RetrievalDocument.status.in_(SEARCHABLE_STATUSES),
            RetrievalDocument.retention_state == "active", RetrievalChunk.record_type.in_(types)]
    if scope is not None:
        base.append(RetrievalChunk.record_id.in_(list(scope)[:5000]))
    if f.source_id:
        base.append(RetrievalDocument.source_id == f.source_id)
    if f.review_status:
        base.append(RetrievalDocument.review_status == f.review_status)
    if f.time_from:
        base.append(RetrievalDocument.source_time >= f.time_from)
    if f.time_to:
        base.append(RetrievalDocument.source_time <= f.time_to)
    if f.document_version is not None:
        base.append(RetrievalChunk.document_version == f.document_version)
    stmt = (select(RetrievalChunk, RetrievalDocument).join(RetrievalDocument, RetrievalDocument.id == RetrievalChunk.document_id)
            .where(*base, or_(*[_like(RetrievalChunk.text_lower, t) for t in terms]))
            .order_by(RetrievalChunk.indexed_at.desc(), RetrievalChunk.id).limit(settings.RETRIEVAL_MAX_CANDIDATES + 1))
    rows = db.execute(stmt).all()
    if len(rows) > settings.RETRIEVAL_MAX_CANDIDATES:
        rows = rows[: settings.RETRIEVAL_MAX_CANDIDATES]
        res.truncated = True

    stats = db.execute(select(func.count(), func.avg(RetrievalChunk.token_count)).select_from(RetrievalChunk).join(
        RetrievalDocument, RetrievalDocument.id == RetrievalChunk.document_id).where(
        RetrievalChunk.organization_id == org, RetrievalDocument.status.in_(SEARCHABLE_STATUSES))).one()
    n_docs, avg_len = int(stats[0] or 0), float(stats[1] or 1.0)
    df = {t: db.execute(select(func.count()).select_from(RetrievalChunk).where(
        RetrievalChunk.organization_id == org, _like(RetrievalChunk.text_lower, t))).scalar_one() for t in terms}
    scored = bm25_scores(terms, [c.text for c, _ in rows], n_docs=n_docs, avg_len=avg_len, df=df)

    cache: dict = {}
    best: dict[tuple[str, str], dict] = {}
    for (chunk, doc), (score, matched) in zip(rows, scored):
        if score <= 0:
            continue
        key = (chunk.record_type, chunk.record_id)
        live = _live_info(db, user, cache, *key)
        if live is None:
            continue  # deleted, other org, or access revoked: dropped, never revealed
        cur = best.get(key)
        if cur is not None:
            cur["matching_chunks"] += 1
            if score <= cur["score"]:
                continue
            count = cur["matching_chunks"]
        else:
            count = 1
        live_upd = getattr(live, "updated_at", None)
        stale = bool(live_upd is not None and doc.source_updated_at is not None
                     and to_utc(live_upd)[0] > to_utc(doc.source_updated_at)[0])
        best[key] = {
            "record_type": chunk.record_type, "record_id": chunk.record_id, "document_id": doc.id, "chunk_id": chunk.id,
            "chunk_position": chunk.position, "document_version": chunk.document_version, "title": doc.title,
            "section": chunk.section, "excerpt": excerpt(body_text(chunk.text) or chunk.text, matched or terms), "text": chunk.text if include_text else None, "score": round(score, 4),
            "matched_terms": matched, "matching_chunks": count, "source_time": iso(doc.source_time) if doc.source_time else None,
            "source_id": doc.source_id, "review_status": doc.review_status, "investigation_id": doc.investigation_id,
            "source_ref": doc.source_ref, "extraction_method": doc.extraction_method,
            "content_available": doc.status == "indexed", "stale": stale,
            "link": src.detail_link(chunk.record_type, chunk.record_id, src.parent_id(chunk.record_type, live)),
        }
    ordered = sorted(best.values(), key=lambda h: (-h["score"], h["source_time"] or "", h["record_id"]))
    res.total = len(ordered)
    start = (page - 1) * page_size
    res.items = ordered[start: start + page_size]
    if res.total == 0:
        res.notice = "No authorized records matched the query terms."
    return res


def document_detail(db: Session, user: AuthenticatedUser, record_type: str, record_id: str) -> dict:
    """Authorized detail of an indexed document with its chunks. Unauthorized,
    deleted and cross-org references all return the same 404."""
    if record_type not in INDEXABLE_RECORD_TYPES:
        raise invalid(f"record_type must be one of {INDEXABLE_RECORD_TYPES}")
    live = src.load_live(db, user.organization_id, record_type, record_id)
    doc = db.execute(select(RetrievalDocument).where(
        RetrievalDocument.organization_id == user.organization_id, RetrievalDocument.record_type == record_type,
        RetrievalDocument.record_id == record_id)).scalar_one_or_none()
    if live is None or doc is None or doc.status == "invalidated" or not src.can_view(db, user, record_type, live):
        raise not_found("Document")
    chunks = db.execute(select(RetrievalChunk).where(RetrievalChunk.document_id == doc.id).order_by(RetrievalChunk.position)).scalars().all()
    live_upd = getattr(live, "updated_at", None)
    stale = bool(live_upd is not None and doc.source_updated_at is not None and to_utc(live_upd)[0] > to_utc(doc.source_updated_at)[0])
    return {
        "document_id": doc.id, "record_type": record_type, "record_id": record_id, "title": doc.title, "version": doc.version,
        "status": doc.status, "extraction_method": doc.extraction_method, "source_ref": doc.source_ref,
        "source_id": doc.source_id, "review_status": doc.review_status, "investigation_id": doc.investigation_id,
        "source_time": iso(doc.source_time) if doc.source_time else None, "indexed_at": iso(doc.indexed_at),
        "stale": stale, "note": doc.error_message, "link": src.detail_link(record_type, record_id, src.parent_id(record_type, live)),
        "chunks": [{"chunk_id": c.id, "position": c.position, "section": c.section, "text": c.text,
                    "char_start": c.char_start, "char_end": c.char_end, "document_version": c.document_version} for c in chunks],
    }
