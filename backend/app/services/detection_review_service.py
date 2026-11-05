"""Analyst review of a DetectionResult, and promotion into the Evidence
layer (Section 9/14's required lineage: "... -> Detection
result -> Derived observation/evidence reference -> Analyst review").

The one rule this entire module exists to enforce: a DetectionResult is
NEVER turned into Evidence automatically. `promote_to_evidence()` is the
only function that creates the Evidence row, and it refuses outright
unless `review_status == "confirmed"` -- an unreviewed or rejected
detection can never become evidence, no matter who calls this or with
what arguments.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.detection_result import DetectionResult
from app.models.evidence import Evidence


class ReviewError(ValueError):
    pass


def review_detection(
    db: Session,
    detection: DetectionResult,
    *,
    review_status: str,
    reviewed_by_user_id: Optional[str],
    review_note: Optional[str] = None,
) -> DetectionResult:
    if review_status not in ("confirmed", "rejected"):
        raise ReviewError(f"review_status must be 'confirmed' or 'rejected' (got '{review_status}')")
    detection.review_status = review_status
    detection.reviewed_by_user_id = reviewed_by_user_id
    detection.reviewed_at = datetime.now(timezone.utc)
    detection.review_note = review_note
    db.add(detection)
    db.commit()
    db.refresh(detection)
    return detection


def promote_to_evidence(
    db: Session,
    detection: DetectionResult,
    *,
    title: str,
    summary: Optional[str],
    created_by_user_id: Optional[str],
) -> Evidence:
    """Section 9: 'never auto-promote an unreviewed detection into a
    consequential assessment.' This check is the enforcement of that
    rule, not just documentation of it."""
    if detection.review_status != "confirmed":
        raise ReviewError(
            f"only a confirmed detection can be promoted to evidence (this detection's review_status is '{detection.review_status}')"
        )

    evidence = Evidence(
        organization_id=detection.organization_id,
        evidence_type="media_reference",
        title=title,
        summary=summary,
        external_reference_uri=f"media_asset://{detection.media_asset_id}",
        detection_result_id=detection.id,
        created_by_user_id=created_by_user_id,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence
