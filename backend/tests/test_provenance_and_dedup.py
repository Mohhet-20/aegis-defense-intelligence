"""Raw-record provenance and deduplication/idempotency
 tests. Mixes API-level tests (through the real upload
endpoint) with one lower-level test that deliberately exercises the
true race-condition path the DB's unique constraint exists to catch.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from app.models.data_source import DataSource
from app.models.event import Event
from app.models.ingestion_job import IngestionJob
from app.models.raw_record import RawRecord
from app.services import ingestion_service


def _upload(client, header, source_id, content, filename="upload.json"):
    return client.post(
        "/api/v1/ingestion/jobs",
        data={"source_id": source_id},
        files={"file": (filename, io.BytesIO(content), "application/json")},
        headers=header,
    )


# --- provenance -------------------------------------------------------


def test_every_record_gets_a_raw_record_row_even_when_rejected(client, seeded_users, tokens, source, auth_header, db):
    content = b'[{"event_type": "test_event", "title": "Missing observed_at"}]'
    _upload(client, auth_header(tokens, "analyst"), source.id, content)
    rows = db.query(RawRecord).all()
    assert len(rows) == 1
    assert rows[0].validation_status == "invalid"
    assert rows[0].event_id is None  # rejected -- never linked to a fabricated event


def test_accepted_record_links_raw_record_to_its_event(client, seeded_users, tokens, source, auth_header, db):
    content = b'[{"event_type": "test_event", "title": "Linked", "observed_at": "2026-01-01T00:00:00Z", "external_id": "link-1"}]'
    _upload(client, auth_header(tokens, "analyst"), source.id, content)
    raw = db.query(RawRecord).filter_by(external_record_id="link-1").one()
    event = db.query(Event).filter_by(external_id="link-1").one()
    assert raw.event_id == event.id
    assert event.provenance["raw_record_id"] == raw.id
    assert raw.connector_type == "json_file"
    assert raw.content_fingerprint


def test_raw_record_preserves_the_original_payload_unchanged(client, seeded_users, tokens, source, auth_header, db):
    content = b'[{"event_type": "test_event", "title": "Original Title", "observed_at": "2026-01-01T00:00:00Z", "custom_field": "custom_value"}]'
    _upload(client, auth_header(tokens, "analyst"), source.id, content)
    raw = db.query(RawRecord).one()
    assert raw.payload["title"] == "Original Title"
    assert raw.payload["custom_field"] == "custom_value"


def test_duplicate_record_still_gets_a_raw_record_with_an_explanation(client, seeded_users, tokens, source, auth_header, db):
    content = b"""[
        {"event_type": "x", "title": "First", "observed_at": "2026-01-01T00:00:00Z", "external_id": "dup-exp"},
        {"event_type": "x", "title": "Second", "observed_at": "2026-01-01T00:00:00Z", "external_id": "dup-exp"}
    ]"""
    _upload(client, auth_header(tokens, "analyst"), source.id, content)
    rows = db.query(RawRecord).filter_by(external_record_id="dup-exp").all()
    assert len(rows) == 2
    duplicate_rows = [r for r in rows if r.is_duplicate]
    assert len(duplicate_rows) == 1
    assert duplicate_rows[0].duplicate_reason
    assert duplicate_rows[0].duplicate_of_raw_record_id is not None


# --- deduplication / idempotency ---------------------------------------


def test_repeated_identical_upload_is_idempotent(client, seeded_users, tokens, source, auth_header, db):
    content = b'[{"event_type": "test_event", "title": "Repeatable", "observed_at": "2026-01-01T00:00:00Z", "external_id": "rep-1"}]'
    first = _upload(client, auth_header(tokens, "analyst"), source.id, content)
    second = _upload(client, auth_header(tokens, "analyst"), source.id, content)
    assert first.json()["accepted_count"] == 1
    assert second.json()["accepted_count"] == 0
    assert second.json()["duplicate_count"] == 1
    assert db.query(Event).filter_by(external_id="rep-1").count() == 1


def test_overlapping_batch_only_accepts_the_new_record(client, seeded_users, tokens, source, auth_header):
    first = b'[{"event_type": "a", "title": "A", "observed_at": "2026-01-01T00:00:00Z", "external_id": "ov-1"}]'
    overlap = b"""[
        {"event_type": "a", "title": "A again", "observed_at": "2026-01-01T00:00:00Z", "external_id": "ov-1"},
        {"event_type": "b", "title": "B", "observed_at": "2026-01-01T00:00:00Z", "external_id": "ov-2"}
    ]"""
    _upload(client, auth_header(tokens, "analyst"), source.id, first)
    resp = _upload(client, auth_header(tokens, "analyst"), source.id, overlap)
    body = resp.json()
    assert body["accepted_count"] == 1
    assert body["duplicate_count"] == 1


def test_updated_record_with_same_external_id_never_silently_overwrites(client, seeded_users, tokens, source, auth_header, db):
    """A source resending the SAME external_id with DIFFERENT content
    (a corrected/updated report) is still flagged a duplicate, not
    silently merged into the existing event -- Section 11: 'never
    silently replace existing evidence.' Updating existing evidence is
    a deliberate, separate operation this layer does not implement;
    the safe default is to preserve the original and flag the
    resend for analyst attention."""
    original = b'[{"event_type": "x", "title": "Original Report", "observed_at": "2026-01-01T00:00:00Z", "external_id": "upd-1", "severity": "low"}]'
    updated = b'[{"event_type": "x", "title": "CORRECTED Report", "observed_at": "2026-01-01T00:00:00Z", "external_id": "upd-1", "severity": "critical"}]'
    _upload(client, auth_header(tokens, "analyst"), source.id, original)
    resp = _upload(client, auth_header(tokens, "analyst"), source.id, updated)
    assert resp.json()["duplicate_count"] == 1
    assert resp.json()["accepted_count"] == 0
    stored = db.query(Event).filter_by(external_id="upd-1").one()
    assert stored.title == "Original Report"  # untouched
    assert stored.source_severity == "low"  # untouched


def test_concurrent_duplicate_attempt_is_caught_by_the_db_constraint(db, org, monkeypatch):
    """Simulates a genuine race condition: a second request's
    pre-insert existence check runs a split second BEFORE a concurrent
    winner's commit becomes visible, so it also sees "nothing exists
    yet." The DB's uq_events_source_external_id constraint is the
    actual backstop -- this proves it fires, is caught,
    and is reported as an ordinary counted duplicate rather than a
    crashed/poisoned session."""
    from app.connectors.types import ConnectorResult, RawRecord as ConnectorRawRecord

    source = DataSource(organization_id=org.id, name="RaceSource", source_type="manual")
    db.add(source)
    db.flush()

    now = datetime.now(timezone.utc)
    winner = Event(
        organization_id=org.id, source_id=source.id, external_id="race-1", event_type="race",
        title="Winner (committed by a concurrent request)", observed_at=now, ingested_at=now, data_origin="user_upload",
    )
    db.add(winner)
    db.flush()

    # Force the existence check to report "not found," exactly what a
    # true race's losing request would have seen a moment earlier.
    monkeypatch.setattr(ingestion_service, "_event_already_exists", lambda *a, **k: False)

    job = IngestionJob(organization_id=org.id, source_id=source.id, job_type="json_upload", status="running", started_at=now)
    db.add(job)
    db.flush()

    record = {"event_type": "race", "title": "Loser (should not be inserted)", "observed_at": "2026-01-01T00:00:00Z", "external_id": "race-1"}
    connector_result = ConnectorResult(connector_type="json_file", connector_version="1.0", records=[ConnectorRawRecord(payload=record, external_id="race-1")])

    accepted, rejected, skipped, duplicate, errors = ingestion_service._process_batch(
        db, job=job, organization_id=org.id, source_id=source.id,
        connector_result=connector_result, data_origin="user_upload",
        seen_external_ids=set(), seen_raw_record_ids={},
    )

    assert accepted == 0
    assert duplicate == 1
    assert rejected == 0

    # The session must still be perfectly usable afterwards -- the
    # SAVEPOINT rollback must not have poisoned the outer transaction.
    db.commit()
    events = db.query(Event).filter_by(external_id="race-1").all()
    assert len(events) == 1
    assert events[0].title == "Winner (committed by a concurrent request)"
