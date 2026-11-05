"""Tenant isolation: audit scoping, referenced-record
association checks, direct media access, user administration across orgs.
Each test names the defect it pins."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit import AuditRecord
from app.models.event import Event
from app.models.organization import Organization
from app.models.user import User
from app.core.security import hash_password
from app.services import media_service

API = "/api/v1"


@pytest.fixture()
def org_b(db, test_password):
    o = Organization(name="Org B", status="active")
    db.add(o)
    db.flush()
    u = User(organization_id=o.id, username="badmin", email="badmin@b.example.com", display_name="B", password_hash=hash_password(test_password), role="administrator", is_active=True)
    db.add(u)
    db.commit()
    return o, u


@pytest.fixture()
def b_headers(client, org_b, test_password):
    r = client.post(f"{API}/auth/login", json={"username_or_email": "badmin", "password": test_password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _a_event(db, org, source):
    t = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    e = Event(organization_id=org.id, source_id=source.id, event_type="motion", title="A event", observed_at=t, ingested_at=t + timedelta(minutes=1), data_origin="user_upload")
    db.add(e)
    db.commit()
    return e


# ---- audit scoping (defect: NULL-org and foreign rows were visible) --------------

def test_audit_list_never_returns_null_org_or_foreign_org_rows(client, db, org, org_b, seeded_users, tokens, auth_header, b_headers):
    ob, _ = org_b
    db.add(AuditRecord(action="system.event", organization_id=None, outcome="success", context_metadata={"n": 1}))
    db.add(AuditRecord(action="b.private", organization_id=ob.id, outcome="success", context_metadata={"n": 2}))
    db.add(AuditRecord(action="a.visible", organization_id=org.id, outcome="success", context_metadata={"n": 3}))
    db.commit()
    a = client.get(f"{API}/audit?page_size=200", headers=auth_header(tokens, "admin")).json()
    actions = {i["action"] for i in a["items"]}
    assert "a.visible" in actions and "system.event" not in actions and "b.private" not in actions
    assert all(i["organization_id"] == org.id for i in a["items"])
    b = client.get(f"{API}/audit?page_size=200", headers=b_headers).json()
    assert "b.private" in {i["action"] for i in b["items"]} and "a.visible" not in {i["action"] for i in b["items"]}


def test_failed_login_for_unknown_identifier_not_exposed_to_any_org(client, db, seeded_users, tokens, auth_header):
    client.post(f"{API}/auth/login", json={"username_or_email": "nobody-here", "password": "whatever-pass-1"})
    assert db.query(AuditRecord).filter(AuditRecord.organization_id.is_(None), AuditRecord.action == "auth.login").count() == 1
    items = client.get(f"{API}/audit?action=auth.login&page_size=200", headers=auth_header(tokens, "admin")).json()["items"]
    assert all(i["organization_id"] is not None for i in items)


def test_audit_get_by_id_is_org_scoped_and_admin_only(client, db, org, org_b, seeded_users, tokens, auth_header, b_headers):
    ob, _ = org_b
    row = AuditRecord(action="b.private", organization_id=ob.id, outcome="success", context_metadata={})
    db.add(row)
    db.commit()
    assert client.get(f"{API}/audit/{row.id}", headers=auth_header(tokens, "admin")).status_code == 404
    assert client.get(f"{API}/audit/{row.id}", headers=b_headers).status_code == 200
    assert client.get(f"{API}/audit/{row.id}", headers=auth_header(tokens, "analyst")).status_code == 403


def test_audit_filters(client, db, org, seeded_users, tokens, auth_header):
    now = datetime.now(timezone.utc)
    db.add_all([
        AuditRecord(action="x.one", organization_id=org.id, actor_user_id=seeded_users["viewer"].id, target_type="thing", target_id="t1", outcome="success", request_id="req-aaaaaaaa", context_metadata={}),
        AuditRecord(action="x.two", organization_id=org.id, actor_user_id=seeded_users["analyst"].id, target_type="thing", target_id="t2", outcome="failure", request_id="req-bbbbbbbb", context_metadata={}),
        AuditRecord(action="y.three", organization_id=org.id, outcome="denied", context_metadata={}),
    ])
    db.commit()
    h = auth_header(tokens, "admin")
    q = lambda s: client.get(f"{API}/audit?{s}", headers=h).json()
    assert q("action=x.one")["total"] == 1
    assert q("action_prefix=x.")["total"] == 2
    assert q("action_prefix=x_")["total"] == 0  # LIKE wildcard is escaped
    assert q("outcome=denied")["total"] == 1
    assert q(f"actor_user_id={seeded_users['viewer'].id}&action_prefix=x.")["total"] == 1
    assert q("target_type=thing&target_id=t2")["total"] == 1
    assert q("request_id=req-bbbbbbbb")["total"] == 1
    future = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    assert q(f"action_prefix=x.&created_from={future}")["total"] == 0
    assert client.get(f"{API}/audit?outcome=bogus", headers=h).status_code == 422
    assert client.get(f"{API}/audit?page_size=5000", headers=h).status_code == 422
    assert "x.one" in client.get(f"{API}/audit/actions", headers=h).json()


# ---- referenced-record association (defects: sensors, evidence, devices, investigations) -----

def test_sensor_create_rejects_other_orgs_source_and_asset(client, db, org, org_b, source, b_headers, seeded_users, tokens, auth_header):
    a_asset = client.post(f"{API}/assets", headers=auth_header(tokens, "admin"), json={"name": "pump", "entity_type": "facility"}).json()
    r = client.post(f"{API}/sensors", headers=b_headers, json={"name": "s", "sensor_type": "temp", "source_id": source.id})
    assert r.status_code == 404 and r.json()["detail"] == "Data source not found"
    r = client.post(f"{API}/sensors", headers=b_headers, json={"name": "s", "sensor_type": "temp", "asset_id": a_asset["id"]})
    assert r.status_code == 404 and r.json()["detail"] == "Asset not found"
    # same-org association still works
    ok = client.post(f"{API}/sensors", headers=auth_header(tokens, "admin"), json={"name": "s", "sensor_type": "temp", "source_id": source.id, "asset_id": a_asset["id"]})
    assert ok.status_code == 201


def test_sensor_update_rejects_other_orgs_asset(client, org_b, b_headers, seeded_users, tokens, auth_header):
    a_asset = client.post(f"{API}/assets", headers=auth_header(tokens, "admin"), json={"name": "pump", "entity_type": "facility"}).json()
    sid = client.post(f"{API}/sensors", headers=b_headers, json={"name": "bs", "sensor_type": "temp"}).json()["id"]
    r = client.patch(f"{API}/sensors/{sid}", headers=b_headers, json={"asset_id": a_asset["id"]})
    assert r.status_code == 404
    assert client.get(f"{API}/sensors/{sid}", headers=b_headers).json()["asset_id"] is None


def test_evidence_create_rejects_other_orgs_event(client, db, org, source, b_headers):
    ev = _a_event(db, org, source)
    r = client.post(f"{API}/evidence", headers=b_headers, json={"evidence_type": "observation", "title": "stolen link", "event_id": ev.id})
    assert r.status_code == 404 and r.json()["detail"] == "Event not found"
    r2 = client.post(f"{API}/evidence", headers=b_headers, json={"evidence_type": "ingestion_record", "title": "t", "raw_record_id": "00000000-0000-0000-0000-000000000000"})
    assert r2.status_code == 404


def test_evidence_create_same_org_event_still_works(client, db, org, source, seeded_users, tokens, auth_header):
    ev = _a_event(db, org, source)
    r = client.post(f"{API}/evidence", headers=auth_header(tokens, "admin"), json={"evidence_type": "observation", "title": "ok", "event_id": ev.id})
    assert r.status_code == 201, r.text


def test_investigation_rejects_foreign_linked_event_but_tolerates_legacy_dangling_id(client, db, org, source, b_headers, seeded_users, tokens, auth_header):
    ev = _a_event(db, org, source)
    assert client.post(f"{API}/investigations", headers=b_headers, json={"title": "t", "linked_event_ids": [ev.id]}).status_code == 404
    iid = client.post(f"{API}/investigations", headers=b_headers, json={"title": "t"}).json()["id"]
    assert client.patch(f"{API}/investigations/{iid}", headers=b_headers, json={"linked_event_ids": [ev.id]}).status_code == 404
    # a dangling (nonexistent-anywhere) id is legacy-tolerated, as
    assert client.post(f"{API}/investigations", headers=auth_header(tokens, "admin"), json={"title": "t", "linked_event_ids": ["missing-id"]}).status_code == 201


def test_device_register_rejects_other_orgs_site(client, org_b, b_headers, seeded_users, tokens, auth_header):
    site = client.post(f"{API}/fleet/sites", headers=auth_header(tokens, "admin"), json={"name": "Site A"})
    assert site.status_code in (200, 201), site.text
    r = client.post(f"{API}/devices", headers=b_headers, json={"device_identifier": "dev-b-1", "device_name": "D", "device_type": "field_sensor_node", "site_id": site.json()["id"]})
    assert r.status_code == 404 and r.json()["detail"] == "Site not found", r.text


def test_investigation_member_and_assignee_must_be_same_org(client, org_b, b_headers, seeded_users):
    iid = client.post(f"{API}/investigations", headers=b_headers, json={"title": "t"}).json()["id"]
    a_user = seeded_users["analyst"].id
    assert client.post(f"{API}/investigations", headers=b_headers, json={"title": "t2", "assigned_user_id": a_user}).status_code in (404, 422)
    assert client.post(f"{API}/investigations/{iid}/members", headers=b_headers, json={"user_id": a_user}).status_code in (404, 422)


# ---- direct media access ------------------------------------------------------------

def test_media_content_cross_org_and_unauthenticated(client, db, org, org_b, png_bytes, b_headers, seeded_users, tokens, auth_header):
    asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="a.png", content=png_bytes(), uploaded_by_user_id=None)
    assert client.get(f"{API}/media/{asset.id}/content", headers=b_headers).status_code == 404
    assert client.get(f"{API}/media/{asset.id}", headers=b_headers).status_code == 404
    assert client.get(f"{API}/media/{asset.id}/content").status_code == 401
    ok = client.get(f"{API}/media/{asset.id}/content", headers=auth_header(tokens, "viewer"))
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert asset.id not in str(client.get(f"{API}/media", headers=b_headers).json())


# ---- user administration across orgs -------------------------------------------------

def test_user_admin_routes_do_not_cross_orgs(client, org_b, b_headers, seeded_users):
    uid = seeded_users["viewer"].id
    assert client.get(f"{API}/users/{uid}", headers=b_headers).status_code == 404
    assert client.patch(f"{API}/users/{uid}", headers=b_headers, json={"role": "administrator"}).status_code == 404
    assert client.post(f"{API}/users/{uid}/revoke-sessions", headers=b_headers).status_code == 404
    assert client.post(f"{API}/users/{uid}/reset-password", headers=b_headers, json={"new_password": "Str0ngPassphrase-42"}).status_code == 404
    assert client.get(f"{API}/users/{uid}/access-history", headers=b_headers).status_code == 404
    listed = client.get(f"{API}/users", headers=b_headers).json()
    assert {u["username"] for u in listed} == {"badmin"}


def test_role_gate_blocks_privilege_escalation_via_create(client, seeded_users, tokens, auth_header):
    body = {"username": "evil1", "email": "evil1@test.example.com", "display_name": "E", "password": "Str0ngPassphrase-42", "role": "administrator"}
    assert client.post(f"{API}/users", headers=auth_header(tokens, "analyst"), json=body).status_code == 403
    assert client.post(f"{API}/users", headers=auth_header(tokens, "investigator"), json=body).status_code == 403


# ---- stored-artifact integrity & access audit ---------------------------------------------

def test_media_download_is_audited_and_hash_verified(client, db, org, png_bytes, seeded_users, tokens, auth_header):
    from app.cv import storage
    asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="a.png", content=png_bytes(), uploaded_by_user_id=None)
    ok = client.get(f"{API}/media/{asset.id}/content", headers=auth_header(tokens, "viewer"))
    assert ok.status_code == 200 and ok.headers["cache-control"] == "private, no-store"
    row = db.query(AuditRecord).filter(AuditRecord.action == "media.content_access").first()
    assert row.actor_user_id == seeded_users["viewer"].id and row.target_id == asset.id
    # corrupt the stored file: it must not be served
    with open(storage.path_for(asset.storage_key), "ab") as fh:
        fh.write(b"tamper")
    bad = client.get(f"{API}/media/{asset.id}/content", headers=auth_header(tokens, "viewer"))
    assert bad.status_code == 500 and "integrity" in bad.json()["detail"]
    assert db.query(AuditRecord).filter(AuditRecord.action == "media.integrity_failure").count() == 1


def test_missing_stored_file_is_410_not_a_crash(client, db, org, png_bytes, seeded_users, tokens, auth_header):
    import os
    from app.cv import storage
    asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="a.png", content=png_bytes(color=(5, 6, 7)), uploaded_by_user_id=None)
    os.remove(storage.path_for(asset.storage_key))
    r = client.get(f"{API}/media/{asset.id}/content", headers=auth_header(tokens, "viewer"))
    assert r.status_code == 410 and "missing" in r.json()["detail"]


# ---- export permissions ---------------------------------------------------------------------

@pytest.mark.parametrize("role,expected", [("viewer", 403), ("investigator", 403), ("analyst", 200), ("admin", 200)])
def test_bulk_event_and_geo_exports_are_role_gated(client, seeded_users, tokens, auth_header, role, expected):
    h = auth_header(tokens, role)
    assert client.get(f"{API}/events/export?format=csv", headers=h).status_code == expected
    assert client.get(f"{API}/geospatial/export/geojson?record_types=event", headers=h).status_code == expected


def test_investigation_export_requires_permission_and_org(client, org_b, b_headers, seeded_users, tokens, auth_header):
    iid = client.post(f"{API}/investigations", headers=auth_header(tokens, "admin"), json={"title": "exp"}).json()["id"]
    assert client.post(f"{API}/investigations/{iid}/export", headers=auth_header(tokens, "viewer")).status_code == 403
    assert client.post(f"{API}/investigations/{iid}/export", headers=b_headers).status_code == 404
    assert client.post(f"{API}/investigations/{iid}/export", headers=auth_header(tokens, "analyst")).status_code == 200
    assert client.get(f"{API}/scenarios/{iid}/export", headers=b_headers).status_code == 404


def test_geospatial_relationship_generation_is_audited(client, db, seeded_users, tokens, auth_header):
    r = client.post(f"{API}/geospatial/relationships/generate", headers=auth_header(tokens, "analyst"), json={})
    assert r.status_code == 200, r.text
    assert db.query(AuditRecord).filter(AuditRecord.action == "geospatial.relationships_generate").count() == 1
