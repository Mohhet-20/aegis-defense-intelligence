"""Unified evidence registry (Phase 11, Phases C-D) built on the existing
`Evidence` model.

Evidence rows are REFERENCES to existing records (aegis://<type>/<id> URIs
for platform records) -- bytes are never copied. The only content stored on
an Evidence row is small analyst-authored text, as before.

Integrity vs. everything else: verify_integrity() answers one question -- do
the bytes (or text) currently in controlled storage hash to the value
recorded earlier? A 'match' is NOT evidence of source authenticity, of
being unaltered before first hashing, or of factual correctness. The check
history is an application audit trail, not a legally certified chain of
custody.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Role
from app.cv import storage
from app.models.assessment import Assessment
from app.models.data_source import DataSource
from app.models.detection_result import DetectionResult
from app.models.event import Event
from app.models.evidence import EVIDENCE_ACCESS_CLASSIFICATIONS, EVIDENCE_REVIEW_STATUSES, EVIDENCE_TYPES, Evidence
from app.models.inference_job import InferenceJob
from app.models.ingestion_job import IngestionJob
from app.models.investigation import Investigation
from app.models.investigation_workspace import EvidenceIntegrityCheck, InvestigationLink
from app.models.media_asset import MediaAsset
from app.models.model_record import ModelRecord
from app.models.observation import Observation
from app.models.raw_record import RawRecord
from app.models.track import Track
from app.models.tracking_job import TrackingJob
from app.services import audit_service, evidence_service
from app.services.investigation_service import assert_mutable
from app.services.timeutil import iso
from app.services.workspace_errors import conflict, invalid, not_found

INTEGRITY_DISCLAIMER = (
    "An integrity 'match' only shows that the stored bytes hash to the value recorded earlier. "
    "It does not establish who created the content, that the source was authentic, that the content "
    "was unaltered before it was first hashed, or that it is factually correct. This history is an "
    "application audit trail, not a legally certified chain of custody."
)
PLATFORM_RECORD_TYPES = ("media_asset", "detection", "track", "data_source", "assessment_version")
RESTRICTED_READ_ROLES = (Role.ADMINISTRATOR, Role.ANALYST, Role.INVESTIGATOR)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def evidence_visible(user: AuthenticatedUser, evidence: Evidence) -> bool:
    if evidence.organization_id != user.organization_id:
        return False
    if evidence.access_classification == "restricted":
        return user.role in RESTRICTED_READ_ROLES
    return True


def get_evidence_for_user(db: Session, user: AuthenticatedUser, evidence_id: str) -> Evidence:
    ev = evidence_service.get_evidence(db, user.organization_id, evidence_id)
    if ev is None or not evidence_visible(user, ev):
        raise not_found("Evidence")
    return ev


def _org_get(db: Session, model, organization_id: str, record_id: str, label: str):
    row = db.execute(select(model).where(model.id == record_id, model.organization_id == organization_id)).scalar_one_or_none()
    if row is None:
        raise not_found(label)
    return row


def _existing_reference(db: Session, organization_id: str, evidence_type: str, **ref) -> Optional[Evidence]:
    stmt = select(Evidence).where(
        Evidence.organization_id == organization_id, Evidence.evidence_type == evidence_type,
        Evidence.superseded_by_evidence_id.is_(None),
    )
    for col, val in ref.items():
        stmt = stmt.where(getattr(Evidence, col) == val)
    return db.execute(stmt.order_by(Evidence.created_at.asc(), Evidence.id.asc())).scalars().first()


def register_evidence(
    db: Session,
    investigation: Investigation,
    *,
    actor_user_id: str,
    evidence_type: str,
    title: str,
    summary: Optional[str] = None,
    record_id: Optional[str] = None,
    record_version: Optional[int] = None,
    event_id: Optional[str] = None,
    observation_id: Optional[str] = None,
    raw_record_id: Optional[str] = None,
    content: Optional[str] = None,
    external_reference_uri: Optional[str] = None,
    claimed_hash: Optional[str] = None,
    access_classification: str = "internal",
    captured_at: Optional[datetime] = None,
    processing_version: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Registers (or reuses) an Evidence row and associates it with the
    investigation in the caller's transaction. Returns (evidence, reused, link)."""
    if evidence_type not in EVIDENCE_TYPES:
        raise invalid(f"evidence_type must be one of {EVIDENCE_TYPES}")
    if access_classification not in EVIDENCE_ACCESS_CLASSIFICATIONS:
        raise invalid(f"access_classification must be one of {EVIDENCE_ACCESS_CLASSIFICATIONS}")
    assert_mutable(investigation)
    org = investigation.organization_id
    fields: dict = {"captured_at": captured_at, "processing_version": processing_version}
    uri = external_reference_uri
    hash_value: Optional[str] = None
    algo: Optional[str] = None
    dedupe: Optional[dict] = None

    if evidence_type in PLATFORM_RECORD_TYPES:
        if not record_id:
            raise invalid(f"evidence_type '{evidence_type}' requires record_id")
        if evidence_type == "media_asset":
            m = _org_get(db, MediaAsset, org, record_id, "Media asset")
            uri = f"aegis://media_asset/{m.id}"
            fields["media_asset_id"] = m.id
            hash_value, algo = m.content_hash, "sha256"
            dedupe = {"media_asset_id": m.id}
        elif evidence_type == "detection":
            d = _org_get(db, DetectionResult, org, record_id, "Detection")
            uri = f"aegis://detection/{d.id}"
            fields.update(detection_result_id=d.id, media_asset_id=d.media_asset_id)
            model = db.get(ModelRecord, d.model_record_id)
            fields["processing_version"] = processing_version or (f"{model.name}@{model.version}" if model else None)
            dedupe = {"detection_result_id": d.id}
        elif evidence_type == "track":
            t = _org_get(db, Track, org, record_id, "Track")
            uri = f"aegis://track/{t.id}"
            job = db.get(TrackingJob, t.tracking_job_id)
            if job is not None:
                fields["media_asset_id"] = job.media_asset_id
                fields["processing_version"] = processing_version or f"{job.tracker_key}@{job.tracker_version}"
            dedupe = {"external_reference_uri": uri}
        elif evidence_type == "data_source":
            s = _org_get(db, DataSource, org, record_id, "Data source")
            uri = f"aegis://data_source/{s.id}"
            fields["source_id"] = s.id
            dedupe = {"external_reference_uri": uri}
        else:  # assessment_version
            a = _org_get(db, Assessment, org, record_id, "Assessment")
            version = record_version or a.version
            if version < 1 or version > a.version:
                raise invalid(f"assessment has versions 1..{a.version}")
            uri = f"aegis://assessment_version/{a.id}?v={version}"
            fields["processing_version"] = processing_version or f"assessment v{version}"
            dedupe = {"external_reference_uri": uri}
    elif evidence_type == "observation":
        if not event_id:
            raise invalid("evidence_type 'observation' requires event_id")
        e = _org_get(db, Event, org, event_id, "Event")
        fields.update(event_id=e.id, source_id=e.source_id, captured_at=captured_at or e.observed_at)
        dedupe = {"event_id": e.id}
    elif evidence_type == "sensor_observation":
        if not observation_id:
            raise invalid("evidence_type 'sensor_observation' requires observation_id")
        o = _org_get(db, Observation, org, observation_id, "Observation")
        fields.update(observation_id=o.id, source_id=o.source_id, captured_at=captured_at or o.observed_at)
        dedupe = {"observation_id": o.id}
    elif evidence_type == "ingestion_record":
        if not raw_record_id:
            raise invalid("evidence_type 'ingestion_record' requires raw_record_id")
        r = _org_get(db, RawRecord, org, raw_record_id, "Raw record")
        fields["raw_record_id"] = r.id
        dedupe = {"raw_record_id": r.id}
    elif evidence_type in ("report", "analyst_note"):
        if not content:
            raise invalid(f"evidence_type '{evidence_type}' requires content")
        hash_value, algo = sha256_hex(content.encode("utf-8")), "sha256"
    else:  # document / media_reference: external URI only
        if not uri:
            raise invalid(f"evidence_type '{evidence_type}' requires external_reference_uri")
        if claimed_hash:
            hash_value = claimed_hash.strip().lower()
            algo = "sha256" if len(hash_value) == 64 else "unspecified"
        dedupe = {"external_reference_uri": uri}

    evidence = _existing_reference(db, org, evidence_type, **dedupe) if dedupe else None
    reused = evidence is not None
    if evidence is None:
        evidence = Evidence(
            organization_id=org, evidence_type=evidence_type, title=title, summary=summary,
            event_id=fields.get("event_id"), raw_record_id=fields.get("raw_record_id"),
            observation_id=fields.get("observation_id"),
            content=content if evidence_type in ("report", "analyst_note") else None,
            external_reference_uri=uri, integrity_hash=hash_value, integrity_hash_algorithm=algo,
            hash_recorded_at=datetime.now(timezone.utc) if hash_value else None,
            created_by_user_id=actor_user_id,
            detection_result_id=fields.get("detection_result_id"), media_asset_id=fields.get("media_asset_id"),
            source_id=fields.get("source_id"), access_classification=access_classification,
            captured_at=fields.get("captured_at"), processing_version=fields.get("processing_version"),
        )
        db.add(evidence)
        db.flush()
        audit_service.record(
            db, action="evidence.register", actor_user_id=actor_user_id, organization_id=org,
            target_type="evidence", target_id=evidence.id, request_id=request_id,
            context_metadata={"evidence_type": evidence_type, "investigation_id": investigation.id, "hash_recorded": bool(hash_value)},
        )

    from app.services import investigation_links_service

    link = investigation_links_service.link_record(
        db, investigation, record_type="evidence", record_id=evidence.id, note=None,
        actor_user_id=actor_user_id, request_id=request_id,
    )
    return evidence, reused, link


