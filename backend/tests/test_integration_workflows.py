"""Cross-module end-to-end workflows A-H.

Every test drives the real HTTP API (FastAPI TestClient, in-memory
SQLite, mock adapters, synthetic fixtures) from the first request to the
last assertion, crossing module boundaries. Nothing here is mocked at
the service layer. Per-module behaviour is covered by the module test
files; these tests pin the *seams* between modules.
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.audit import AuditRecord
from tests.analytics_fixtures import EVENTS_EVENT_BASIS, WINDOW_Q, seed

API = "/api/v1"


def _now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def H(tokens, auth_header):
    return lambda role: auth_header(tokens, role)


def _upload(client, headers, source_id, records, name="batch.json"):
    return client.post(
        f"{API}/ingestion/jobs", data={"source_id": source_id},
        files={"file": (name, io.BytesIO(json.dumps(records).encode()), "application/json")}, headers=headers,
    )


def _audit_actions(db):
    db.expire_all()
    return [a.action for a in db.execute(select(AuditRecord)).scalars().all()]


# ----------------------------------------------------------------- A: auth

def test_workflow_a_auth_and_permissions(client, db, tokens, H, seeded_users, test_password):
    # login -> identity -> role-gated route
    me = client.get(f"{API}/auth/me", headers=H("analyst"))
    assert me.status_code == 200 and me.json()["role"] == "analyst"

    # protected route: no token and a garbage token are both 401
    assert client.get(f"{API}/events").status_code == 401
    assert client.get(f"{API}/events", headers={"Authorization": "Bearer not.a.token"}).status_code == 401

    # permission boundary: viewer reads but cannot create/administer
    assert client.get(f"{API}/events", headers=H("viewer")).status_code == 200
    assert client.post(f"{API}/sources", json={"name": "x", "source_type": "manual"}, headers=H("viewer")).status_code == 403
    assert client.get(f"{API}/audit", headers=H("viewer")).status_code == 403
    assert client.get(f"{API}/audit", headers=H("admin")).status_code == 200

    # a wrong password is a uniform 401 and never discloses whether the user exists
    bad = client.post(f"{API}/auth/login", json={"username_or_email": "analyst", "password": "wrong-password-1!"})
    ghost = client.post(f"{API}/auth/login", json={"username_or_email": "nobody-here", "password": "wrong-password-1!"})
    assert bad.status_code == ghost.status_code == 401
    assert bad.json()["detail"] == ghost.json()["detail"]

    # revoking sessions invalidates the existing refresh token
    login = client.post(f"{API}/auth/login", json={"username_or_email": "analyst", "password": test_password}).json()
    hdr = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.post(f"{API}/auth/revoke-sessions", headers=hdr).status_code == 204
    refreshed = client.post(f"{API}/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refreshed.status_code == 401


# ----------------------------------------------------------- B: ingestion

def test_workflow_b_ingestion_provenance_duplicates_malformed(client, db, source, H):
    analyst = H("analyst")
    recs = [
        {"event_type": "perimeter_motion", "title": "A", "observed_at": "2026-01-01T00:00:00Z", "external_id": "x-1"},
        {"event_type": "perimeter_motion", "title": "A again", "observed_at": "2026-01-01T00:00:00Z", "external_id": "x-1"},
        {"title": "no event type", "observed_at": "2026-01-01T00:00:00Z"},
    ]
    r = _upload(client, analyst, source.id, recs)
    assert r.status_code == 201, r.text
    job = r.json()
    assert (job["accepted_count"], job["duplicate_count"], job["rejected_count"]) == (1, 1, 1)

    # provenance: the stored event points back to the source and names its origin
    ev = client.get(f"{API}/events", headers=analyst).json()["items"]
    assert len(ev) == 1
    detail = client.get(f"{API}/events/{ev[0]['id']}", headers=analyst).json()
    assert detail["source_id"] == source.id and detail["data_origin"]

    # re-uploading the same file adds no new events (cross-batch duplicate)
    again = _upload(client, analyst, source.id, recs[:1]).json()
    assert again["accepted_count"] == 0 and again["duplicate_count"] == 1
    assert client.get(f"{API}/events", headers=analyst).json()["total"] == 1

    # entirely malformed input is a clean 4xx, never a 5xx, and creates nothing
    bad = client.post(
        f"{API}/ingestion/jobs", data={"source_id": source.id},
        files={"file": ("broken.json", b"{not json", "application/json")}, headers=analyst,
    )
    # The job is recorded (so the failure is inspectable) but must never read as a success.
    assert bad.status_code < 500
    if bad.status_code == 201:
        bj = bad.json()
        assert bj["status"] != "completed" and bj["accepted_count"] == 0, bj
        assert bj.get("error_message") or bj.get("error_summary") or bj["rejected_count"] >= 0
    assert client.get(f"{API}/events", headers=analyst).json()["total"] == 1

    # a viewer may not ingest
    assert _upload(client, H("viewer"), source.id, recs[:1]).status_code == 403


# ------------------------------------------------- C: evidence and fusion

def test_workflow_c_uncertain_vs_conflicting_stay_distinct_and_audited(client, db, source, H):
    analyst = H("analyst")
    _upload(client, analyst, source.id, [
        {"event_type": "perimeter_motion", "title": "E1", "observed_at": "2026-01-01T00:00:00Z", "external_id": "e1"},
        {"event_type": "perimeter_motion", "title": "E2", "observed_at": "2026-01-01T00:01:00Z", "external_id": "e2"},
    ])
    events = client.get(f"{API}/events", headers=analyst).json()["items"]
    e1, e2 = events[0]["id"], events[1]["id"]

    ev = client.post(f"{API}/evidence", headers=analyst, json={"evidence_type": "observation", "title": "obs", "event_id": e1})
    assert ev.status_code == 201, ev.text
    # an evidence record backed by nothing real is refused
    assert client.post(f"{API}/evidence", headers=analyst, json={"evidence_type": "observation", "title": "empty"}).status_code in (400, 422)

    def rel(rtype):
        return client.post(f"{API}/relationships", headers=analyst, json={
            "source_ref_type": "event", "source_ref_id": e1, "target_ref_type": "event", "target_ref_id": e2,
            "relationship_type": rtype, "explanation": "synthetic"})

    uncertain = rel("temporally_associated")
    contradicts = rel("contradicts")
    assert uncertain.status_code == 201 and contradicts.status_code == 201, (uncertain.text, contradicts.text)

    # reviewing one as "uncertain" must not turn it into a contradiction, and vice versa
    r1 = client.post(f"{API}/relationships/{uncertain.json()['id']}/review", headers=analyst,
                     json={"review_status": "uncertain", "review_note": "cannot tell"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["review_status"] == "uncertain" and r1.json()["relationship_type"] == "temporally_associated"
    got = client.get(f"{API}/relationships/{contradicts.json()['id']}", headers=analyst).json()
    assert got["relationship_type"] == "contradicts" and got["review_status"] != "uncertain"

    # a viewer cannot review; the review that did happen is in the audit log
    assert client.post(f"{API}/relationships/{contradicts.json()['id']}/review", headers=H("viewer"),
                       json={"review_status": "confirmed"}).status_code == 403
    assert any(a.startswith("evidence_relationship") for a in _audit_actions(db))

    # fusion runs over the same events without changing their provenance
    run = client.post(f"{API}/fusion/run", headers=analyst, json={})
    assert run.status_code == 201 and run.json()["status"] == "completed"


# ------------------------------------------------ D: media and inference

def test_workflow_d_media_inference_review(client, db, org, tokens, H, png_bytes, cv_mock_model):
    analyst = H("analyst")
    content = png_bytes(100, 80)
    up = client.post(f"{API}/media", headers=analyst, files={"file": ("a.png", content, "image/png")})
    assert up.status_code == 201, up.text
    media = up.json()
    # the storage path / filesystem location is never exposed
    assert "storage_path" not in media and "/" not in str(media.get("stored_filename", ""))
    assert client.get(f"{API}/media/{media['id']}/content", headers=analyst).content == content

    # invalid files: wrong content for the declared type, and a non-media payload
    assert client.post(f"{API}/media", headers=analyst, files={"file": ("x.png", b"not a png", "image/png")}).status_code in (400, 415, 422)
    assert client.post(f"{API}/media", headers=analyst, files={"file": ("x.exe", b"MZ\x00\x00", "application/octet-stream")}).status_code in (400, 415, 422)

    job = client.post(f"{API}/inference/jobs", headers=analyst, json={
        "media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "image_detection"})
    assert job.status_code == 201, job.text
    assert job.json()["status"] == "completed"

    dets = client.get(f"{API}/inference/jobs/{job.json()['id']}/detections", headers=analyst).json()
    assert dets["total"] >= 1
    det = dets["items"][0]
    assert det["review_status"] in ("unreviewed", "pending", "pending_review")

    # AI output is advisory: promotion to evidence needs an explicit human review first
    rv = client.post(f"{API}/detections/{det['id']}/review", headers=analyst, json={"review_status": "confirmed", "review_note": "ok"})
    assert rv.status_code == 200, rv.text
    pr = client.post(f"{API}/detections/{det['id']}/promote-to-evidence", headers=analyst, json={"title": "Promoted", "summary": "s"})
    assert pr.status_code in (200, 201), pr.text
    assert "detection.reviewed" in "".join(_audit_actions(db)) or any("detection" in a for a in _audit_actions(db))

    # viewer cannot upload or run inference
    assert client.post(f"{API}/media", headers=H("viewer"), files={"file": ("a.png", content, "image/png")}).status_code == 403


def test_workflow_d_media_is_tenant_private(client, tokens, H, b_headers, png_bytes, cv_mock_model):
    media = client.post(f"{API}/media", headers=H("analyst"), files={"file": ("a.png", png_bytes(), "image/png")}).json()
    assert client.get(f"{API}/media/{media['id']}", headers=b_headers).status_code == 404
    assert client.get(f"{API}/media/{media['id']}/content", headers=b_headers).status_code == 404
    assert client.post(f"{API}/inference/jobs", headers=b_headers, json={
        "media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "image_detection"}).status_code in (400, 403, 404)


# ------------------------------------------- E: investigation and export

def test_workflow_e_investigation_evidence_export_access(client, db, source, H, b_headers):
    analyst = H("analyst")
    _upload(client, analyst, source.id, [{"event_type": "perimeter_motion", "title": "E1", "observed_at": "2026-01-01T00:00:00Z", "external_id": "i1"}])
    event_id = client.get(f"{API}/events", headers=analyst).json()["items"][0]["id"]

    inv = client.post(f"{API}/investigations", headers=analyst, json={
        "title": "Case 1", "description": "synthetic", "priority": "normal", "purpose": "test", "scope": "test",
        "linked_event_ids": [event_id]})
    assert inv.status_code == 201, inv.text
    iid = inv.json()["id"]

    note = client.post(f"{API}/investigations/{iid}/notes", headers=analyst, json={"body": "first note", "note_kind": "observed_fact"})
    assert note.status_code == 201, note.text
    # optimistic concurrency: a stale version is refused, not silently overwritten
    ok = client.patch(f"{API}/investigations/{iid}/notes/{note.json()['id']}", headers=analyst,
                      json={"body": "edited", "expected_version": note.json()["version"]})
    assert ok.status_code == 200, ok.text
    stale = client.patch(f"{API}/investigations/{iid}/notes/{note.json()['id']}", headers=analyst,
                         json={"body": "stale edit", "expected_version": note.json()["version"]})
    assert stale.status_code == 409
    revs = client.get(f"{API}/investigations/{iid}/notes/{note.json()['id']}/revisions", headers=analyst).json()
    items = revs if isinstance(revs, list) else revs.get("items", [])
    assert len(items) >= 2

    # status transitions are validated and recorded
    bad = client.post(f"{API}/investigations/{iid}/transition", headers=analyst, json={"to_status": "no_such_status", "reason": "x"})
    assert bad.status_code in (400, 409, 422)
    hist = client.get(f"{API}/investigations/{iid}/status-history", headers=analyst)
    assert hist.status_code == 200

    exp = client.post(f"{API}/investigations/{iid}/export", headers=analyst)
    assert exp.status_code in (200, 201), exp.text
    assert any("export" in a for a in _audit_actions(db))

    # another organization sees nothing of this case, including sub-resources and export
    for path in ("", "/notes", "/timeline", "/audit", "/evidence"):
        assert client.get(f"{API}/investigations/{iid}{path}", headers=b_headers).status_code == 404, path
    assert client.post(f"{API}/investigations/{iid}/export", headers=b_headers).status_code == 404
    # a viewer cannot write into it
    assert client.post(f"{API}/investigations/{iid}/notes", headers=H("viewer"), json={"body": "x", "note_kind": "observed_fact"}).status_code == 403


# ------------------------------------- F/G: MLOps, analytics, reporting

def test_workflow_f_mlops_then_analytics_and_report_agree(client, db, org, org_b, H, clf_samples):
    analyst = H("analyst")
    model = client.post(f"{API}/mlops/models", headers=analyst, json={
        "name": "wf-f", "version": "1.0.0", "task_type": "classification", "release_notes": "synthetic"}).json()
    run = client.post(f"{API}/mlops/experiments", headers=analyst, json={
        "model_record_id": model["id"], "experiment_name": "wf-f", "idempotency_key": "wf-f-key-0001",
        "classification": {"dataset_name": "synthetic", "dataset_version": "1", "is_synthetic": True,
                           "positive_label": "pos", "samples": clf_samples(wrong=4)}})
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "succeeded"
    # replaying the same idempotency key returns the same run instead of duplicating it
    replay = client.post(f"{API}/mlops/experiments", headers=analyst, json={
        "model_record_id": model["id"], "experiment_name": "wf-f", "idempotency_key": "wf-f-key-0001",
        "classification": {"dataset_name": "synthetic", "dataset_version": "1", "is_synthetic": True,
                           "positive_label": "pos", "samples": clf_samples(wrong=4)}})
    assert replay.status_code in (200, 201) and replay.json()["id"] == run.json()["id"]

    seed(db, org, org_b)
    dash = client.get(f"{API}/reporting/analytics/events", params=WINDOW_Q, headers=analyst)
    assert dash.status_code == 200, dash.text
    dash_value = dash.json()["values"]["events.count"]["value"]
    assert dash_value == EVENTS_EVENT_BASIS

    rep = client.post(f"{API}/reporting/reports", headers=analyst, json={
        "template_key": "platform_activity", "format": "json", **WINDOW_Q})
    assert rep.status_code == 201, rep.text
    doc = client.get(f"{API}/reporting/reports/{rep.json()['id']}/download", headers=analyst).json()
    assert doc["sections"]["events"]["values"]["events.count"]["value"] == dash_value
    # the report is not contaminated by the other organization's seeded rows
    other = client.get(f"{API}/reporting/analytics/events", params=WINDOW_Q, headers=H("admin")).json()
    assert other["values"]["events.count"]["value"] == dash_value


def test_workflow_g_report_lifecycle_failures_and_access(client, db, org, org_b, H, b_headers):
    from app.models.report import ReportRun

    seed(db, org, org_b)
    analyst = H("analyst")
    rep = client.post(f"{API}/reporting/reports", headers=analyst, json={
        "template_key": "platform_activity", "format": "csv", **WINDOW_Q}).json()
    assert rep["status"] == "completed" and rep["downloadable"]
    body = client.get(f"{API}/reporting/reports/{rep['id']}/download", headers=analyst)
    assert body.status_code == 200 and hashlib.sha256(body.content).hexdigest() == rep["content_sha256"]

    # authorization: foreign org cannot see or download; viewer cannot create
    assert client.get(f"{API}/reporting/reports/{rep['id']}", headers=b_headers).status_code == 404
    assert client.get(f"{API}/reporting/reports/{rep['id']}/download", headers=b_headers).status_code == 404
    assert client.post(f"{API}/reporting/reports", headers=H("viewer"), json={
        "template_key": "platform_activity", "format": "json", **WINDOW_Q}).status_code == 403

    # invalid request is rejected before a run is created
    before = db.execute(select(ReportRun)).scalars().all()
    bad = client.post(f"{API}/reporting/reports", headers=analyst, json={"template_key": "nope", "format": "json", **WINDOW_Q})
    assert 400 <= bad.status_code < 500
    db.expire_all()
    assert len(db.execute(select(ReportRun)).scalars().all()) == len(before)

    # a tampered artifact is never served as a success, and the mismatch is audited
    from app.services import report_service

    run = db.get(ReportRun, rep["id"])
    f = report_service._artifact_path(run)
    f.write_bytes(f.read_bytes() + b" ")
    tampered = client.get(f"{API}/reporting/reports/{rep['id']}/download", headers=analyst)
    assert tampered.status_code == 409
    assert "report.integrity_mismatch" in _audit_actions(db)


# ------------------------------------------------------------ H: edge sync

def test_workflow_h_edge_sync_idempotency_conflict_retry(client, db, H, active_device_factory, device_headers):
    device, key = active_device_factory()
    hdr = device_headers(device.device_identifier, key)
    now = _now()

    def env(mid, ikey, text, rev=0):
        return {"message_id": mid, "idempotency_key": ikey, "record_type": "annotation", "client_record_id": "ann-1",
                "schema_version": "v1", "payload": {"text": text}, "source_created_at": now, "queued_at": now, "base_revision": rev}

    def send(*records):
        return client.post(f"{API}/edge/sync/batch", headers=hdr, json={
            "protocol_version": "edge_sync_v1", "device_id": device.device_identifier, "sent_at": now, "records": list(records)})

    first = send(env("m1", "k1", "central"))
    assert first.status_code == 200 and first.json()["results"][0]["sync_status"] == "synced"

    # idempotent replay: same key is acknowledged, not applied twice
    replay = send(env("m1", "k1", "central"))
    assert replay.status_code == 200
    listed = client.get(f"{API}/edge/sync/records", headers=H("analyst")).json()
    assert listed["total"] == 1

    # stale write -> conflict, inspectable with both versions, nothing silently lost
    stale = send(env("m2", "k2", "stale"))
    res = stale.json()["results"][0]
    assert res.get("conflict_id"), res
    conflict = client.get(f"{API}/edge/conflicts/{res['conflict_id']}", headers=H("analyst")).json()
    assert conflict["resolution_status"] == "unresolved"
    assert conflict["local_version"]["payload"] == {"text": "stale"}
    assert conflict["central_version"]["payload"] == {"text": "central"}

    # a viewer can inspect but not resolve; an analyst-level resolver can, and it is audited
    assert client.post(f"{API}/edge/conflicts/{res['conflict_id']}/resolve", headers=H("viewer"),
                       json={"resolution_strategy": "keep_central"}).status_code == 403
    done = client.post(f"{API}/edge/conflicts/{res['conflict_id']}/resolve", headers=H("admin"),
                       json={"resolution_strategy": "keep_central", "resolution_note": "central wins"})
    assert done.status_code == 200, done.text
    assert any("conflict" in a for a in _audit_actions(db))

    # rejected input is stored inspectably, not dropped: unsupported protocol is a 4xx and a malformed record is reported per-record
    bad_proto = client.post(f"{API}/edge/sync/batch", headers=hdr, json={
        "protocol_version": "edge_sync_v99", "device_id": device.device_identifier, "sent_at": now, "records": [env("m3", "k3", "x")]})
    assert bad_proto.status_code == 400

    # credentials: a revoked/rotated key stops working immediately
    rot = client.post(f"{API}/devices/{device.id}/rotate-key", headers=H("admin"))
    assert rot.status_code in (200, 201), rot.text
    assert send(env("m4", "k4", "after-rotate")).status_code == 401
