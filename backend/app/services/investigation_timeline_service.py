"""Unified investigation timeline, computed on read from
existing persisted records -- nothing is stored or back-filled.

Timestamp semantics
-------------------
Every entry has ONE `time_kind` so different clocks are never blended:
event_time, observation_time, capture_time, registration_time,
ingestion_time, processing_time, review_time, note_time, status_change,
association_time, integrity_check_time, record_created.
Valid timestamps are normalised to UTC. The database stores UTC; a naive
value is read as UTC and flagged `assumed_utc`. Original source offsets are
reported only if the record's own provenance carries one. A timestamp that
is not recorded yields an entry with `timestamp: null`, `time_known: false`,
sorted last. Order is stable: (known first, timestamp, kind rank, record
type, record id, entry id). Chronological proximity does not imply causation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment_review import AssessmentReview
from app.models.inference_job import InferenceJob
from app.models.ingestion_job import IngestionJob
from app.models.investigation import Investigation
from app.models.investigation_workspace import EvidenceIntegrityCheck, InvestigationNote
from app.models.tracking_job import TrackingJob
from app.services import investigation_links_service as links
from app.services import investigation_service
from app.services.timeutil import iso, to_utc

NO_CAUSATION_NOTICE = (
    "Entries are ordered by recorded time only. Closeness in time does not show that one record caused, "
    "explains or is related to another."
)
MAX_ENTRIES = 5000
KIND_RANK = {
    "event_time": 10, "observation_time": 11, "capture_time": 12, "record_created": 20, "registration_time": 21,
    "ingestion_time": 30, "processing_time": 40, "association_time": 50, "integrity_check_time": 55,
    "review_time": 60, "note_time": 70, "status_change": 80,
}
TIMELINE_RECORD_TYPES = (
    "event", "observation", "media_asset", "assessment", "evidence", "detection_result", "track",
    "ingestion_job", "inference_job", "tracking_job", "note", "investigation", "data_source", "sensor",
)


def _entry(record_type, record_id, kind, dt: Optional[datetime], title, *, source_id=None, details=None, tz=None, missing_note=None):
    aware, assumed = to_utc(dt)
    return {
        "entry_id": f"{record_type}:{record_id}:{kind}",
        "record_type": record_type, "record_id": record_id, "time_kind": kind,
        "timestamp": iso(aware), "time_known": aware is not None, "assumed_utc": assumed,
        "original_timezone": tz,
        "missing_time_note": (missing_note or "No timestamp is recorded for this value.") if aware is None else None,
        "title": title, "source_id": source_id, "details": details or {},
        "_sort": aware,
    }


def _prov_tz(provenance) -> Optional[str]:
    if isinstance(provenance, dict):
        for key in ("original_timezone", "timezone", "tz"):
            if isinstance(provenance.get(key), str):
                return provenance[key]
    return None


def build_entries(db: Session, investigation: Investigation) -> list[dict]:
    org = investigation.organization_id
    out: list[dict] = []
    job_seen: set[str] = set()

    def add_ingestion_job(job_id):
        if not job_id or ("i", job_id) in job_seen:
            return
        job_seen.add(("i", job_id))
        j = db.get(IngestionJob, job_id)
        if j is not None and j.organization_id == org:
            out.append(_entry("ingestion_job", j.id, "processing_time", j.started_at, f"Ingestion job {j.job_type} started ({j.status})",
                              source_id=j.source_id, details={"accepted": j.accepted_count, "rejected": j.rejected_count}))

    def add_inference_job(job_id):
        if not job_id or ("f", job_id) in job_seen:
            return
        job_seen.add(("f", job_id))
        j = db.get(InferenceJob, job_id)
        if j is not None and j.organization_id == org:
            out.append(_entry("inference_job", j.id, "processing_time", j.started_at, f"Inference job {j.job_type} ({j.status})",
                              missing_note="Job has not started or start time was not recorded."))

    for rec in links.effective_records(db, investigation):
        rtype, rid, row, link = rec["record_type"], rec["record_id"], rec["row"], rec["link"]
        if row is None:
            continue
        if link is not None:
            out.append(_entry(rtype, rid, "association_time", link.created_at, f"{rtype.replace('_', ' ').title()} linked to investigation",
                              details={"link_id": link.id, "note": link.note, "origin": rec["origin"]}))
        if rtype == "event":
            out.append(_entry("event", rid, "event_time", row.observed_at, row.title, source_id=row.source_id,
                              tz=_prov_tz(row.provenance), details={"data_origin": row.data_origin}))
            out.append(_entry("event", rid, "ingestion_time", row.ingested_at, f"Event ingested: {row.title}", source_id=row.source_id))
            add_ingestion_job(row.ingestion_job_id)
        elif rtype == "observation":
            out.append(_entry("observation", rid, "observation_time", row.observed_at, f"{row.observation_type} observation",
                              source_id=row.source_id, tz=_prov_tz(row.provenance),
                              details={"validation_status": row.validation_status, "quality_flags": list(row.quality_flags or [])}))
            out.append(_entry("observation", rid, "ingestion_time", row.ingested_at, f"Observation ingested ({row.observation_type})",
                              source_id=row.source_id, missing_note="Ingestion time was not recorded for this observation."))
            add_ingestion_job(row.ingestion_job_id)
        elif rtype == "media_asset":
            out.append(_entry("media_asset", rid, "registration_time", row.created_at, f"Media registered: {row.declared_filename}"))
            out.append(_entry("media_asset", rid, "capture_time", None, f"Capture time of {row.declared_filename}",
                              missing_note="The platform does not record when this media was captured."))
        elif rtype == "assessment":
            out.append(_entry("assessment", rid, "record_created", row.created_at, f"Assessment created: {row.title}",
                              details={"version": row.version, "status": row.status}))
            for rv in db.execute(select(AssessmentReview).where(AssessmentReview.assessment_id == rid, AssessmentReview.organization_id == org)
                                 .order_by(AssessmentReview.created_at.asc(), AssessmentReview.id.asc())).scalars():
                out.append(_entry("assessment", rid, "review_time", rv.created_at, f"Assessment review: {rv.decision} (v{rv.assessment_version})",
                                  details={"review_id": rv.id, "decision": rv.decision}))
        elif rtype == "evidence":
            out.append(_entry("evidence", rid, "registration_time", row.created_at, f"Evidence registered: {row.title}",
                              source_id=row.source_id, details={"evidence_type": row.evidence_type}))
            out.append(_entry("evidence", rid, "capture_time", row.captured_at, f"Original time of evidence: {row.title}",
                              source_id=row.source_id, missing_note="Original capture/event time is unknown for this evidence."))
            for ck in db.execute(select(EvidenceIntegrityCheck).where(EvidenceIntegrityCheck.evidence_id == rid, EvidenceIntegrityCheck.organization_id == org)
                                 .order_by(EvidenceIntegrityCheck.created_at.asc(), EvidenceIntegrityCheck.id.asc())).scalars():
                out.append(_entry("evidence", rid, "integrity_check_time", ck.created_at, f"Integrity check: {ck.result}",
                                  details={"check_id": ck.id, "result": ck.result, "note": "Integrity only; not authenticity or correctness."}))
        elif rtype == "detection_result":
            out.append(_entry("detection_result", rid, "processing_time", row.created_at, f"Detection produced: {row.class_label}",
                              details={"model_confidence": row.confidence}))
            if row.reviewed_at is not None:
                out.append(_entry("detection_result", rid, "review_time", row.reviewed_at, f"Detection reviewed: {row.review_status}"))
            add_inference_job(row.inference_job_id)
        elif rtype == "track":
            out.append(_entry("track", rid, "processing_time", row.created_at, f"Track {row.sequence_track_id} produced"))
            tj = db.get(TrackingJob, row.tracking_job_id)
            if tj is not None and tj.organization_id == org and ("t", tj.id) not in job_seen:
                job_seen.add(("t", tj.id))
                out.append(_entry("tracking_job", tj.id, "processing_time", tj.created_at, f"Tracking job {tj.tracker_key}@{tj.tracker_version} ({tj.status})"))
        elif rtype in ("data_source", "sensor"):
            pass  # association entry only

    for n in db.execute(select(InvestigationNote).where(InvestigationNote.investigation_id == investigation.id)
                        .order_by(InvestigationNote.created_at.asc(), InvestigationNote.id.asc())).scalars():
        out.append(_entry("note", n.id, "note_time", n.created_at, f"Note ({n.note_kind.replace('_', ' ')})",
                          details={"note_kind": n.note_kind, "version": n.version, "author_user_id": n.author_user_id}))
    for h in investigation_service.list_status_history(db, investigation):
        out.append(_entry("investigation", investigation.id, "status_change", h.created_at,
                          f"Status {h.from_status or '(new)'} -> {h.to_status}", details={"reason": h.reason, "history_id": h.id, "changed_by_user_id": h.changed_by_user_id}))
    return out


def sort_entries(entries: list[dict]) -> list[dict]:
    far = datetime.max
    return sorted(
        entries,
        key=lambda e: (
            0 if e["time_known"] else 1,
            e["_sort"].replace(tzinfo=None) if e["_sort"] else far,
            KIND_RANK.get(e["time_kind"], 99), e["record_type"], e["record_id"], e["entry_id"],
        ),
    )


def get_timeline(
    db: Session, investigation: Investigation, *, start: Optional[datetime] = None, end: Optional[datetime] = None,
    record_types: Optional[list[str]] = None, time_kinds: Optional[list[str]] = None, source_id: Optional[str] = None,
    include_unknown_times: bool = True, page: int = 1, page_size: int = 50,
) -> dict:
    entries = sort_entries(build_entries(db, investigation))
    s = to_utc(start)[0]
    e = to_utc(end)[0]
    kept = []
    for x in entries:
        if record_types and x["record_type"] not in record_types:
            continue
        if time_kinds and x["time_kind"] not in time_kinds:
            continue
        if source_id and x["source_id"] != source_id:
            continue
        if not x["time_known"]:
            if (s or e) or not include_unknown_times:
                continue  # a date range can only match entries that have a time
        else:
            if s and x["_sort"] < s:
                continue
            if e and x["_sort"] > e:
                continue
        kept.append(x)
    truncated = len(kept) > MAX_ENTRIES
    kept = kept[:MAX_ENTRIES]
    page = max(page, 1)
    page_size = max(1, min(page_size, 200))
    window = kept[(page - 1) * page_size: page * page_size]
    items = [{k: v for k, v in x.items() if k != "_sort"} for x in window]
    return {
        "items": items, "total": len(kept), "page": page, "page_size": page_size, "truncated": truncated,
        "unknown_time_entries": sum(1 for x in kept if not x["time_known"]),
        "notice": NO_CAUSATION_NOTICE,
        "timestamp_semantics": "All timestamps are UTC. 'assumed_utc' marks values stored without an offset. Distinct time_kind values are never merged.",
    }
