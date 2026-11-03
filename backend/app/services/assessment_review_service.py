"""Human review decisions on assessments.

Append-only: every decision is a new AssessmentReview row; changing a
decision requires a stated reason and links to the row it supersedes.
Nothing here mutates the Assessment or triggers any downstream action --
a decision is a recorded human judgement, and the advisory score it was
made against is kept alongside it for comparison.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import Assessment
from app.models.assessment_review import AssessmentReview
from app.services import assessment_scoring_service, audit_service

# Documented, deliberately simple mapping used ONLY to show where a human
# decision differs from the advisory band. It is not a recommendation.
EXPECTED_DECISION_BY_BAND = {"high": "further_review_requested", "low": "accepted", "medium": None}


class ReviewError(ValueError):
    pass


def list_reviews(db: Session, organization_id: str, assessment_id: str) -> list[AssessmentReview]:
    return list(db.execute(select(AssessmentReview).where(
        AssessmentReview.organization_id == organization_id, AssessmentReview.assessment_id == assessment_id
    ).order_by(AssessmentReview.created_at.asc(), AssessmentReview.id)).scalars())


def submit_review(db: Session, assessment: Assessment, *, reviewer_user_id: Optional[str], decision: str, notes: str,
                  change_reason: Optional[str], information_flags: list[str], score_snapshot_id: Optional[str],
                  request_id: Optional[str] = None) -> AssessmentReview:
    org = assessment.organization_id
    if assessment.status == "archived":
        raise ReviewError("archived assessments are read-only and cannot be reviewed")

    history = list_reviews(db, org, assessment.id)
    previous = history[-1] if history else None
    if previous is not None and previous.decision != decision and not (change_reason and change_reason.strip()):
        raise ReviewError(f"change_reason is required when changing the previous decision ('{previous.decision}')")

    snapshot = None
    if score_snapshot_id:
        snapshot = assessment_scoring_service.get_snapshot(db, org, assessment.id, score_snapshot_id)
        if snapshot is None:
            raise ReviewError("score_snapshot_id does not refer to a score of this assessment")
    else:
        snaps = assessment_scoring_service.list_snapshots(db, org, assessment.id)
        snapshot = next((s for s in snaps if s.assessment_version == assessment.version), None)

    review = AssessmentReview(
        organization_id=org, assessment_id=assessment.id, assessment_version=assessment.version,
        score_snapshot_id=snapshot.id if snapshot else None, decision=decision, notes=notes.strip(),
        change_reason=change_reason.strip() if change_reason else None, information_flags=information_flags,
        advisory_score_at_review=snapshot.score if snapshot else None, advisory_band_at_review=snapshot.priority_band if snapshot else None,
        reviewer_user_id=reviewer_user_id, supersedes_review_id=previous.id if previous else None,
    )
    db.add(review)
    db.flush()
    audit_service.record(db, action="assessment.review", actor_user_id=reviewer_user_id, organization_id=org, target_type="assessment",
                         target_id=assessment.id, request_id=request_id,
                         context_metadata={"review_id": review.id, "decision": decision, "previous_decision": previous.decision if previous else None,
                                           "assessment_version": assessment.version, "information_flags": information_flags,
                                           "advisory_band_at_review": review.advisory_band_at_review})
    db.commit()
    db.refresh(review)
    return review


def comparison(latest: Optional[AssessmentReview], assessment: Assessment) -> dict:
    if latest is None:
        return {"available": False, "note": "No human decision has been recorded yet."}
    band = latest.advisory_band_at_review
    expected = EXPECTED_DECISION_BY_BAND.get(band) if band else None
    if band is None:
        note = "No advisory score existed for this assessment version when the decision was made."
        agreement = None
    elif expected is None:
        note = "Medium advisory priority carries no expected decision; the human decision stands on its own."
        agreement = None
    elif expected == latest.decision:
        note = f"Human decision matches what a '{band}' advisory priority would suggest."
        agreement = True
    else:
        note = f"Human decision ('{latest.decision}') differs from what a '{band}' advisory priority would suggest ('{expected}'). The human decision governs."
        agreement = False
    return {"available": True, "advisory_score_at_review": latest.advisory_score_at_review, "advisory_band_at_review": band,
            "human_decision": latest.decision, "expected_by_band": expected, "agreement": agreement, "note": note,
            "review_is_for_current_version": latest.assessment_version == assessment.version}


def review_status(history: list[AssessmentReview]) -> str:
    return history[-1].decision if history else "unreviewed"
