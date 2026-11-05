"""The first ingestion pipeline: JSON/CSV upload,
validation, deduplication, and honest partial-failure reporting.

The duplicate-handling tests here specifically guard against a real
regression found during manual testing: two records sharing an
`external_id` within the SAME upload used to raise an unhandled
IntegrityError (a 500) instead of being reported as a duplicate,
because the in-DB duplicate check alone can't see rows added earlier
in the same unflushed batch. See app/services/ingestion_service.py's
`seen_external_ids` set.
"""
from __future__ import annotations

import io


def _upload(client, token_header, source_id, filename, content, content_type):
    return client.post(
        "/api/v1/ingestion/jobs",
        data={"source_id": source_id},
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=token_header,
    )


def test_json_upload_accepts_valid_records(client, seeded_users, tokens, source, auth_header):
    content = b"""
    [
      {"event_type": "perimeter_motion", "title": "Motion event", "observed_at": "2026-01-01T00:00:00Z"}
    ]
    """
    response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload.json", content, "application/json")
    assert response.status_code == 201
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 0
    assert body["status"] == "completed"


def test_csv_upload_accepts_valid_records(client, seeded_users, tokens, source, auth_header):
    content = b"event_type,title,observed_at\nsensor_offline,Sensor dropped,2026-01-01T00:00:00Z\n"
    response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload.csv", content, "text/csv")
    assert response.status_code == 201
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["job_type"] == "csv_upload"


def test_unsupported_file_type_is_rejected_cleanly(client, seeded_users, tokens, source, auth_header):
    response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload.exe", b"not a real upload", "application/octet-stream")
    assert response.status_code == 201  # job created, but marked failed -- never a 500
    body = response.json()
    assert body["status"] == "failed"
    assert "Unsupported file type" in body["error_summary"][0]["error"]


def test_record_missing_required_field_is_rejected_not_fatal(client, seeded_users, tokens, source, auth_header):
    content = b'[{"event_type": "test_event", "title": "Missing observed_at"}]'
    response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload.json", content, "application/json")
    assert response.status_code == 201
    body = response.json()
    assert body["accepted_count"] == 0
    assert body["rejected_count"] == 1
    assert body["status"] == "completed_with_errors"
    assert "observed_at" in body["error_summary"][0]["error"]


def test_record_with_out_of_range_coordinate_is_rejected_not_fatal(client, seeded_users, tokens, source, auth_header):
    content = b"""[
        {"event_type": "bad_coords", "title": "Bad coordinate event",
         "observed_at": "2026-01-01T00:00:00Z", "latitude": 999.0, "longitude": 20.0}
    ]"""
    response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload.json", content, "application/json")
    assert response.status_code == 201
    body = response.json()
    assert body["rejected_count"] == 1
    assert "coordinate out of range" in body["error_summary"][0]["error"]


def test_intra_batch_duplicate_external_id_is_reported_not_a_500(client, seeded_users, tokens, source, auth_header):
    """Regression test for the exact bug found and fixed in this
    layer: a single upload containing the same external_id twice must
    be reported as accepted=1, duplicate=1 -- never a 500."""
    content = b"""[
        {"event_type": "test_event", "title": "First", "observed_at": "2026-01-01T00:00:00Z", "external_id": "dup-1"},
        {"event_type": "test_event", "title": "Second (duplicate)", "observed_at": "2026-01-01T00:00:00Z", "external_id": "dup-1"}
    ]"""
    response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload.json", content, "application/json")
    assert response.status_code == 201
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["duplicate_count"] == 1
    assert body["rejected_count"] == 0
    assert body["status"] == "completed"


def test_cross_batch_duplicate_external_id_is_detected_via_db(client, seeded_users, tokens, source, auth_header):
    """The same external_id uploaded in two SEPARATE requests must be
    caught by the database-level check, not just the in-batch set."""
    first = b'[{"event_type": "test_event", "title": "First", "observed_at": "2026-01-01T00:00:00Z", "external_id": "cross-1"}]'
    second = b'[{"event_type": "test_event", "title": "Resubmitted", "observed_at": "2026-01-01T00:00:00Z", "external_id": "cross-1"}]'

    first_response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload1.json", first, "application/json")
    assert first_response.json()["accepted_count"] == 1

    second_response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload2.json", second, "application/json")
    body = second_response.json()
    assert body["accepted_count"] == 0
    assert body["duplicate_count"] == 1


def test_mixed_batch_reports_each_outcome_independently(client, seeded_users, tokens, source, auth_header):
    """One bad record must never abort the whole job (Rule 5 / Section
    10's partial-failure-honesty requirement)."""
    content = b"""[
        {"event_type": "test_event", "title": "Valid", "observed_at": "2026-01-01T00:00:00Z", "external_id": "mix-1"},
        {"event_type": "test_event", "title": "Missing observed_at"},
        {"event_type": "bad_coords", "title": "Bad coordinate", "observed_at": "2026-01-01T00:00:00Z", "latitude": 999.0, "longitude": 20.0},
        {"event_type": "test_event", "title": "Valid again", "observed_at": "2026-01-01T00:00:00Z", "external_id": "mix-1"}
    ]"""
    response = _upload(client, auth_header(tokens, "analyst"), source.id, "upload.json", content, "application/json")
    assert response.status_code == 201
    body = response.json()
    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 2
    assert body["duplicate_count"] == 1
    assert body["status"] == "completed_with_errors"
    assert len(body["error_summary"]) == 2


def test_ingestion_requires_a_valid_source(client, seeded_users, tokens, auth_header):
    response = _upload(client, auth_header(tokens, "analyst"), "not-a-real-source", "upload.json", b"[]", "application/json")
    assert response.status_code == 404


def test_uploaded_events_are_labeled_user_upload_not_synthetic(client, seeded_users, tokens, source, auth_header, db):
    from app.models.event import Event

    content = b'[{"event_type": "test_event", "title": "Real upload", "observed_at": "2026-01-01T00:00:00Z"}]'
    _upload(client, auth_header(tokens, "analyst"), source.id, "upload.json", content, "application/json")

    event = db.query(Event).filter_by(title="Real upload").first()
    assert event is not None
    assert event.data_origin == "user_upload"


def test_list_ingestion_jobs_is_paginated_and_permission_checked(client, seeded_users, tokens, source, auth_header):
    _upload(client, auth_header(tokens, "analyst"), source.id, "upload.json", b"[]", "application/json")

    response = client.get("/api/v1/ingestion/jobs", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    assert response.json()["total"] == 1
