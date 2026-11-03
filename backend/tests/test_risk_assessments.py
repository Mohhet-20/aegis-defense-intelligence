"""Risk assessment records: read access, review workflow, and the
documented distinction between a model's output and a verified fact
(human_review_status starts "pending" and only a human can move it)."""
from __future__ import annotations


def _make_assessment(db, org, score=71.0, confidence=0.4):
    from datetime import datetime, timezone

    from app.models.model_record import ModelRecord
    from app.models.risk_assessment import RiskAssessment

    # (name, version) is unique in the schema (migration b15e0ps0001), so reuse the record.
    model_record = db.query(ModelRecord).filter_by(name="test-model", version="v0").first()
    if model_record is None:
        model_record = ModelRecord(name="test-model", version="v0", model_type="heuristic", status="registered")
        db.add(model_record)
        db.flush()
    assessment = RiskAssessment(
        organization_id=org.id,
        subject_type="event",
        subject_id="some-event-id",
        assessed_at=datetime.now(timezone.utc),
        method="unit_test",
        model_record_id=model_record.id,
        score=score,
        confidence=confidence,
        contributing_factors=[{"factor": "test", "weight": 1.0}],
        evidence_refs=[],
        explanation="Test-only explanation, not a real model output.",
        human_review_status="pending",
        data_origin="synthetic_demo",
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


def test_assessment_starts_pending_and_is_never_auto_confirmed(client, db, org, seeded_users, tokens, auth_header):
    assessment = _make_assessment(db, org)
    response = client.get(f"/api/v1/risk-assessments/{assessment.id}", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    assert response.json()["human_review_status"] == "pending"


def test_review_assessment_records_reviewer_and_timestamp(client, db, org, seeded_users, tokens, auth_header):
    assessment = _make_assessment(db, org)
    response = client.post(
        f"/api/v1/risk-assessments/{assessment.id}/review",
        json={"human_review_status": "dismissed", "reviewer_notes": "Not credible."},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["human_review_status"] == "dismissed"
    assert body["reviewer_notes"] == "Not credible."
    assert body["reviewed_at"] is not None
    assert body["reviewer_user_id"] is not None


def test_review_rejects_pending_as_a_target_status(client, db, org, seeded_users, tokens, auth_header):
    """A human can confirm or reject an assessment, but can't "review"
    it back into pending -- that's not a real decision."""
    assessment = _make_assessment(db, org)
    response = client.post(
        f"/api/v1/risk-assessments/{assessment.id}/review",
        json={"human_review_status": "pending"},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 422


def test_filter_assessments_by_review_status(client, db, org, seeded_users, tokens, auth_header):
    _make_assessment(db, org)
    second = _make_assessment(db, org, score=90.0)
    client.post(
        f"/api/v1/risk-assessments/{second.id}/review",
        json={"human_review_status": "confirmed"},
        headers=auth_header(tokens, "analyst"),
    )

    response = client.get(
        "/api/v1/risk-assessments", params={"human_review_status": "pending"}, headers=auth_header(tokens, "viewer")
    )
    assert response.json()["total"] == 1

    response = client.get(
        "/api/v1/risk-assessments", params={"human_review_status": "confirmed"}, headers=auth_header(tokens, "viewer")
    )
    assert response.json()["total"] == 1
