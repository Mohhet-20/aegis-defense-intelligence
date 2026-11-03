"""Analyst track annotations (Phase 5, Section 3E/12F). Never edits a
`Track` or `TrackObservation` row -- an annotation is purely additive,
and "correcting" an earlier one creates a new row pointing back at the
one it supersedes, exactly like Phase 3's review-history discipline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.track import Track
from app.models.track_annotation import ANNOTATION_TYPES, TrackAnnotation


class AnnotationError(ValueError):
    pass


def create_annotation(
    db: Session,
    *,
    organization_id: str,
    track: Track,
    annotation_type: str,
    note: Optional[str],
    created_by_user_id: Optional[str],
    supersedes_annotation_id: Optional[str] = None,
) -> TrackAnnotation:
    if annotation_type not in ANNOTATION_TYPES:
        raise AnnotationError(f"unknown annotation_type '{annotation_type}'. Allowed: {ANNOTATION_TYPES}")

    if supersedes_annotation_id:
        prior = db.execute(
            select(TrackAnnotation).where(TrackAnnotation.id == supersedes_annotation_id, TrackAnnotation.organization_id == organization_id)
        ).scalar_one_or_none()
        if prior is None:
            raise AnnotationError("the annotation to supersede was not found")
        if prior.track_id != track.id:
            raise AnnotationError("an annotation can only supersede a prior annotation on the SAME track")
        prior.superseded_at = datetime.now(timezone.utc)
        db.add(prior)

    annotation = TrackAnnotation(
        organization_id=organization_id,
        track_id=track.id,
        annotation_type=annotation_type,
        note=note,
        created_by_user_id=created_by_user_id,
        supersedes_annotation_id=supersedes_annotation_id,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation


def list_annotations_for_track(db: Session, organization_id: str, track_id: str) -> list[TrackAnnotation]:
    stmt = (
        select(TrackAnnotation)
        .where(TrackAnnotation.organization_id == organization_id, TrackAnnotation.track_id == track_id)
        .order_by(TrackAnnotation.created_at.asc())
    )
    return list(db.execute(stmt).scalars().all())
