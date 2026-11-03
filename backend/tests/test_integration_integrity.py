"""Phase 17 Phase 4: cross-module data integrity.

Populates several modules through the real API, then checks the stored
rows generically against the schema metadata, so a new table with a
tenant column is covered without editing this file:
  * no dangling foreign keys;
  * every FK from a tenant-scoped row to another tenant-scoped table points
    at a row of the SAME organization (no cross-tenant references);
  * audit rows reference an existing organization/user.
"""
from __future__ import annotations

import io
import json

from sqlalchemy import text

from app.db.base import Base
from tests.analytics_fixtures import seed

API = "/api/v1"


def _ok(resp):
    assert resp.status_code < 300, (resp.request.url, resp.status_code, resp.text[:200])
    return resp


def _populate(client, db, org, org_b, source, tokens, auth_header, png_bytes, cv_mock_model, active_device_factory, device_headers, with_seed=True):
    from datetime import datetime, timezone

    analyst = auth_header(tokens, "analyst")
    recs = [{"event_type": "perimeter_motion", "title": f"E{i}", "observed_at": "2026-01-01T00:0%d:00Z" % i, "external_id": f"i{i}"} for i in range(3)]
    _ok(client.post(f"{API}/ingestion/jobs", data={"source_id": source.id}, headers=analyst,
                files={"file": ("a.json", io.BytesIO(json.dumps(recs).encode()), "application/json")}))
    events = client.get(f"{API}/events", headers=analyst).json()["items"]
    ev = client.post(f"{API}/evidence", headers=analyst, json={"evidence_type": "observation", "title": "o", "event_id": events[0]["id"]}).json()
    _ok(client.post(f"{API}/relationships", headers=analyst, json={
        "source_ref_type": "event", "source_ref_id": events[0]["id"], "target_ref_type": "event", "target_ref_id": events[1]["id"],
        "relationship_type": "analyst_linked", "explanation": "x"}))
    _ok(client.post(f"{API}/investigations", headers=analyst, json={
        "title": "c", "priority": "normal", "purpose": "t", "scope": "t", "linked_event_ids": [events[0]["id"]]}))
    media = client.post(f"{API}/media", headers=analyst, files={"file": ("a.png", png_bytes(), "image/png")}).json()
    _ok(client.post(f"{API}/inference/jobs", headers=analyst, json={"media_asset_id": media["id"], "model_record_id": cv_mock_model.id, "job_type": "image_detection"}))
    rep = client.post(f"{API}/reporting/reports", headers=analyst, json={"template_key": "platform_activity", "format": "json",
                      "start": "2026-01-01T00:00:00Z", "end": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    assert rep.status_code == 201 and rep.json()["status"] == "completed", rep.text
    device, key = active_device_factory()
    now = datetime.now(timezone.utc).isoformat()
    _ok(client.post(f"{API}/edge/sync/batch", headers=device_headers(device.device_identifier, key), json={
        "protocol_version": "edge_sync_v1", "device_id": device.device_identifier, "sent_at": now, "records": [{
            "message_id": "m1", "idempotency_key": "k1", "record_type": "observation_capture", "client_record_id": "c1",
            "schema_version": "v1", "payload": {"x": 1}, "source_created_at": now, "queued_at": now}]}))
    # Analytics fixture rows are inserted last: they deliberately include an
    # out-of-range latitude (see KNOWN_RISKS: a stored invalid coordinate makes
    # GET /events fail response validation), so they must not precede API reads.
    if with_seed:
        seed(db, org, org_b)
    return ev


def test_no_dangling_foreign_keys_and_no_cross_tenant_references(
    client, db, org, org_b, source, tokens, auth_header, png_bytes, cv_mock_model, active_device_factory, device_headers,
):
    _populate(client, db, org, org_b, source, tokens, auth_header, png_bytes, cv_mock_model, active_device_factory, device_headers)
    db.expire_all()

    # 1. SQLite's own check: every FK value resolves.
    # (PostgreSQL enforces foreign keys at write time, so there is nothing to check after the fact.)
    if db.get_bind().dialect.name == "sqlite":
        dangling = db.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert dangling == [], f"dangling foreign keys: {dangling[:5]}"

    # 2. Tenant consistency, derived from metadata.
    tables = Base.metadata.tables
    checked = 0
    violations = []
    for table in tables.values():
        if "organization_id" not in table.c:
            continue
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent is table or fk.parent.name == "organization_id" or "organization_id" not in parent.c:
                continue
            q = text(
                f"SELECT COUNT(*) FROM {table.name} c JOIN {parent.name} p ON c.{fk.parent.name} = p.{fk.column.name} "
                f"WHERE c.organization_id IS NOT NULL AND p.organization_id IS NOT NULL AND c.organization_id <> p.organization_id"
            )
            n = db.execute(q).scalar()
            checked += 1
            if n:
                violations.append((table.name, fk.parent.name, parent.name, n))
    assert checked > 20, "tenant-reference check ran against suspiciously few foreign keys"
    assert violations == [], f"cross-tenant references: {violations}"


def test_audit_rows_reference_real_organizations_and_users(
    client, db, org, org_b, source, tokens, auth_header, png_bytes, cv_mock_model, active_device_factory, device_headers,
):
    _populate(client, db, org, org_b, source, tokens, auth_header, png_bytes, cv_mock_model, active_device_factory, device_headers)
    db.expire_all()
    total = db.execute(text("SELECT COUNT(*) FROM audit_records")).scalar()
    assert total > 5
    orphan_org = db.execute(text(
        "SELECT COUNT(*) FROM audit_records a WHERE a.organization_id IS NOT NULL AND a.organization_id NOT IN (SELECT id FROM organizations)")).scalar()
    orphan_user = db.execute(text(
        "SELECT COUNT(*) FROM audit_records a WHERE a.actor_user_id IS NOT NULL AND a.actor_user_id NOT IN (SELECT id FROM users)")).scalar()
    assert orphan_org == 0 and orphan_user == 0


def test_org_scoped_listings_never_leak_other_org_rows(
    client, db, org, org_b, source, tokens, auth_header, b_headers, png_bytes, cv_mock_model, active_device_factory, device_headers,
):
    _populate(client, db, org, org_b, source, tokens, auth_header, png_bytes, cv_mock_model, active_device_factory, device_headers, with_seed=False)
    # org B (empty of its own data in this flow) must see none of org A's rows through lists, aggregates or reports.
    for path in ("/events", "/evidence", "/relationships", "/investigations", "/media", "/inference/jobs",
                 "/reporting/reports", "/edge/sync/records", "/devices", "/ingestion/jobs", "/sources"):
        r = client.get(f"{API}{path}", headers=b_headers)
        assert r.status_code == 200, (path, r.status_code)
        body = r.json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        assert items == [] or all(i.get("organization_id") != org.id for i in items), path
    dash = client.get(f"{API}/dashboard/summary", headers=b_headers)
    if dash.status_code == 200:
        assert json.dumps(dash.json()).count(org.id) == 0
