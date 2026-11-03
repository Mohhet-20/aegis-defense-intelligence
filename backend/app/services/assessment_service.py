"""Intelligence assessment CRUD, evidence linking, and versioning.
An assessment is never allowed to declare
something hostile from a heuristic score alone -- this module only
ever stores what an analyst wrote and which evidence they cited; it
never computes a conclusion.

Versioning: every update that changes a tracked field snapshots the
PRE-update state into `AssessmentRevision` first, then applies the
change and bumps `version`. The snapshot is a plain dict of the fields
below, not a diff -- simple, always reconstructable, and exactly what
Section 12/17 ask to be testable ("version history").
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import (
    ASSESSMENT_EVIDENCE_ROLES,
    ASSESSMENT_STATUSES,
    Assessment,
    AssessmentEvidenceLink,
    AssessmentRevision,
)
from app.models.evidence import Evidence
from app.models.event import Event
from app.services import audit_service

# draft -> in_review -> published -> archived is the only forward path;
# published -> archived is also allowed directly. Nothing moves
# backward -- a correction is a new version via update_assessment(),
# or a whole new Assessment via supersede(), never a reopened draft.
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"in_review"},
    "in_review": {"draft", "published"},
    "published": {"archived"},
    "archived": set(),
}

_TRACKED_FIELDS = (
    "title", "question", "scope_description", "scope_start", "scope_end",
    "summary", "assumptions", "information_gaps", "confidence_level",
    "confidence_rationale", "status",
)


def _snapshot(assessment: Assessment) -> dict:
    out = {}
    for field in _TRACKED_FIELDS:
        value = getattr(assessment, field)
        out[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def create_assessment(
    db: Session,
    *,
    organization_id: str,
    title: str,
    question: str,
    author_user_id: Optional[str],
    scope_description: Optional[str] = None,
    scope_start=None,
    scope_end=None,
    summary: Optional[str] = None,
    assumptions: Optional[list] = None,
    information_gaps: Optional[list] = None,
    confidence_level: Optional[str] = None,
    confidence_rationale: Optional[str] = None,
) -> Assessment:
    if confidence_level is not None:
        from app.models.assessment import CONFIDENCE_LEVELS
        if confidence_level not in CONFIDENCE_LEVELS:
            raise ValueError(f"'{confidence_level}' is not a valid confidence_level (must be one of {CONFIDENCE_LEVELS})")

    assessment = Assessment(
        organization_id=organization_id,
        title=title,
        question=question,
        author_user_id=author_user_id,
        scope_description=scope_description,
        scope_start=scope_start,
        scope_end=scope_end,
        summary=summary,
        assumptions=assumptions or [],
        information_gaps=information_gaps or [],
        confidence_level=confidence_level,
        confidence_rationale=confidence_rationale,
        status="draft",
        version=1,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def get_assessment(db: Session, organization_id: str, assessment_id: str) -> Optional[Assessment]:
    stmt = select(Assessment).where(Assessment.id == assessment_id, Assessment.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_assessments_query(organization_id: str, *, status: Optional[str] = None):
    stmt = select(Assessment).where(Assessment.organization_id == organization_id)
    if status:
        stmt = stmt.where(Assessment.status == status)
    return stmt.order_by(Assessment.updated_at.desc())


def update_assessment(
    db: Session,
    assessment: Assessment,
    *,
    actor_user_id: Optional[str],
    change_note: Optional[str] = None,
    request_id: Optional[str] = None,
    **fields,
) -> Assessment:
    """Validates a status transition if one is requested, snapshots the
    pre-change state, applies every provided field, and bumps version.
    Unknown kwargs are rejected outright rather than silently ignored."""
    unknown = set(fields) - set(_TRACKED_FIELDS)
    if unknown:
        raise ValueError(f"unknown assessment field(s): {sorted(unknown)}")

    new_status = fields.get("status")
    if new_status is not None and new_status != assessment.status:
        if new_status not in ASSESSMENT_STATUSES:
            raise ValueError(f"'{new_status}' is not a valid status (must be one of {ASSESSMENT_STATUSES})")
        allowed = ALLOWED_STATUS_TRANSITIONS.get(assessment.status, set())
        if new_status not in allowed:
            raise ValueError(f"cannot move an assessment from '{assessment.status}' to '{new_status}' (allowed: {sorted(allowed) or 'none -- this is a terminal state'})")

    if "confidence_level" in fields and fields["confidence_level"] is not None:
        from app.models.assessment import CONFIDENCE_LEVELS
        if fields["confidence_level"] not in CONFIDENCE_LEVELS:
            raise ValueError(f"'{fields['confidence_level']}' is not a valid confidence_level (must be one of {CONFIDENCE_LEVELS})")

    revision = AssessmentRevision(
        organization_id=assessment.organization_id,
        assessment_id=assessment.id,
        version=assessment.version,
        snapshot=_snapshot(assessment),
        changed_by_user_id=actor_user_id,
        change_note=change_note,
    )
    db.add(revision)

    for key, value in fields.items():
        setattr(assessment, key, value)
    assessment.version += 1
    db.add(assessment)

    audit_service.record(
        db,
        action="assessment.update",
        actor_user_id=actor_user_id,
        organization_id=assessment.organization_id,
        target_type="assessment",
        target_id=assessment.id,
        request_id=request_id,
        context_metadata={"new_version": assessment.version, "changed_fields": sorted(fields), "change_note": change_note},
    )
    db.commit()
    db.refresh(assessment)
    return assessment


def supersede_assessment(db: Session, old_assessment: Assessment, new_assessment: Assessment, *, actor_user_id: Optional[str], request_id: Optional[str] = None) -> Assessment:
    old_assessment.superseded_by_assessment_id = new_assessment.id
    db.add(old_assessment)
    audit_service.record(
        db, action="assessment.supersede", actor_user_id=actor_user_id, organization_id=old_assessment.organization_id,
        target_type="assessment", target_id=old_assessment.id, request_id=request_id,
        context_metadata={"superseded_by_assessment_id": new_assessment.id},
    )
    db.commit()
    db.refresh(old_assessment)
    return old_assessment


def list_revisions(db: Session, organization_id: str, assessment_id: str) -> list[AssessmentRevision]:
    stmt = (
        select(AssessmentRevision)
        .where(AssessmentRevision.organization_id == organization_id, AssessmentRevision.assessment_id == assessment_id)
        .order_by(AssessmentRevision.version.asc())
    )
    return list(db.execute(stmt).scalars().all())


def link_evidence(
    db: Session,
    *,
    organization_id: str,
    assessment: Assessment,
    role: str,
    event_id: Optional[str] = None,
    evidence_id: Optional[str] = None,
    note: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> tuple[AssessmentEvidenceLink, bool]:
    """Returns (link, created). Idempotent: linking the same (event_id
    or evidence_id, role) twice returns the existing link rather than
    creating a duplicate. Validates that the referenced Event/Evidence
    actually exists in this organization -- an assessment can never
    cite evidence that doesn't exist ("the assessment must
    be traceable to its underlying evidence")."""
    if role not in ASSESSMENT_EVIDENCE_ROLES:
        raise ValueError(f"'{role}' is not a valid role (must be one of {ASSESSMENT_EVIDENCE_ROLES})")
    if bool(event_id) == bool(evidence_id):
        raise ValueError("exactly one of event_id or evidence_id must be set")

    if event_id:
        exists = db.execute(select(Event.id).where(Event.id == event_id, Event.organization_id == organization_id)).scalar_one_or_none()
        if exists is None:
            raise ValueError(f"no event '{event_id}' exists in this organization")
    else:
        exists = db.execute(select(Evidence.id).where(Evidence.id == evidence_id, Evidence.organization_id == organization_id)).scalar_one_or_none()
        if exists is None:
            raise ValueError(f"no evidence item '{evidence_id}' exists in this organization")

    existing_stmt = select(AssessmentEvidenceLink).where(
        AssessmentEvidenceLink.assessment_id == assessment.id,
        AssessmentEvidenceLink.role == role,
        AssessmentEvidenceLink.event_id == event_id,
        AssessmentEvidenceLink.evidence_id == evidence_id,
    )
    existing = db.execute(existing_stmt).scalar_one_or_none()
    if existing is not None:
        return existing, False

    link = AssessmentEvidenceLink(
        organization_id=organization_id, assessment_id=assessment.id, event_id=event_id, evidence_id=evidence_id, role=role, note=note,
    )
    db.add(link)
    audit_service.record(
        db, action="assessment.link_evidence", actor_user_id=actor_user_id, organization_id=organization_id,
        target_type="assessment", target_id=assessment.id, request_id=request_id,
        context_metadata={"role": role, "event_id": event_id, "evidence_id": evidence_id},
    )
    db.commit()
    db.refresh(link)
    return link, True


def list_evidence_links(db: Session, organization_id: str, assessment_id: str) -> list[AssessmentEvidenceLink]:
    stmt = select(AssessmentEvidenceLink).where(AssessmentEvidenceLink.organization_id == organization_id, AssessmentEvidenceLink.assessment_id == assessment_id)
    return list(db.execute(stmt).scalars().all())