# ---- integrity -----------------------------------------------------------

def verify_integrity(db: Session, evidence: Evidence, *, actor_user_id: str, request_id: Optional[str] = None) -> EvidenceIntegrityCheck:
    result, algo, recorded, computed, detail = "not_file_backed", None, None, None, None
    if evidence.media_asset_id and evidence.evidence_type in ("media_asset", "media_reference"):
        media = db.get(MediaAsset, evidence.media_asset_id)
        if media is None or media.organization_id != evidence.organization_id:
            result, detail = "original_unavailable", "The media asset record no longer exists."
        else:
            algo = "sha256"
            recorded = evidence.integrity_hash or media.content_hash
            try:
                data = storage.read_bytes(media.storage_key)
            except FileNotFoundError:
                result, detail = "original_unavailable", "The stored file is missing from controlled storage."
            except (storage.PathTraversalError, OSError) as exc:
                result, detail = "original_unavailable", f"The stored file could not be read ({type(exc).__name__})."
            else:
                computed = sha256_hex(data)
                result = "match" if computed == recorded else "mismatch"
                detail = "Stored bytes hash to the recorded value." if result == "match" else "Stored bytes do NOT hash to the recorded value."
    elif evidence.content is not None:
        algo = evidence.integrity_hash_algorithm or "sha256"
        computed = sha256_hex(evidence.content.encode("utf-8"))
        recorded = evidence.integrity_hash
        if not recorded:
            result, detail = "no_recorded_hash", "No hash was recorded at registration; the computed value is shown but is not a baseline."
        else:
            result = "match" if computed == recorded else "mismatch"
            detail = "Stored text hashes to the recorded value." if result == "match" else "Stored text differs from what was hashed at registration."
    else:
        detail = "This evidence is a reference to a record or external location; there are no stored bytes to hash."
    check = EvidenceIntegrityCheck(
        organization_id=evidence.organization_id, evidence_id=evidence.id, result=result, algorithm=algo,
        recorded_hash=recorded, computed_hash=computed, detail=detail, checked_by_user_id=actor_user_id,
    )
    db.add(check)
    audit_service.record(
        db, action="evidence.verify_integrity", actor_user_id=actor_user_id, organization_id=evidence.organization_id,
        target_type="evidence", target_id=evidence.id, request_id=request_id, context_metadata={"result": result},
    )
    db.flush()
    return check


