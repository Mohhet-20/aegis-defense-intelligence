"""Evidence CRUD (Phase 3, Section 3B). Every row must reference
something real -- enforced here BEFORE the DB's own CHECK constraint
ever gets a chance to reject it, so the caller gets a clear 400 instead
of a raw IntegrityError. See app/models/evidence.py for the full
reference-field contract.

Evidence rows backed by a real FK reference (event_id/raw_record_id/
observation_id) are never edited after creation -- same immutability
stance as RawRecord, because the whole point is an unaltered pointer to
something that already exists elsewhere. Only the free-text fields on
a `report`/`analyst_note` evidence item (title/summary/content) can be
updated, since those ARE the primary content, not a pointer to it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evidence import EVIDENCE_TYPES, Evidence

if TYPE_CHECKING:
    from app.models.observation import Observation

# evidence_type -> which reference field it is expected to carry.
# "report"/"analyst_note" instead require `content`; "document"/
# "media_reference" require `external_reference_uri`. This is the
# service-level version of the DB's CHECK constraint, checked first so
# a bad request gets a readable 400 explaining exactly what's missing.
_REQUIRES_EVENT = {"observation"}
_REQUIRES_RAW_RECORD = {"ingestion_record"}
_REQUIRES_OBSERVATION_ROW = {"sensor_observation"}
_REQUIRES_CONTENT = {"report", "analyst_note"}
_REQUIRES_URI = {"document", "media_reference", "media_asset", "detection", "track", "data_source", "assessment_version"}


def validate_evidence_payload(
    evidence_type: str,
    *,
    event_id: Optional[str],
    raw_record_id: Optional[str],
    observation_id: Optional[str],
    content: Optional[str],
    external_reference_uri: Optional[str],
) -> None:
    if evidence_type not in EVIDENCE_TYPES:
        raise ValueError(f"'{evidence_type}' is not a valid evidence_type (must be one of {EVIDENCE_TYPES})")
    if evidence_type in _REQUIRES_EVENT and not event_id:
        raise ValueError("evidence_type 'observation' requires event_id")
    if evidence_type in _REQUIRES_RAW_RECORD and not raw_record_id:
        raise ValueError("evidence_type 'ingestion_record' requires raw_record_id")
    if evidence_type in _REQUIRES_OBSERVATION_ROW and not observation_id:
        raise ValueError("evidence_type 'sensor_observation' requires observation_id")
    if evidence_type in _REQUIRES_CONTENT and not content:
        raise ValueError(f"evidence_type '{evidence_type}' requires content")
    if evidence_type in _REQUIRES_URI and not external_reference_uri:
        raise ValueError(f"evidence_type '{evidence_type}' requires external_reference_uri")
    if not any([event_id, raw_record_id, observation_id, content, external_reference_uri]):
        raise ValueError("an Evidence item must reference something real: event_id, raw_record_id, observation_id, content, or external_reference_uri")


def create_evidence(
    db: Session,
    *,
    organization_id: str,
    evidence_type: str,
    title: str,
    summary: Optional[str] = None,
    event_id: Optional[str] = None,
    raw_record_id: Optional[str] = None,
    observation_id: Optional[str] = None,
    content: Optional[str] = None,
    external_reference_uri: Optional[str] = None,
    integrity_hash: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
) -> Evidence:
    validate_evidence_payload(
        evidence_type,
        event_id=event_id,
        raw_record_id=raw_record_id,
        observation_id=observation_id,
        content=content,
        external_reference_uri=external_reference_uri,
    )
    evidence = Evidence(
        organization_id=organization_id,
        evidence_type=evidence_type,
        title=title,
        summary=summary,
        event_id=event_id,
        raw_record_id=raw_record_id,
        observation_id=observation_id,
        content=content,
        external_reference_uri=external_reference_uri,
        integrity_hash=integrity_hash,
        created_by_user_id=created_by_user_id,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def get_or_create_observation_evidence(
    db: Session, organization_id: str, observation: "Observation", *, created_by_user_id: Optional[str] = None
) -> Evidence:
    """Wraps a single Observation row as a "sensor_observation" Evidence
    item, reusing an already-wrapped one if it exists -- idempotent, so
    calling this twice for the same observation never creates a second
    wrapper.

    `Observation` is not itself a REFERENCEABLE_TYPE for
    `EvidenceRelationship` (app/models/evidence_relationship.py's
    REFERENCEABLE_TYPES is only `("event", "evidence")`), so any module
    that wants to link two Observations -- or an Observation and
    something else -- via EvidenceRelationship must wrap each
    Observation through this function first. Originally written as a
    private helper inside app/services/cross_source_comparison_service.py
   ; promoted here, the shared home for
    Evidence-creation logic, when app/services/spatial_relationship_service.py
    needed the exact same wrapping for spatially-close
    Observation pairs -- the same "promote on second use" discipline
    already applied to app/geo/distance.py's haversine functions."""
    stmt = select(Evidence).where(
        Evidence.organization_id == organization_id,
        Evidence.evidence_type == "sensor_observation",
        Evidence.observation_id == observation.id,
    )
    existing = db.execute(stmt).scalar_one_or_none()
    if existing is not None:
        return existing
    return create_evidence(
        db, organization_id=organization_id, evidence_type="sensor_observation",
        title=f"Sensor observation: {observation.observation_type} @ {observation.observed_at.isoformat()}",
        summary="Auto-wrapped so this Observation can participate in an EvidenceRelationship -- see get_or_create_observation_evidence's docstring.",
        observation_id=observation.id, created_by_user_id=created_by_user_id,
    )


def get_evidence(db: Session, organization_id: str, evidence_id: str) -> Optional[Evidence]:
    stmt = select(Evidence).where(Evidence.id == evidence_id, Evidence.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_evidence_query(organization_id: str, *, evidence_type: Optional[str] = None, event_id: Optional[str] = None):
    stmt = select(Evidence).where(Evidence.organization_id == organization_id)
    if evidence_type:
        stmt = stmt.where(Evidence.evidence_type == evidence_type)
    if event_id:
        stmt = stmt.where(Evidence.event_id == event_id)
    return stmt.order_by(Evidence.created_at.desc())


def update_evidence_content(db: Session, evidence: Evidence, *, title: Optional[str] = None, summary: Optional[str] = None, content: Optional[str] = None) -> Evidence:
    """Only ever touches the free-text fields -- never the reference
    fields (event_id/raw_record_id/observation_id/external_reference_uri),
    which are immutable once set (see module docstring)."""
    if title is not None:
        evidence.title = title
    if summary is not None:
        evidence.summary = summary
    if content is not None:
        if evidence.evidence_type not in _REQUIRES_CONTENT:
            raise ValueError(f"evidence_type '{evidence.evidence_type}' does not carry free-text content -- only 'report'/'analyst_note' items can be edited this way")
        evidence.content = content
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence
