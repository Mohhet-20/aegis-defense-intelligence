"""Evidence CRUD (Section 3B) and EvidenceRelationship CRUD +
review workflow (Sections 3D, 11). Section 17 requires: valid
relationship creation, invalid references, self-link behavior,
duplicate submission, relationship provenance, analyst review
permissions, and reversal/supersession.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.data_source import DataSource
from app.models.event import Event
from app.services import evidence_service, relationship_service
from app.services.relationship_service import InvalidReferenceError

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


# --- Evidence --------------------------------------------------------------


def test_evidence_backed_by_an_event_requires_event_id(db, org):
    with pytest.raises(ValueError):
        evidence_service.create_evidence(db, organization_id=org.id, evidence_type="observation", title="An observation")


def test_evidence_with_no_real_reference_is_rejected(db, org):
    with pytest.raises(ValueError):
        evidence_service.create_evidence(db, organization_id=org.id, evidence_type="analyst_note", title="Empty note")


def test_analyst_note_requires_content(db, org):
    with pytest.raises(ValueError):
        evidence_service.create_evidence(db, organization_id=org.id, evidence_type="analyst_note", title="Note", content=None)
    evidence = evidence_service.create_evidence(db, organization_id=org.id, evidence_type="analyst_note", title="Note", content="Observed via radio chatter.")
    assert evidence.id


def test_evidence_backed_by_event_id_is_created(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    event = _event(db, org, source)
    db.commit()
    evidence = evidence_service.create_evidence(db, organization_id=org.id, evidence_type="observation", title="Linked observation", event_id=event.id)
    assert evidence.event_id == event.id


def test_only_free_text_fields_can_be_updated(db, org):
    note = evidence_service.create_evidence(db, organization_id=org.id, evidence_type="report", title="Report", content="Initial text.")
    updated = evidence_service.update_evidence_content(db, note, content="Revised text.")
    assert updated.content == "Revised text."

    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    event = _event(db, org, source)
    db.commit()
    observation_evidence = evidence_service.create_evidence(db, organization_id=org.id, evidence_type="observation", title="Linked", event_id=event.id)
    with pytest.raises(ValueError):
        evidence_service.update_evidence_content(db, observation_evidence, content="Should be refused")


# --- EvidenceRelationship ---------------------------------------------------


def test_valid_relationship_creation_between_two_events(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    b = _event(db, org, source, title="B")
    db.commit()

    relationship, created = relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
        relationship_type="derived_from", origin="analyst_created", explanation="B was written up from A's report.", created_by_user_id="user-1",
    )
    assert created is True
    assert relationship.source_event_id == a.id
    assert relationship.target_event_id == b.id
    assert relationship.review_status == "candidate"


def test_relationship_to_a_nonexistent_record_is_rejected(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    db.commit()

    with pytest.raises(InvalidReferenceError):
        relationship_service.create_relationship(
            db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id="does-not-exist",
            relationship_type="supports", origin="analyst_created", explanation="x", created_by_user_id="user-1",
        )


def test_self_link_is_rejected(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    db.commit()

    with pytest.raises(ValueError):
        relationship_service.create_relationship(
            db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=a.id,
            relationship_type="supports", origin="analyst_created", explanation="x", created_by_user_id="user-1",
        )


def test_duplicate_relationship_submission_is_idempotent(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    b = _event(db, org, source, title="B")
    db.commit()

    first, created_first = relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
        relationship_type="supports", origin="analyst_created", explanation="x", created_by_user_id="user-1",
    )
    second, created_second = relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
        relationship_type="supports", origin="analyst_created", explanation="a different explanation string", created_by_user_id="user-2",
    )
    assert created_first is True
    assert created_second is False
    assert first.id == second.id


def test_relationship_between_an_event_and_an_evidence_item(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    db.commit()
    note = evidence_service.create_evidence(db, organization_id=org.id, evidence_type="analyst_note", title="Note", content="text")

    relationship, created = relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="evidence", source_ref_id=note.id, target_ref_type="event", target_ref_id=a.id,
        relationship_type="contradicts", origin="analyst_created", explanation="This note disputes event A.", created_by_user_id="user-1",
    )
    assert created is True
    assert relationship.source_evidence_id == note.id
    assert relationship.target_event_id == a.id


def test_rule_based_relationship_requires_no_human_author(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    b = _event(db, org, source, title="B")
    db.commit()

    relationship, _ = relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
        relationship_type="duplicate_candidate", origin="rule_based", explanation="shared_source_id + temporal_proximity",
    )
    assert relationship.created_by_user_id is None


def test_analyst_created_relationship_without_an_author_is_rejected(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    b = _event(db, org, source, title="B")
    db.commit()

    with pytest.raises(ValueError):
        relationship_service.create_relationship(
            db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
            relationship_type="supports", origin="analyst_created", explanation="x", created_by_user_id=None,
        )


def test_review_confirm_reject_and_reverse_workflow(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    b = _event(db, org, source, title="B")
    db.commit()
    relationship, _ = relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
        relationship_type="supports", origin="analyst_created", explanation="x", created_by_user_id="user-1",
    )

    with pytest.raises(ValueError):
        relationship_service.reverse_relationship(db, relationship, actor_user_id="user-2")  # never reviewed yet

    confirmed = relationship_service.review_relationship(db, relationship, review_status="confirmed", reviewed_by_user_id="user-2", review_note="Looks right.")
    assert confirmed.review_status == "confirmed"
    assert confirmed.reviewed_by_user_id == "user-2"

    reversed_rel = relationship_service.reverse_relationship(db, confirmed, actor_user_id="user-3", note="Actually, this was wrong.")
    assert reversed_rel.review_status == "candidate"
    assert reversed_rel.is_reversed is True
    assert reversed_rel.last_reversed_at is not None

    history = relationship_service.get_review_history(db, org.id, relationship.id)
    assert [h.action for h in history] == ["evidence_relationship.review", "evidence_relationship.reverse"]
    assert history[0].context_metadata["new_status"] == "confirmed"
    assert history[1].context_metadata["prior_status"] == "confirmed"


def test_review_cannot_be_set_back_to_candidate_directly(db, org):
    source = DataSource(organization_id=org.id, name="S", source_type="manual")
    db.add(source)
    db.flush()
    a = _event(db, org, source, title="A")
    b = _event(db, org, source, title="B")
    db.commit()
    relationship, _ = relationship_service.create_relationship(
        db, organization_id=org.id, source_ref_type="event", source_ref_id=a.id, target_ref_type="event", target_ref_id=b.id,
        relationship_type="supports", origin="analyst_created", explanation="x", created_by_user_id="user-1",
    )
    with pytest.raises(ValueError):
        relationship_service.review_relationship(db, relationship, review_status="candidate", reviewed_by_user_id="user-2")


# --- API-level: permissions ------------------------------------------------


def test_viewer_cannot_create_a_relationship_but_can_read_one(client, seeded_users, tokens, source, auth_header):
    content = b'[{"event_type": "a", "title": "A", "observed_at": "2026-01-01T00:00:00Z"}, {"event_type":"a","title":"B","observed_at":"2026-01-01T00:00:00Z"}]'
    upload = client.post("/api/v1/ingestion/jobs", data={"source_id": source.id}, files={"file": ("f.json", content, "application/json")}, headers=auth_header(tokens, "analyst"))
    assert upload.status_code == 201
    events = client.get("/api/v1/events", headers=auth_header(tokens, "viewer")).json()["items"]
    a_id, b_id = events[0]["id"], events[1]["id"]

    forbidden = client.post(
        "/api/v1/relationships",
        json={"source_ref_type": "event", "source_ref_id": a_id, "target_ref_type": "event", "target_ref_id": b_id, "relationship_type": "supports", "explanation": "x"},
        headers=auth_header(tokens, "viewer"),
    )
    assert forbidden.status_code == 403

    created = client.post(
        "/api/v1/relationships",
        json={"source_ref_type": "event", "source_ref_id": a_id, "target_ref_type": "event", "target_ref_id": b_id, "relationship_type": "supports", "explanation": "x"},
        headers=auth_header(tokens, "analyst"),
    )
    assert created.status_code == 201
    relationship_id = created.json()["id"]

    readable = client.get(f"/api/v1/relationships/{relationship_id}", headers=auth_header(tokens, "viewer"))
    assert readable.status_code == 200

    viewer_review = client.post(f"/api/v1/relationships/{relationship_id}/review", json={"review_status": "confirmed"}, headers=auth_header(tokens, "viewer"))
    assert viewer_review.status_code == 403


def test_get_nonexistent_relationship_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/relationships/does-not-exist", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 404
