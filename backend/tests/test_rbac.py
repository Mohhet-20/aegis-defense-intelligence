"""Role-based access control: every route decides
authorization server-side via require_permission -- never a
frontend-only check. These tests exercise the 403 cases directly."""
from __future__ import annotations


def test_viewer_cannot_create_a_source(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/sources",
        json={"name": "Attempted Source", "source_type": "manual"},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 403
    assert "source:manage" in response.json()["detail"]


def test_viewer_cannot_run_ingestion(client, seeded_users, tokens, source, auth_header):
    files = {"file": ("x.json", b"[]", "application/json")}
    response = client.post(
        "/api/v1/ingestion/jobs",
        data={"source_id": source.id},
        files=files,
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 403
    assert "ingestion:run" in response.json()["detail"]


def test_investigator_cannot_manage_users(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/users",
        json={
            "username": "newperson",
            "email": "newperson@test.example.com",
            "display_name": "New Person",
            "password": "SomePassword123!",
        },
        headers=auth_header(tokens, "investigator"),
    )
    assert response.status_code == 403


def test_investigator_can_manage_investigations(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/investigations",
        json={"title": "Investigator-created case", "priority": "normal"},
        headers=auth_header(tokens, "investigator"),
    )
    assert response.status_code == 201


def test_analyst_can_review_risk_but_viewer_cannot(client, db, org, seeded_users, tokens, auth_header):
    from datetime import datetime, timezone

    from app.models.model_record import ModelRecord
    from app.models.risk_assessment import RiskAssessment

    model_record = ModelRecord(name="test-model", version="v0", model_type="heuristic", status="registered")
    db.add(model_record)
    db.flush()
    assessment = RiskAssessment(
        organization_id=org.id,
        subject_type="event",
        subject_id="unrelated-id",
        assessed_at=datetime.now(timezone.utc),
        method="unit_test",
        model_record_id=model_record.id,
        score=50.0,
        confidence=0.5,
        contributing_factors=[],
        evidence_refs=[],
        human_review_status="pending",
        data_origin="synthetic_demo",
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    viewer_response = client.post(
        f"/api/v1/risk-assessments/{assessment.id}/review",
        json={"human_review_status": "confirmed"},
        headers=auth_header(tokens, "viewer"),
    )
    assert viewer_response.status_code == 403

    analyst_response = client.post(
        f"/api/v1/risk-assessments/{assessment.id}/review",
        json={"human_review_status": "confirmed"},
        headers=auth_header(tokens, "analyst"),
    )
    assert analyst_response.status_code == 200
    assert analyst_response.json()["human_review_status"] == "confirmed"


def test_administrator_has_every_permission_by_construction():
    from app.core.security import ROLE_PERMISSIONS, Permission, Role

    assert ROLE_PERMISSIONS[Role.ADMINISTRATOR] == set(Permission)


def test_audit_read_restricted_to_administrator(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/audit", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 403

    response = client.get("/api/v1/audit", headers=auth_header(tokens, "admin"))
    assert response.status_code == 200
