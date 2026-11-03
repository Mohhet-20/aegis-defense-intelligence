"""EvidenceRelationship CRUD + review workflow (Phase 3, Sections 3D
and 11). See app/models/evidence_relationship.py's module docstring for
exactly how this differs from Phase 2's `EventCorrelation` (which is
untouched by this module and keeps working exactly as it did).

Every relationship here is DIRECTIONAL (source -> target) -- unlike
EventCorrelation's canonical (event_a < event_b) ordering, a `supports`
or `derived_from` relationship has a real, meaningful direction, so
this module never reorders the two sides.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.evidence_relationship import (
    REFERENCEABLE_TYPES,
    RELATIONSHIP_ORIGINS,
    RELATIONSHIP_REVIEW_STATUSES,
    RELATIONSHIP_TYPES,
    EvidenceRelationship,
)
from app.models.event import Event
from app.services import audit_service


class InvalidReferenceError(ValueError):
    pass


def _resolve_ref(db: Session, organization_id: str, ref_type: str, ref_id: str) -> None:
    if ref_type not in REFERENCEABLE_TYPES:
        raise InvalidReferenceError(f"'{ref_type}' is not a referenceable type (must be one of {REFERENCEABLE_TYPES})")
    model = Event if ref_type == "event" else Evidence
    row = db.execute(select(model).where(model.id == ref_id, model.organization_id == organization_id)).scalar_one_or_none()
    if row is None:
        raise InvalidReferenceError(f"no {ref_type} '{ref_id}' exists in this organization")


def _ref_columns(ref_type: str, ref_id: str) -> dict:
    if ref_type == "event":
        return {"event_id": ref_id, "evidence_id": None}
    return {"event_id": None, "evidence_id": ref_id}


def create_relationship(
    db: Session,
    *,
    organization_id: str,
    source_ref_type: str,
    source_ref_id: str,
    target_ref_type: str,
    target_ref_id: str,
    relationship_type: str,
    origin: str,
    explanation: str,
    supporting_metadata: Optional[dict] = None,
    created_by_user_id: Optional[str] = None,
    fusion_batch_id: Optional[str] = None,
) -> tuple[EvidenceRelationship, bool]:
    """Returns (relationship, created). `created=False` means an
    identical (source, target, relationship_type) relationship already
    existed and was returned as-is -- Section 11: "make duplicate
    review submissions safe" extends naturally to duplicate CREATE
    submissions too; this never silently creates a second row for the
    same link."""
    if relationship_type not in RELATIONSHIP_TYPES:
        raise ValueError(f"'{relationship_type}' is not a valid relationship_type (must be one of {RELATIONSHIP_TYPES})")
    if origin not in RELATIONSHIP_ORIGINS:
        raise ValueError(f"'{origin}' is not a valid origin (must be one of {RELATIONSHIP_ORIGINS})")
    if origin == "analyst_created" and not created_by_user_id:
        raise ValueError("an analyst_created relationship requires created_by_user_id")

    _resolve_ref(db, organization_id, source_ref_type, source_ref_id)
    _resolve_ref(db, organization_id, target_ref_type, target_ref_id)

    if source_ref_type == target_ref_type and source_ref_id == target_ref_id:
        raise ValueError("a relationship cannot link a record to itself")

    source_cols = _ref_columns(source_ref_type, source_ref_id)
    target_cols = _ref_columns(target_ref_type, target_ref_id)

    existing_stmt = select(EvidenceRelationship).where(
        EvidenceRelationship.organization_id == organization_id,
        EvidenceRelationship.relationship_type == relationship_type,
        EvidenceRelationship.source_event_id == source_cols["event_id"],
        EvidenceRelationship.source_evidence_id == source_cols["evidence_id"],
        EvidenceRelationship.target_event_id == target_cols["event_id"],
        EvidenceRelationship.target_evidence_id == target_cols["evidence_id"],
    )
    existing = db.execute(existing_stmt).scalar_one_or_none()
    if existing is not None:
        return existing, False

    relationship = EvidenceRelationship(
        organization_id=organization_id,
        source_event_id=source_cols["event_id"],
        source_evidence_id=source_cols["evidence_id"],
        target_event_id=target_cols["event_id"],
        target_evidence_id=target_cols["evidence_id"],
        relationship_type=relationship_type,
        origin=origin,
        explanation=explanation,
        supporting_metadata=supporting_metadata or {},
        review_status="candidate",
        created_by_user_id=created_by_user_id,
        fusion_batch_id=fusion_batch_id,
    )
    db.add(relationship)
    db.commit()
    db.refresh(relationship)
    return relationship, True


def get_relationship(db: Session, organization_id: str, relationship_id: str) -> Optional[EvidenceRelationship]:
    stmt = select(EvidenceRelationship).where(EvidenceRelationship.id == relationship_id, EvidenceRelationship.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_relationships_query(
    organization_id: str,
    *,
    relationship_type: Optional[str] = None,
    origin: Optional[str] = None,
    review_status: Optional[str] = None,
    ref_type: Optional[str] = None,
    ref_id: Optional[str] = None,
):
    stmt = select(EvidenceRelationship).where(EvidenceRelationship.organization_id == organization_id)
    if relationship_type:
        stmt = stmt.where(EvidenceRelationship.relationship_type == relationship_type)
    if origin:
        stmt = stmt.where(EvidenceRelationship.origin == origin)
    if review_status:
        stmt = stmt.where(EvidenceRelationship.review_status == review_status)
    if ref_type and ref_id:
        cols = _ref_columns(ref_type, ref_id)
        id_col = "event_id" if ref_type == "event" else "evidence_id"
        ref_value = cols[id_col]
        if ref_type == "event":
            stmt = stmt.where((EvidenceRelationship.source_event_id == ref_value) | (EvidenceRelationship.target_event_id == ref_value))
        else:
            stmt = stmt.where((EvidenceRelationship.source_evidence_id == ref_value) | (EvidenceRelationship.target_evidence_id == ref_value))
    return stmt.order_by(EvidenceRelationship.created_at.desc())


def review_relationship(
    db: Session,
    relationship: EvidenceRelationship,
    *,
    review_status: str,
    reviewed_by_user_id: str,
    review_note: Optional[str] = None,
    request_id: Optional[str] = None,
) -> EvidenceRelationship:
    """Confirm / reject / mark-uncertain -- the only way review_status
    ever moves away from "candidate". Idempotent: submitting the exact
    same decision again is a safe no-op (still re-stamps reviewed_at/
    reviewed_by, but the audit trail shows it as a repeat, never an
    error)."""
    if review_status not in RELATIONSHIP_REVIEW_STATUSES or review_status == "candidate":
        raise ValueError(f"'{review_status}' is not a valid review decision (must be one of {[s for s in RELATIONSHIP_REVIEW_STATUSES if s != 'candidate']})")

    prior_status = relationship.review_status
    relationship.review_status = review_status
    relationship.reviewed_by_user_id = reviewed_by_user_id
    relationship.reviewed_at = datetime.now(timezone.utc)
    relationship.review_note = review_note
    db.add(relationship)

    audit_service.record(
        db,
        action="evidence_relationship.review",
        actor_user_id=reviewed_by_user_id,
        organization_id=relationship.organization_id,
        target_type="evidence_relationship",
        target_id=relationship.id,
        request_id=request_id,
        context_metadata={"prior_status": prior_status, "new_status": review_status, "review_note": review_note},
    )
    db.commit()
    db.refresh(relationship)
    return relationship


def reverse_relationship(
    db: Session,
    relationship: EvidenceRelationship,
    *,
    actor_user_id: str,
    note: Optional[str] = None,
    request_id: Optional[str] = None,
) -> EvidenceRelationship:
    """Un-does a prior confirm/reject/uncertain decision WITHOUT
    deleting anything -- the relationship goes back to "candidate" for
    re-review, `is_reversed`/`last_reversed_at` record that this
    happened, and the full prior state is preserved in the audit trail
    ("reverse or supersede a prior decision with an audit
    record"). Reversing a relationship that is still "candidate" (never
    reviewed) is refused -- there is nothing to reverse."""
    if relationship.review_status == "candidate" and not relationship.is_reversed:
        raise ValueError("this relationship has never been reviewed -- there is no decision to reverse")

    prior_status = relationship.review_status
    relationship.review_status = "candidate"
    relationship.is_reversed = True
    relationship.last_reversed_at = datetime.now(timezone.utc)
    db.add(relationship)

    audit_service.record(
        db,
        action="evidence_relationship.reverse",
        actor_user_id=actor_user_id,
        organization_id=relationship.organization_id,
        target_type="evidence_relationship",
        target_id=relationship.id,
        request_id=request_id,
        context_metadata={"prior_status": prior_status, "new_status": "candidate", "note": note},
    )
    db.commit()
    db.refresh(relationship)
    return relationship


def get_review_history(db: Session, organization_id: str, relationship_id: str):
    return audit_service.list_for_target(db, organization_id, target_type="evidence_relationship", target_id=relationship_id)