def list_integrity_checks(db: Session, evidence: Evidence) -> list[EvidenceIntegrityCheck]:
    return list(
        db.execute(
            select(EvidenceIntegrityCheck).where(EvidenceIntegrityCheck.evidence_id == evidence.id)
            .order_by(EvidenceIntegrityCheck.created_at.asc(), EvidenceIntegrityCheck.id.asc())
        ).scalars()
    )


# ---- provenance ----------------------------------------------------------

def build_provenance(db: Session, evidence: Evidence) -> dict:
    """Walks existing foreign keys to describe where the evidence came from.
    Unresolvable hops are reported as unavailable; unknown values are None."""
    org = evidence.organization_id
    chain: list[dict] = []
    limitations: list[str] = []

    def node(role, rtype, row, label, extra=None):
        chain.append({"role": role, "record_type": rtype, "record_id": row.id if row is not None else None,
                      "label": label, "available": row is not None, **(extra or {})})

    def fetch(model, rid):
        if not rid:
            return None
        row = db.get(model, rid)
        return row if row is not None and row.organization_id == org else None

    det = fetch(DetectionResult, evidence.detection_result_id)
    media = fetch(MediaAsset, evidence.media_asset_id) or (fetch(MediaAsset, det.media_asset_id) if det else None)
    if evidence.detection_result_id:
        node("derived_from", "detection_result", det,
             f"{det.class_label} (model confidence {det.confidence:.3f})" if det else "detection record unavailable",
             {"review_status": det.review_status if det else None})
        if det is not None:
            job = fetch(InferenceJob, det.inference_job_id)
            node("processed_by", "inference_job", job, f"{job.job_type} / {job.status}" if job else "inference job unavailable",
                 {"started_at": iso(job.started_at) if job else None, "finished_at": iso(job.finished_at) if job else None})
            model = db.get(ModelRecord, det.model_record_id)
            node("model", "model_record", model, f"{model.name}@{model.version}" if model else "model record unavailable")
    if media is not None or evidence.media_asset_id:
        node("original_artifact", "media_asset", media, media.declared_filename if media else "media asset unavailable",
             {"content_hash": media.content_hash if media else None, "hash_algorithm": "sha256" if media else None,
              "registered_at": iso(media.created_at) if media else None, "capture_time": None,
              "capture_time_note": "The platform records when media was registered, not when it was captured."})
    if evidence.event_id:
        ev = fetch(Event, evidence.event_id)
        node("references", "event", ev, ev.title if ev else "event unavailable",
             {"observed_at": iso(ev.observed_at) if ev else None, "ingested_at": iso(ev.ingested_at) if ev else None,
              "data_origin": ev.data_origin if ev else None, "recorded_provenance": ev.provenance if ev else None})
        if ev is not None and ev.ingestion_job_id:
            ij = fetch(IngestionJob, ev.ingestion_job_id)
            node("ingested_by", "ingestion_job", ij, f"{ij.job_type} / {ij.status}" if ij else "ingestion job unavailable")
    if evidence.observation_id:
        ob = fetch(Observation, evidence.observation_id)
        node("references", "observation", ob, ob.observation_type if ob else "observation unavailable",
             {"observed_at": iso(ob.observed_at) if ob else None, "ingested_at": iso(ob.ingested_at) if ob else None,
              "data_origin": ob.data_origin if ob else None, "quality_flags": list(ob.quality_flags or []) if ob else None,
              "recorded_provenance": ob.provenance if ob else None})
    if evidence.source_id:
        src = fetch(DataSource, evidence.source_id)
        node("source", "data_source", src, src.name if src else "source unavailable",
             {"source_type": src.source_type if src else None, "reliability_weight_configured": src.reliability_weight if src else None})
    else:
        limitations.append("Source is unknown (no data source recorded for this evidence).")
    if evidence.supersedes_evidence_id:
        node("supersedes", "evidence", fetch(Evidence, evidence.supersedes_evidence_id), "earlier evidence version")
    if evidence.superseded_by_evidence_id:
        node("superseded_by", "evidence", fetch(Evidence, evidence.superseded_by_evidence_id), "newer evidence version")
    if evidence.captured_at is None:
        limitations.append("Original capture/event time is unknown.")
    if not evidence.integrity_hash:
        limitations.append("No content hash was recorded, so integrity cannot be checked against a baseline.")
    limitations.append(INTEGRITY_DISCLAIMER)
    return {
        "evidence_id": evidence.id,
        "evidence_type": evidence.evidence_type,
        "source_reference": evidence.external_reference_uri,
        "times": {
            "registered_at": iso(evidence.created_at),
            "captured_at": iso(evidence.captured_at),  # None = unknown, never guessed
            "hash_recorded_at": iso(evidence.hash_recorded_at),
        },
        "processing_version": evidence.processing_version,
        "integrity_hash": evidence.integrity_hash,
        "integrity_hash_algorithm": evidence.integrity_hash_algorithm,
        "access_classification": evidence.access_classification,
        "review_status": evidence.review_status,
        "chain": chain,
        "limitations": limitations,
    }


