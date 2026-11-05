"""Idempotent indexing of authoritative records into the derived
retrieval tables.

Rules:
* One RetrievalDocument per (org, record_type, record_id); re-indexing an
  unchanged record is a no-op (content_hash), a changed one bumps `version`
  and replaces its chunks. No duplicates are possible (unique constraints).
* Deleted records are invalidated: chunks are removed immediately, a metadata
  tombstone is kept for RETRIEVAL_TOMBSTONE_DAYS, then purged.
* Failures are recorded per record (status='error') and never abort a run.
* Services flush only; the caller commits."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.retrieval import INDEXABLE_RECORD_TYPES, RetrievalChunk, RetrievalDocument, RetrievalIndexRun
from app.retrieval.lexical import tokenize
from app.retrieval.text import chunk_text, normalize_text
from app.services import investigation_links_service, retrieval_sources as src
from app.services.timeutil import to_utc
from app.services.workspace_errors import invalid


settings = get_settings()

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(spec: src.DocSpec, text: str) -> str:
    h = hashlib.sha256()
    for part in (spec.title, spec.status, spec.review_status or "", spec.investigation_id or "",
                 spec.source_id or "", spec.extraction_method, text):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


def get_document(db: Session, organization_id: str, record_type: str, record_id: str) -> Optional[RetrievalDocument]:
    return db.execute(select(RetrievalDocument).where(
        RetrievalDocument.organization_id == organization_id, RetrievalDocument.record_type == record_type,
        RetrievalDocument.record_id == record_id)).scalar_one_or_none()


def _drop_chunks(db: Session, document_id: str) -> None:
    db.execute(delete(RetrievalChunk).where(RetrievalChunk.document_id == document_id))


def invalidate_record(db: Session, organization_id: str, record_type: str, record_id: str, reason: str) -> bool:
    doc = get_document(db, organization_id, record_type, record_id)
    if doc is None or doc.status == "invalidated":
        return False
    _drop_chunks(db, doc.id)
    doc.status, doc.retention_state = "invalidated", "invalidated"
    doc.chunk_count, doc.invalidated_at, doc.invalidation_reason = 0, _now(), reason[:200]
    doc.error_message = None
    db.flush()
    return True


def index_record(db: Session, organization_id: str, record_type: str, record_id: str) -> str:
    """Returns one of: created, updated, unchanged, invalidated, missing, error."""
    if record_type not in INDEXABLE_RECORD_TYPES:
        raise invalid(f"record_type must be one of {INDEXABLE_RECORD_TYPES}")
    row = src.load_live(db, organization_id, record_type, record_id)
    existing = get_document(db, organization_id, record_type, record_id)
    if row is None:
        return "invalidated" if invalidate_record(db, organization_id, record_type, record_id, "source_record_missing") else "missing"
    try:
        spec = src.build_doc(db, record_type, row)
        text = normalize_text(spec.text)[: settings.RETRIEVAL_MAX_DOC_CHARS]
        status = spec.status if spec.status != "indexed" else ("indexed" if text.strip() else "empty")
        # a heading-only document (no body text) is empty for retrieval purposes
        body = "\n".join(l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#"))
        if spec.status == "indexed" and not body.strip():
            status = "empty"
        spec.status = status
        digest = _hash(spec, text)
        if existing is not None and existing.content_hash == digest and existing.retention_state == "active" and existing.status == status:
            return "unchanged"
        now = _now()
        chunks = chunk_text(text, max_chars=settings.RETRIEVAL_CHUNK_CHARS, overlap=settings.RETRIEVAL_CHUNK_OVERLAP) if status != "empty" else []
        if existing is None:
            doc = RetrievalDocument(organization_id=organization_id, record_type=record_type, record_id=record_id, version=1,
                                    content_hash=digest, indexed_at=now, source_ref=spec.source_ref, extraction_method=spec.extraction_method)
            db.add(doc)
            result = "created"
        else:
            doc = existing
            _drop_chunks(db, doc.id)
            if doc.content_hash != digest:
                doc.version = (doc.version or 0) + 1
            result = "updated"
        doc.title = (spec.title or "")[:300]
        doc.source_ref, doc.extraction_method = spec.source_ref, spec.extraction_method
        doc.investigation_id, doc.source_id, doc.review_status = spec.investigation_id, spec.source_id, (spec.review_status or None)
        doc.source_time, doc.source_updated_at = spec.source_time, spec.source_updated_at
        doc.content_hash, doc.status, doc.error_message = digest, status, spec.note
        doc.retention_state, doc.invalidated_at, doc.invalidation_reason = "active", None, None
        doc.indexed_at, doc.chunk_count = now, len(chunks)
        db.flush()
        for c in chunks:
            db.add(RetrievalChunk(
                organization_id=organization_id, document_id=doc.id, record_type=record_type, record_id=record_id,
                document_version=doc.version, position=c.position, section=(c.section or None), text=c.text,
                text_lower=c.text.lower(), token_count=max(1, len(tokenize(c.text))), char_start=c.char_start,
                char_end=c.char_end, source_time=spec.source_time, indexed_at=now))
        db.flush()
        return result
    except Exception as exc:  # per-record isolation: record, never abort the run
        msg = f"{type(exc).__name__}: {str(exc)[:300]}"
        doc = existing or get_document(db, organization_id, record_type, record_id)
        if doc is None:
            doc = RetrievalDocument(organization_id=organization_id, record_type=record_type, record_id=record_id, version=1,
                                    content_hash="error", indexed_at=_now(), source_ref=f"{record_type}:{record_id}",
                                    extraction_method="none")
            db.add(doc)
        _drop_chunks(db, doc.id)
        doc.status, doc.error_message, doc.chunk_count, doc.indexed_at = "error", msg[:500], 0, _now()
        db.flush()
        return "error"


def _targets(db: Session, organization_id: str, record_types: list[str], investigation_id: Optional[str]) -> list[tuple[str, str]]:
    cap = settings.RETRIEVAL_MAX_INDEX_RECORDS
    out: list[tuple[str, str]] = []
    if investigation_id:
        from app.models.investigation import Investigation
        from app.models.investigation_workspace import InvestigationNote
        inv = db.get(Investigation, investigation_id)
        if inv is None or inv.organization_id != organization_id:
            raise invalid("investigation not found")
        out.append(("investigation", inv.id))
        for (nid,) in db.execute(select(InvestigationNote.id).where(InvestigationNote.investigation_id == inv.id)).all():
            out.append(("investigation_note", nid))
        for item in investigation_links_service.effective_records(db, inv):
            if item["row"] is not None and item["record_type"] in INDEXABLE_RECORD_TYPES:
                out.append((item["record_type"], item["record_id"]))
        seen, uniq = set(), []
        for t in out:
            if t[0] in record_types and t not in seen:
                seen.add(t)
                uniq.append(t)
        return uniq[:cap]
    for rt in record_types:
        for row in src.iter_rows(db, organization_id, rt, cap - len(out)):
            out.append((rt, row.id))
        if len(out) >= cap:
            break
    return out


def run_index(db: Session, *, organization_id: str, user_id: Optional[str], record_types: Optional[list[str]] = None,
              investigation_id: Optional[str] = None) -> RetrievalIndexRun:
    types = list(record_types or INDEXABLE_RECORD_TYPES)
    bad = [t for t in types if t not in INDEXABLE_RECORD_TYPES]
    if bad:
        raise invalid(f"unknown record types: {bad}")
    scope = f"investigation:{investigation_id}" if investigation_id else "org:" + ",".join(types)
    run = RetrievalIndexRun(organization_id=organization_id, scope=scope[:100], status="running",
                            triggered_by_user_id=user_id, started_at=_now(), counts={}, errors=[])
    db.add(run)
    db.flush()
    counts: dict[str, int] = {}
    errors: list[dict] = []
    deadline = time.monotonic() + settings.RETRIEVAL_INDEX_TIMEOUT_SECONDS
    partial = False
    targets = _targets(db, organization_id, types, investigation_id)
    for rt, rid in targets:
        if time.monotonic() > deadline:
            partial = True
            break
        res = index_record(db, organization_id, rt, rid)
        counts[res] = counts.get(res, 0) + 1
        if res == "error" and len(errors) < 20:
            d = get_document(db, organization_id, rt, rid)
            errors.append({"record_type": rt, "record_id": rid, "error": d.error_message if d else "unknown"})
    if not investigation_id and not partial:
        # Invalidate documents whose live record has disappeared.
        docs = db.execute(select(RetrievalDocument).where(
            RetrievalDocument.organization_id == organization_id, RetrievalDocument.record_type.in_(types),
            RetrievalDocument.status != "invalidated")).scalars().all()
        for d in docs:
            if src.load_live(db, organization_id, d.record_type, d.record_id) is None:
                if invalidate_record(db, organization_id, d.record_type, d.record_id, "source_record_missing"):
                    counts["invalidated"] = counts.get("invalidated", 0) + 1
    run.counts = dict(counts, targets=len(targets))
    run.errors = errors
    run.status = "partial" if partial else ("completed_with_errors" if errors else "completed")
    run.finished_at = _now()
    db.flush()
    return run


def purge_tombstones(db: Session, organization_id: str, *, older_than_days: Optional[int] = None) -> int:
    days = settings.RETRIEVAL_TOMBSTONE_DAYS if older_than_days is None else older_than_days
    cutoff = _now() - timedelta(days=days)
    ids = [r for (r,) in db.execute(select(RetrievalDocument.id).where(
        RetrievalDocument.organization_id == organization_id, RetrievalDocument.status == "invalidated",
        RetrievalDocument.invalidated_at.is_not(None), RetrievalDocument.invalidated_at <= cutoff)).all()]
    for i in ids:
        _drop_chunks(db, i)
    if ids:
        db.execute(delete(RetrievalDocument).where(RetrievalDocument.id.in_(ids)))
    db.flush()
    return len(ids)


def index_status(db: Session, organization_id: str) -> dict:
    by_status = dict(db.execute(select(RetrievalDocument.status, func.count()).where(
        RetrievalDocument.organization_id == organization_id).group_by(RetrievalDocument.status)).all())
    by_type = dict(db.execute(select(RetrievalDocument.record_type, func.count()).where(
        RetrievalDocument.organization_id == organization_id, RetrievalDocument.status != "invalidated").group_by(RetrievalDocument.record_type)).all())
    chunks = db.execute(select(func.count()).select_from(RetrievalChunk).where(RetrievalChunk.organization_id == organization_id)).scalar_one()
    stale = 0
    for rt in INDEXABLE_RECORD_TYPES:
        model = src.MODELS[rt]
        rows = db.execute(select(RetrievalDocument.source_updated_at, getattr(model, "updated_at")).join(
            model, model.id == RetrievalDocument.record_id).where(
            RetrievalDocument.organization_id == organization_id, RetrievalDocument.record_type == rt,
            RetrievalDocument.status != "invalidated")).all()
        for indexed_upd, live_upd in rows:
            if live_upd is not None and (indexed_upd is None or to_utc(live_upd)[0] > to_utc(indexed_upd)[0]):
                stale += 1
    last = db.execute(select(RetrievalIndexRun).where(RetrievalIndexRun.organization_id == organization_id)
                      .order_by(RetrievalIndexRun.started_at.desc()).limit(1)).scalar_one_or_none()
    errs = db.execute(select(RetrievalDocument.record_type, RetrievalDocument.record_id, RetrievalDocument.error_message).where(
        RetrievalDocument.organization_id == organization_id, RetrievalDocument.status == "error").limit(20)).all()
    return {
        "documents_by_status": by_status, "documents_by_type": by_type, "chunk_count": chunks, "stale_documents": stale,
        "last_run": None if last is None else {"id": last.id, "scope": last.scope, "status": last.status, "counts": last.counts,
                                                "started_at": last.started_at, "finished_at": last.finished_at},
        "errors": [{"record_type": t, "record_id": i, "error": m} for t, i, m in errs],
        "semantic_search_available": False,
    }
