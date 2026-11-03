"""Intelligence assessment tests. Section 17
requires: evidence traceability, supporting/contradicting evidence,
missing information, unauthorized updates, version history.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.data_source import DataSource
from app.models.event import Event
from app.services import assessment_service

pytestmark = pytest.mark.usefixtures("referenced_rows")  # real rows for the ids these tests reference (PostgreSQL enforces FKs)


def _event(db, org, source, **overrides) -> Event:
    defaults = dict(
        organization_id=org.id, source_id=source.id, event_type="perimeter_motion", title="E",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        data_origin="user_upload",
    )
    defaults.update(overrides)
    event = Event(**defaults)
    db.add(event)
    db.flush()
    return event


def test_create_assessment_starts_at_version_1_draft(db, org):
    assessment = assessment_service.create_assessment(db, organization_id=org.id, title="T", question="Q?", author_user_id="user-1")
    assert assessment.version == 1
    assert assessment.status == "draft"


def test_invalid_confidence_level_is_rejected(db, org):
    with pytest.raises(ValueError):
        assessment_service.create_assessment(db, organization_id=org.id, title="T", question="Q?", author_user_id="user-1", confidence_level="extremely-sure")


def test_status_transitions_follow_the_allowed_graph(db, org):
    assessment = assessment_service.create_assessment(db, organization_id=org.id, title="T", question="Q?", author_user_id="user-1")

    # draft -> published directly is not allowed
    with pytest.raises(ValueError):
        assessment_service.update_assessment(db, assessment, actor_user_id="user-1", status="published")

    in_review = assessment_service.update_assessment(db, assessment, actor_user_id="user-1", status="in_review")
    assert in_review.status == "in_review"

    published = assessment_service.update_assessment(db, in_review, actor_user_id="user-1", status="published")
    assert published.status == "published"

    # published -> archived is allowed; published -> draft is not
    with pytest.raises(ValueError):
        assessment_service.update_assessment(db, published, actor_user_id="user-1", status="draft")

    archived = assessment_service.update_assessment(db, published, actor_user_id="user-1", status="archived")
    assert archived.status == "archived"

    # archived is terminal
    with pytest.raises(ValueError):
        assessment_service.update_assessment(db, archived, actor_user_id="user-1", status="draft")


def test_every_update_bumps_version_and_writes_a_revision_snapshot(db, org):
    assessment = assessment_service.create_assessment(db, organization_id=org.id, title="Original Title", question="Q?", author_user_id="user-1")
    updated = assessment_service.update_assessment(db, assessment, actor_user_id="user-1", title="Revised Title", change_note="Fixed a typo.")
    assert updated.version == 2
    assert updated.title == "Revised Title"

    revisions = assessment_service.list_revisions(db, org.id, assessment.id)
    assert len(revisions) == 1
    assert revisions[0].version == 1  # the PRE-update state
    assert revisions[0].snapshot["title"] == "Original Title"
    assert revisions[0].change_note == "Fixed a typo."

    updated_again = assessment_service.update_assessment(db, updated, actor_user_id="user-1", title="Third Title")
    assert updated_again.version == 3
    revisions_after = assessment_service.list_revisions(db, org.id, assessment.id)
    assert len(revisions_after) == 2
    assert [r.version for r in revisions_after] == [1, 2]


def test_unknown_field_is_rejected(db, org):
    assessment = assessment_service.create_assessment(db, organization_id=org.id, title="T", question="Q?", author_user_id="user-1")
    with pytest.raises(ValueError):
        assessment_service.update_assessment(db, assessment, actor_user_id="user-1", not_a_real_field="x")


def test_evidence_traceability_supporting_and_contradicting(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    supporting_event = _event(db, org, source, title="Supporting")
    contradicting_event = _event(db, org, source, title="Contradicting")
    db.commit()

    assessment = assessment_service.create_assessment(db, organization_id=org.id, title="T", question="Q?", author_user_id="user-1")

    support_link, created = assessment_service.link_evidence(
        db, organization_id=org.id, assessment=assessment, role="supporting", event_id=supporting_event.id, actor_user_id="user-1",
    )
    assert created is True
    assert support_link.role == "supporting"

    contradict_link, _ = assessment_service.link_evidence(
        db, organization_id=org.id, assessment=assessment, role="contradicting", event_id=contradicting_event.id, actor_user_id="user-1",
    )
    assert contradict_link.role == "contradicting"

    links = assessment_service.list_evidence_links(db, org.id, assessment.id)
    assert len(links) == 2
    roles = {l.event_id: l.role for l in links}
    assert roles[supporting_event.id] == "supporting"
    assert roles[contradicting_event.id] == "contradicting"


def test_linking_evidence_to_a_nonexistent_event_is_rejected(db, org):
    assessment = assessment_service.create_assessment(db, organization_id=org.id, title="T", question="Q?", author_user_id="user-1")
    with pytest.raises(ValueError):
        assessment_service.link_evidence(db, organization_id=org.id, assessment=assessment, role="supporting", event_id="does-not-exist", actor_user_id="user-1")


def test_duplicate_evidence_link_is_idempotent(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    event = _event(db, org, source, title="E")
    db.commit()
    assessment = assessment_service.create_assessment(db, organization_id=org.id, title="T", question="Q?", author_user_id="user-1")

    first, created_first = assessment_service.link_evidence(db, organization_id=org.id, assessment=assessment, role="supporting", event_id=event.id, actor_user_id="user-1")
    second, created_second = assessment_service.link_evidence(db, organization_id=org.id, assessment=assessment, role="supporting", event_id=event.id, actor_user_id="user-2")
    assert created_first is True
    assert created_second is False
    assert first.id == second.id


def test_information_gaps_and_assumptions_are_stored_as_stated(db, org):
    """These are the analyst's own stated uncertainty -- never inferred
    or auto-generated by this platform."""
    assessment = assessment_service.create_assessment(
        db, organization_id=org.id, title="T", question="Q?", author_user_id="user-1",
        assumptions=["Assumes the sensor clock is accurate to within 1 minute."],
        information_gaps=["No confirmed identity for the second asset."],
    )
    assert assessment.assumptions == ["Assumes the sensor clock is accurate to within 1 minute."]
    assert assessment.information_gaps == ["No confirmed identity for the second asset."]


# --- API-level: unauthorized updates ---------------------------------------


def test_viewer_cannot_update_an_assessment(client, seeded_users, tokens, auth_header):
    created = client.post("/api/v1/assessments", json={"title": "T", "question": "Q?"}, headers=auth_header(tokens, "analyst"))
    assert created.status_code == 201
    assessment_id = created.json()["id"]

    forbidden = client.patch(f"/api/v1/assessments/{assessment_id}", json={"title": "Hacked"}, headers=auth_header(tokens, "viewer"))
    assert forbidden.status_code == 403

    allowed = client.get(f"/api/v1/assessments/{assessment_id}", headers=auth_header(tokens, "viewer"))
    assert allowed.status_code == 200
    assert allowed.json()["title"] == "T"


def test_version_history_is_visible_through_the_api(client, seeded_users, tokens, auth_header):
    created = client.post("/api/v1/assessments", json={"title": "T", "question": "Q?"}, headers=auth_header(tokens, "analyst"))
    assessment_id = created.json()["id"]
    client.patch(f"/api/v1/assessments/{assessment_id}", json={"title": "T2"}, headers=auth_header(tokens, "analyst"))

    revisions = client.get(f"/api/v1/assessments/{assessment_id}/revisions", headers=auth_header(tokens, "analyst"))
    assert revisions.status_code == 200
    assert len(revisions.json()) == 1
    assert revisions.json()[0]["snapshot"]["title"] == "T"


def test_get_nonexistent_assessment_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/assessments/does-not-exist", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 404
