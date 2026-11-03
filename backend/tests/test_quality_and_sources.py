"""Data-quality summaries and the extended source
registry / connector-driven source operations.
"""
from __future__ import annotations

import io

from app.models.data_source import DataSource
from app.services import quality_service as qs


def _upload(client, header, source_id, content, filename="upload.json"):
    return client.post(
        "/api/v1/ingestion/jobs",
        data={"source_id": source_id},
        files={"file": (filename, io.BytesIO(content), "application/json")},
        headers=header,
    )


# --- quality summaries ----------------------------------------------------


def test_quality_summary_is_empty_and_labeled_when_no_records_exist(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/data-quality/summary", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["acceptance_rate"] is None  # never a fabricated 0% on an empty denominator


def test_quality_summary_states_its_own_denominator(client, seeded_users, tokens, source, auth_header):
    content = b"""[
        {"event_type": "a", "title": "Valid", "observed_at": "2026-01-01T00:00:00Z", "external_id": "q-1"},
        {"event_type": "b", "title": "Invalid"}
    ]"""
    _upload(client, auth_header(tokens, "analyst"), source.id, content)
    response = client.get("/api/v1/data-quality/summary", headers=auth_header(tokens, "analyst"))
    body = response.json()
    assert body["total"] == 2
    assert body["valid"] == 1
    assert body["invalid"] == 1
    assert body["rejection_categories"].get("missing_required_field") == 1


def test_quality_summary_can_be_scoped_to_one_source(client, seeded_users, tokens, source, auth_header, db, org):
    other_source = DataSource(organization_id=org.id, name="Other", source_type="manual")
    db.add(other_source)
    db.commit()

    _upload(client, auth_header(tokens, "analyst"), source.id, b'[{"event_type": "a", "title": "A", "observed_at": "2026-01-01T00:00:00Z", "external_id": "x1"}]')
    _upload(client, auth_header(tokens, "analyst"), other_source.id, b'[{"event_type": "a", "title": "A", "observed_at": "2026-01-01T00:00:00Z", "external_id": "x2"}]')

    response = client.get(f"/api/v1/data-quality/summary?source_id={source.id}", headers=auth_header(tokens, "analyst"))
    assert response.json()["total"] == 1


def test_jobs_summary_counts_by_status(client, seeded_users, tokens, source, auth_header):
    _upload(client, auth_header(tokens, "analyst"), source.id, b'[{"event_type": "a", "title": "A", "observed_at": "2026-01-01T00:00:00Z"}]')
    _upload(client, auth_header(tokens, "analyst"), source.id, b"not json at all")
    response = client.get("/api/v1/data-quality/jobs-summary", headers=auth_header(tokens, "analyst"))
    body = response.json()
    assert body["total_jobs"] == 2
    assert body["by_status"].get("completed") == 1
    assert body["by_status"].get("failed") == 1


# --- source registry operations --------------------------------------------


def test_create_source_defaults_to_enabled_file_upload(client, seeded_users, tokens, auth_header):
    response = client.post("/api/v1/sources", json={"name": "New Source", "source_type": "manual"}, headers=auth_header(tokens, "analyst"))
    assert response.status_code == 201
    body = response.json()
    assert body["enabled"] is True
    assert body["connection_mode"] == "file_upload"
    assert body["config_revision"] == 1


def test_disabling_a_source_blocks_new_uploads(client, seeded_users, tokens, source, auth_header):
    client.post(f"/api/v1/sources/{source.id}/disable", headers=auth_header(tokens, "analyst"))
    response = _upload(client, auth_header(tokens, "analyst"), source.id, b'[{"event_type": "a", "title": "A", "observed_at": "2026-01-01T00:00:00Z"}]')
    assert response.status_code == 409


def test_enabling_a_disabled_source_restores_uploads(client, seeded_users, tokens, source, auth_header):
    client.post(f"/api/v1/sources/{source.id}/disable", headers=auth_header(tokens, "analyst"))
    client.post(f"/api/v1/sources/{source.id}/enable", headers=auth_header(tokens, "analyst"))
    response = _upload(client, auth_header(tokens, "analyst"), source.id, b'[{"event_type": "a", "title": "A", "observed_at": "2026-01-01T00:00:00Z"}]')
    assert response.status_code == 201
    assert response.json()["status"] != "failed"


def test_config_metadata_update_bumps_config_revision(client, seeded_users, tokens, source, auth_header):
    response = client.patch(f"/api/v1/sources/{source.id}", json={"config_metadata": {"count": 5}}, headers=auth_header(tokens, "analyst"))
    assert response.json()["config_revision"] == 2


def test_reliability_weight_change_requires_a_reason(client, seeded_users, tokens, source, auth_header):
    response = client.put(f"/api/v1/sources/{source.id}/reliability", json={"weight": 0.5, "reason": ""}, headers=auth_header(tokens, "analyst"))
    assert response.status_code in (400, 422)


def test_reliability_weight_change_with_a_reason_succeeds_and_is_audited(client, seeded_users, tokens, source, auth_header, db):
    from app.models.audit import AuditRecord

    response = client.put(
        f"/api/v1/sources/{source.id}/reliability", json={"weight": 0.3, "reason": "repeated false positives this month"}, headers=auth_header(tokens, "analyst")
    )
    assert response.status_code == 200
    assert response.json()["reliability_weight"] == 0.3
    audit = db.query(AuditRecord).filter_by(action="source.reliability_change").one()
    assert audit.context_metadata["reason"] == "repeated false positives this month"


def test_a_file_upload_only_source_cannot_be_run(client, seeded_users, tokens, auth_header):
    """"manual" has no connector-driven fetch() path -- it only ever
    receives an uploaded file via POST /ingestion/jobs."""
    create = client.post("/api/v1/sources", json={"name": "Manual Only", "source_type": "manual"}, headers=auth_header(tokens, "analyst"))
    source_id = create.json()["id"]
    response = client.post(f"/api/v1/sources/{source_id}/run", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 400


def test_a_connector_driven_source_can_be_run_and_produces_events(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/sources",
        json={"name": "Synthetic Runnable", "source_type": "synthetic_demo", "connection_mode": "polling", "config_metadata": {"count": 3, "seed": 99}},
        headers=auth_header(tokens, "analyst"),
    )
    source_id = create.json()["id"]
    response = client.post(f"/api/v1/sources/{source_id}/run", headers=auth_header(tokens, "analyst"))
    assert response.status_code == 201
    assert response.json()["accepted_count"] == 3
    assert response.json()["job_type"] == "synthetic_demo"
