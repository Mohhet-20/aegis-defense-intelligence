"""Structured citations that are built from, and re-verified
against, persisted records and the requesting user's CURRENT permissions.

Statuses
  verified        record exists, user may read it, and the quoted text is still present
  source_changed  record exists and is readable but the quoted text no longer appears
  unavailable     record no longer exists (or never existed in this organization)
  access_revoked  record exists but the user may not read it now. Title, quote and
                  link are withheld so the citation cannot leak anything.
  unverified      the citation id was not one of the sources actually retrieved
                  (e.g. a model produced an id that does not exist)
Nothing here invents titles, page numbers or locations: only stored values
and character offsets inside the indexed text are used."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser
from app.retrieval.lexical import excerpt
from app.retrieval.text import body_text, normalize_text
from app.services import retrieval_index_service as idx, retrieval_sources as src
from app.services.timeutil import iso

CITATION_STATUSES = ("verified", "source_changed", "unavailable", "access_revoked", "unverified")


def _squash(s: str) -> str:
    return " ".join((s or "").replace("…", " ").split())


def _body(text: str) -> str:
    return body_text(text)


def base(record_type: str, record_id: str, **kw) -> dict:
    d = {"record_type": record_type, "record_id": record_id, "document_version": None, "chunk_position": None,
         "title": None, "section": None, "quote": None, "source_time": None, "link": None,
         "status": "verified", "status_note": None}
    d.update(kw)
    return d


def make_citation(db: Session, user: AuthenticatedUser, record_type: str, record_id: str, *,
                  quote: Optional[str] = None, chunk_position: Optional[int] = None, section: Optional[str] = None,
                  document_version: Optional[int] = None) -> Optional[dict]:
    """None when the record does not exist or the user may not read it."""
    live = src.load_live(db, user.organization_id, record_type, record_id)
    if live is None or not src.can_view(db, user, record_type, live):
        return None
    spec = src.build_doc(db, record_type, live)
    doc = idx.get_document(db, user.organization_id, record_type, record_id)
    if quote is None:
        quote = excerpt(_body(normalize_text(spec.text)), [], 280) or None
    return base(
        record_type, record_id, document_version=document_version if document_version is not None else (doc.version if doc and doc.status != "invalidated" else None),
        chunk_position=chunk_position, title=spec.title, section=section, quote=quote,
        source_time=iso(spec.source_time) if spec.source_time else None,
        link=src.detail_link(record_type, record_id, src.parent_id(record_type, live)))


def verify_citation(db: Session, user: AuthenticatedUser, cit: dict) -> dict:
    """Re-check one citation against live data and current permissions."""
    rtype, rid = cit.get("record_type"), cit.get("record_id")
    out = base(rtype or "", rid or "", document_version=cit.get("document_version"), chunk_position=cit.get("chunk_position"),
               section=cit.get("section"))
    if "id" in cit:
        out["id"] = cit["id"]
    if rtype not in src.MODELS or not isinstance(rid, str):
        out.update(status="unverified", status_note="Not a recognised record reference.")
        return out
    live = src.load_live(db, user.organization_id, rtype, rid)
    if live is None:
        out.update(status="unavailable", status_note="The record no longer exists or is not in your organization.")
        return out
    if not src.can_view(db, user, rtype, live):
        out.update(status="access_revoked", status_note="You no longer have access to this record.")
        return out
    spec = src.build_doc(db, rtype, live)
    full = normalize_text(spec.text)
    text, body = _squash(full), _squash(body_text(full))
    out.update(title=spec.title, source_time=iso(spec.source_time) if spec.source_time else None,
               link=src.detail_link(rtype, rid, src.parent_id(rtype, live)))
    q = cit.get("quote")
    if q:
        if _squash(q) in body or _squash(q) in text:
            out.update(quote=q, status="verified")
        else:
            out.update(status="source_changed", status_note="The record has changed since this citation was made; the quoted text no longer appears. The original quote is not shown.")
    else:
        out.update(status="verified")
    doc = idx.get_document(db, user.organization_id, rtype, rid)
    if out["status"] == "verified" and cit.get("document_version") and doc and doc.version != cit["document_version"]:
        out["status_note"] = f"Index version is now {doc.version} (cited {cit['document_version']}); the quoted text is unchanged."
    return out


def verify_all(db: Session, user: AuthenticatedUser, citations: list[dict]) -> list[dict]:
    return [verify_citation(db, user, c) for c in citations]