# ---- review status + supersession ---------------------------------------

def set_review_status(db: Session, evidence: Evidence, *, review_status: str, note: Optional[str], actor_user_id: str, request_id: Optional[str] = None) -> Evidence:
    if review_status not in EVIDENCE_REVIEW_STATUSES:
        raise invalid(f"review_status must be one of {EVIDENCE_REVIEW_STATUSES}")
    previous = evidence.review_status
    evidence.review_status = review_status
    db.add(evidence)
    audit_service.record(
        db, action="evidence.review_status_change", actor_user_id=actor_user_id, organization_id=evidence.organization_id,
        target_type="evidence", target_id=evidence.id, request_id=request_id,
        context_metadata={"from": previous, "to": review_status, "note": note},
    )
    db.flush()
    return evidence


def supersede(
    db: Session, evidence: Evidence, *, actor_user_id: str, reason: str, title: Optional[str] = None,
    summary: Optional[str] = None, content: Optional[str] = None, request_id: Optional[str] = None,
) -> Evidence:
    """Append-only replacement: a NEW row is created; the old one is marked
    superseded but kept, with its hash and content untouched."""
    if evidence.superseded_by_evidence_id:
        raise conflict("This evidence has already been superseded")
    is_text = evidence.evidence_type in ("report", "analyst_note")
    if is_text and not content:
        raise invalid("Superseding a text evidence item requires new content")
    new_content = content if is_text else evidence.content
    new_hash = sha256_hex(new_content.encode()) if is_text else evidence.integrity_hash
    new = Evidence(
        organization_id=evidence.organization_id, evidence_type=evidence.evidence_type,
        title=title or evidence.title, summary=summary if summary is not None else evidence.summary,
        event_id=evidence.event_id, raw_record_id=evidence.raw_record_id, observation_id=evidence.observation_id,
        content=new_content, external_reference_uri=evidence.external_reference_uri,
        integrity_hash=new_hash, integrity_hash_algorithm=("sha256" if is_text else evidence.integrity_hash_algorithm),
        hash_recorded_at=datetime.now(timezone.utc) if new_hash else None,
        created_by_user_id=actor_user_id, detection_result_id=evidence.detection_result_id,
        media_asset_id=evidence.media_asset_id, source_id=evidence.source_id,
        access_classification=evidence.access_classification, captured_at=evidence.captured_at,
        processing_version=evidence.processing_version, supersedes_evidence_id=evidence.id,
    )
    db.add(new)
    db.flush()
    evidence.superseded_by_evidence_id = new.id
    db.add(evidence)
    links = db.execute(select(InvestigationLink).where(
        InvestigationLink.record_type == "evidence", InvestigationLink.record_id == evidence.id,
        InvestigationLink.organization_id == evidence.organization_id)).scalars().all()
    for link in links:
        db.add(InvestigationLink(
            organization_id=link.organization_id, investigation_id=link.investigation_id, record_type="evidence",
            record_id=new.id, note=f"supersedes {evidence.id}", linked_by_user_id=actor_user_id))
    audit_service.record(
        db, action="evidence.supersede", actor_user_id=actor_user_id, organization_id=evidence.organization_id,
        target_type="evidence", target_id=evidence.id, request_id=request_id,
        context_metadata={"new_evidence_id": new.id, "reason": reason},
    )
    db.flush()
    return new
