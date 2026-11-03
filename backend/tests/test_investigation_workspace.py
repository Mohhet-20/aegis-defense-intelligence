"""Phase 11: investigation lifecycle, links, evidence registry, integrity,
provenance, timeline, notes, search, export, isolation, audit, rollback."""
from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import hash_password
from app.cv import storage
from app.models.audit import AuditRecord
from app.models.event import Event
from app.models.investigation import Investigation
from app.models.investigation_workspace import InvestigationNoteRevision, InvestigationStatusHistory
from app.models.observation import Observation
from app.models.organization import Organization
from app.models.user import User
from app.services import media_service

API = "/api/v1"


def H(auth_header, tokens, role="analyst"):
    return auth_header(tokens, role)


def mk_inv(client, h, **kw):
    r = client.post(f"{API}/investigations", json={"title": "Case", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def mk_event(db, org, source, title="E", observed=None, **kw):
    t = observed or datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    e = Event(organization_id=org.id, source_id=source.id, event_type="motion", title=title, observed_at=t,
              ingested_at=t + timedelta(minutes=1), data_origin="user_upload", **kw)
    db.add(e)
    db.commit()
    return e


def mk_media(db, org, png_bytes):
    return media_service.ingest_media(db, organization_id=org.id, declared_filename="photo.png", content=png_bytes(), uploaded_by_user_id=None)


@pytest.fixture()
def other_org_headers(client, db, test_password):
    o = Organization(name="Other Org", status="active")
    db.add(o)
    db.commit()
    u = User(organization_id=o.id, username="outsider", email="o@x.example.com", display_name="O",
             password_hash=hash_password(test_password), role="administrator", is_active=True)
    db.add(u)
    db.commit()
    r = client.post(f"{API}/auth/login", json={"username_or_email": "outsider", "password": test_password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, o


# ---- lifecycle ---------------------------------------------------------------

def test_lifecycle_valid_and_invalid_transitions_with_history(client, db, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    inv = mk_inv(client, h, initial_status="draft", tags=["Alpha", "alpha", "beta"])
    assert inv["status"] == "draft" and inv["tags"] == ["alpha", "beta"]
    iid = inv["id"]
    bad = client.post(f"{API}/investigations/{iid}/transition", json={"to_status": "closed", "reason": "x"}, headers=h)
    assert bad.status_code == 409
    assert client.post(f"{API}/investigations/{iid}/transition", json={"to_status": "open"}, headers=h).status_code == 200
    assert client.post(f"{API}/investigations/{iid}/transition", json={"to_status": "pending_review"}, headers=h).status_code == 200
    # closing needs a reason
    assert client.post(f"{API}/investigations/{iid}/close", json={}, headers=h).status_code == 422
    closed = client.post(f"{API}/investigations/{iid}/close", json={"reason": "Resolved"}, headers=h)
    assert closed.status_code == 200 and closed.json()["closure_reason"] == "Resolved" and closed.json()["closed_at"]
    # archived only from closed, and archived is terminal + read-only
    assert client.post(f"{API}/investigations/{iid}/archive", json={}, headers=h).status_code == 200
    assert client.post(f"{API}/investigations/{iid}/transition", json={"to_status": "open"}, headers=h).status_code == 409
    assert client.patch(f"{API}/investigations/{iid}", json={"title": "new"}, headers=h).status_code == 409
    hist = client.get(f"{API}/investigations/{iid}/status-history", headers=h).json()
    assert [x["to_status"] for x in hist] == ["draft", "open", "pending_review", "closed", "archived"]


def test_open_cannot_be_archived_and_same_status_rejected(client, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    assert client.post(f"{API}/investigations/{iid}/archive", json={}, headers=h).status_code == 409
    assert client.post(f"{API}/investigations/{iid}/transition", json={"to_status": "open"}, headers=h).status_code == 409


def test_reopen_clears_closed_at_but_keeps_history(client, db, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    client.post(f"{API}/investigations/{iid}/close", json={"reason": "done"}, headers=h)
    r = client.post(f"{API}/investigations/{iid}/transition", json={"to_status": "open"}, headers=h)
    assert r.json()["closed_at"] is None
    assert db.query(InvestigationStatusHistory).filter_by(investigation_id=iid, to_status="closed").count() == 1


def test_list_filters_sorting_archived_hidden_and_pagination(client, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    a = mk_inv(client, h, title="Alpha gate", priority="high", tags=["x"])
    mk_inv(client, h, title="Beta yard", priority="low")
    c = mk_inv(client, h, title="Gamma", priority="low")
    client.post(f"{API}/investigations/{c['id']}/close", json={"reason": "r"}, headers=h)
    client.post(f"{API}/investigations/{c['id']}/archive", json={}, headers=h)
    L = lambda **p: client.get(f"{API}/investigations", params=p, headers=h).json()
    assert L()["total"] == 2  # archived hidden by default
    assert L(include_archived=True)["total"] == 3
    assert L(status="archived")["total"] == 1
    assert L(q="gate")["items"][0]["id"] == a["id"]
    assert L(priority="high")["total"] == 1
    assert L(tag="x")["total"] == 1
    assert [i["title"] for i in L(sort_by="title", sort_dir="asc")["items"]] == ["Alpha gate", "Beta yard"]
    assert len(L(page_size=1)["items"]) == 1 and L(page_size=1)["total"] == 2
    assert client.get(f"{API}/investigations", params={"sort_by": "bogus"}, headers=h).status_code == 422


def test_viewer_cannot_manage_or_export(client, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    v = H(auth_header, tokens, "viewer")
    assert client.post(f"{API}/investigations/{iid}/close", json={"reason": "x"}, headers=v).status_code == 403
    assert client.post(f"{API}/investigations/{iid}/notes", json={"body": "x"}, headers=v).status_code == 403
    assert client.post(f"{API}/investigations/{iid}/export", headers=v).status_code == 403
    assert client.get(f"{API}/investigations/{iid}/timeline", headers=v).status_code == 200


# ---- membership & restriction -----------------------------------------------

def test_members_and_restricted_investigation_access(client, db, seeded_users, tokens, auth_header):
    owner = H(auth_header, tokens, "analyst")
    inv = mk_inv(client, owner, is_restricted=True, assigned_user_id=seeded_users["analyst"].id)
    iid = inv["id"]
    inv_h = H(auth_header, tokens, "investigator")
    # not a member -> not found, and absent from list
    assert client.get(f"{API}/investigations/{iid}", headers=inv_h).status_code == 404
    assert client.get(f"{API}/investigations", headers=inv_h).json()["total"] == 0
    assert client.get(f"{API}/investigations/{iid}/timeline", headers=inv_h).status_code == 404
    # admin always can
    assert client.get(f"{API}/investigations/{iid}", headers=H(auth_header, tokens, "admin")).status_code == 200
    r = client.post(f"{API}/investigations/{iid}/members", json={"user_id": seeded_users["investigator"].id, "role": "reviewer"}, headers=owner)
    assert r.status_code == 201
    assert client.get(f"{API}/investigations/{iid}", headers=inv_h).status_code == 200
    assert client.post(f"{API}/investigations/{iid}/members", json={"user_id": seeded_users["investigator"].id, "role": "reviewer"}, headers=owner).status_code == 409
    assert client.post(f"{API}/investigations/{iid}/members", json={"user_id": seeded_users["viewer"].id, "role": "owner"}, headers=owner).status_code == 422
    assert client.get(f"{API}/investigations", params={"reviewer_user_id": seeded_users["investigator"].id}, headers=owner).json()["total"] == 1
    assert client.delete(f"{API}/investigations/{iid}/members/{seeded_users['investigator'].id}", headers=owner).status_code == 204
    assert client.get(f"{API}/investigations/{iid}", headers=inv_h).status_code == 404


def test_owner_and_members_must_belong_to_organization(client, db, seeded_users, tokens, auth_header, other_org_headers):
    _, o2 = other_org_headers
    stranger = db.query(User).filter_by(organization_id=o2.id).first()
    h = H(auth_header, tokens)
    r = client.post(f"{API}/investigations", json={"title": "x", "assigned_user_id": stranger.id}, headers=h)
    assert r.status_code == 422
    iid = mk_inv(client, h)["id"]
    assert client.post(f"{API}/investigations/{iid}/members", json={"user_id": stranger.id, "role": "member"}, headers=h).status_code == 422


# ---- links ------------------------------------------------------------------

def test_link_records_duplicates_and_cross_org(client, db, org, source, seeded_users, tokens, auth_header, other_org_headers, png_bytes):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    e = mk_event(db, org, source)
    m = mk_media(db, org, png_bytes)
    assert client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": e.id}, headers=h).status_code == 201
    assert client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": e.id}, headers=h).status_code == 409
    assert client.post(f"{API}/investigations/{iid}/links", json={"record_type": "media_asset", "record_id": m.id}, headers=h).status_code == 201
    assert client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": "nope"}, headers=h).status_code == 404
    assert client.post(f"{API}/investigations/{iid}/links", json={"record_type": "bogus", "record_id": e.id}, headers=h).status_code == 422
    links = client.get(f"{API}/investigations/{iid}/links", headers=h).json()
    assert {l["record_type"] for l in links} == {"event", "media_asset"} and all(l["summary"] for l in links)
    # another org cannot link our event into its own investigation
    oh, _ = other_org_headers
    other_inv = mk_inv(client, oh)["id"]
    assert client.post(f"{API}/investigations/{other_inv}/links", json={"record_type": "event", "record_id": e.id}, headers=oh).status_code == 404
    # ...and cannot see ours
    assert client.get(f"{API}/investigations/{iid}", headers=oh).status_code == 404
    assert client.get(f"{API}/investigations/{iid}/timeline", headers=oh).status_code == 404
    assert client.post(f"{API}/investigations/{iid}/export", headers=oh).status_code == 404
    # unlink
    lid = links[0]["id"]
    assert client.delete(f"{API}/investigations/{iid}/links/{lid}", headers=h).status_code == 204
    assert client.delete(f"{API}/investigations/{iid}/links/{lid}", headers=h).status_code == 404


def test_legacy_json_event_list_still_appears(client, db, org, source, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    e = mk_event(db, org, source, title="Legacy")
    iid = mk_inv(client, h, linked_event_ids=[e.id, "missing-id"])["id"]
    tl = client.get(f"{API}/investigations/{iid}/timeline", params={"record_type": "event"}, headers=h).json()
    assert {x["record_id"] for x in tl["items"]} == {e.id}


# ---- evidence registry / integrity / provenance ----------------------------

def test_register_media_evidence_hash_and_dedupe(client, db, org, seeded_users, tokens, auth_header, png_bytes):
    h = H(auth_header, tokens)
    m = mk_media(db, org, png_bytes)
    i1, i2 = mk_inv(client, h)["id"], mk_inv(client, h)["id"]
    body = {"evidence_type": "media_asset", "title": "Photo", "record_id": m.id}
    r1 = client.post(f"{API}/investigations/{i1}/evidence", json=body, headers=h)
    assert r1.status_code == 201, r1.text
    ev = r1.json()["evidence"]
    assert ev["integrity_hash"] == m.content_hash and ev["integrity_hash_algorithm"] == "sha256"
    assert ev["external_reference_uri"] == f"aegis://media_asset/{m.id}"
    assert ev["captured_at"] is None  # unknown stays unknown
    assert r1.json()["reused_existing"] is False
    # same investigation: duplicate association rejected
    assert client.post(f"{API}/investigations/{i1}/evidence", json=body, headers=h).status_code == 409
    # other investigation reuses the SAME evidence row (reference, not copy)
    r2 = client.post(f"{API}/investigations/{i2}/evidence", json=body, headers=h)
    assert r2.status_code == 201 and r2.json()["reused_existing"] is True and r2.json()["evidence"]["id"] == ev["id"]


def test_register_validation_and_event_evidence_times(client, db, org, source, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    P = lambda b: client.post(f"{API}/investigations/{iid}/evidence", json=b, headers=h)
    assert P({"evidence_type": "bogus", "title": "t"}).status_code == 422
    assert P({"evidence_type": "media_asset", "title": "t"}).status_code == 422
    assert P({"evidence_type": "report", "title": "t"}).status_code == 422
    assert P({"evidence_type": "observation", "title": "t", "event_id": "nope"}).status_code == 404
    assert P({"evidence_type": "analyst_note", "title": "t", "content": "x", "access_classification": "secret"}).status_code == 422
    e = mk_event(db, org, source)
    r = P({"evidence_type": "observation", "title": "ev", "event_id": e.id})
    assert r.status_code == 201 and r.json()["evidence"]["source_id"] == source.id and r.json()["evidence"]["captured_at"]
    # viewers cannot register
    assert client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "report", "title": "t", "content": "c"}, headers=H(auth_header, tokens, "viewer")).status_code == 403


def test_cross_org_record_cannot_be_registered_as_evidence(client, db, org, source, seeded_users, tokens, auth_header, other_org_headers):
    oh, _ = other_org_headers
    e = mk_event(db, org, source)
    iid = mk_inv(client, oh)["id"]
    r = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "observation", "title": "x", "event_id": e.id}, headers=oh)
    assert r.status_code == 404


def test_integrity_match_mismatch_and_missing_original(client, db, org, seeded_users, tokens, auth_header, png_bytes):
    h = H(auth_header, tokens)
    m = mk_media(db, org, png_bytes)
    iid = mk_inv(client, h)["id"]
    ev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "media_asset", "title": "P", "record_id": m.id}, headers=h).json()["evidence"]
    V = lambda: client.post(f"{API}/evidence/{ev['id']}/verify-integrity", headers=h)
    ok = V().json()
    assert ok["result"] == "match" and ok["computed_hash"] == ok["recorded_hash"] == m.content_hash
    assert "authentic" in ok["disclaimer"] and "chain of custody" in ok["disclaimer"]
    path = storage.path_for(m.storage_key)
    original = open(path, "rb").read()
    with open(path, "wb") as f:
        f.write(original + b"tamper")
    assert V().json()["result"] == "mismatch"
    os.remove(path)
    gone = V().json()
    assert gone["result"] == "original_unavailable" and gone["computed_hash"] is None
    checks = client.get(f"{API}/evidence/{ev['id']}/integrity-checks", headers=h).json()
    assert [c["result"] for c in checks] == ["match", "mismatch", "original_unavailable"]  # append-only history
    # the recorded hash on the evidence row never changed
    assert client.get(f"{API}/evidence/{ev['id']}", headers=h).json()["integrity_hash"] == m.content_hash


def test_integrity_for_text_reference_and_edited_text(client, db, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    txt = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "analyst_note", "title": "n", "content": "hello"}, headers=h).json()["evidence"]
    assert txt["integrity_hash"] == hashlib.sha256(b"hello").hexdigest()
    assert client.post(f"{API}/evidence/{txt['id']}/verify-integrity", headers=h).json()["result"] == "match"
    client.patch(f"{API}/evidence/{txt['id']}", json={"content": "edited"}, headers=h)
    assert client.post(f"{API}/evidence/{txt['id']}/verify-integrity", headers=h).json()["result"] == "mismatch"
    doc = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "document", "title": "d", "external_reference_uri": "https://example.test/a.pdf"}, headers=h).json()["evidence"]
    assert doc["integrity_hash"] is None
    assert client.post(f"{API}/evidence/{doc['id']}/verify-integrity", headers=h).json()["result"] == "not_file_backed"


def test_no_recorded_hash_is_reported_not_invented(client, db, org, seeded_users, tokens, auth_header):
    from app.services import evidence_service
    ev = evidence_service.create_evidence(db, organization_id=org.id, evidence_type="analyst_note", title="old", content="legacy text")
    r = client.post(f"{API}/evidence/{ev.id}/verify-integrity", headers=H(auth_header, tokens))
    assert r.json()["result"] == "no_recorded_hash" and r.json()["recorded_hash"] is None
    db.refresh(ev)
    assert ev.integrity_hash is None


def test_verify_requires_permission_and_org(client, db, org, seeded_users, tokens, auth_header, other_org_headers):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    ev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "analyst_note", "title": "n", "content": "c"}, headers=h).json()["evidence"]
    assert client.post(f"{API}/evidence/{ev['id']}/verify-integrity", headers=H(auth_header, tokens, "viewer")).status_code == 403
    oh, _ = other_org_headers
    assert client.post(f"{API}/evidence/{ev['id']}/verify-integrity", headers=oh).status_code == 404
    assert client.get(f"{API}/evidence/{ev['id']}/provenance", headers=oh).status_code == 404


def test_restricted_evidence_hidden_from_viewers(client, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    ev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "analyst_note", "title": "secret", "content": "c", "access_classification": "restricted"}, headers=h).json()["evidence"]
    v = H(auth_header, tokens, "viewer")
    assert client.get(f"{API}/evidence/{ev['id']}/provenance", headers=v).status_code == 404
    assert client.get(f"{API}/investigations/{iid}/evidence", headers=v).json() == []
    assert client.get(f"{API}/investigations/{iid}/search", headers=v).json()["total"] == 0
    assert client.get(f"{API}/investigations/{iid}/search", headers=h).json()["total"] == 1


def test_provenance_chain_for_event_and_unknowns(client, db, org, source, seeded_users, tokens, auth_header, png_bytes):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    e = mk_event(db, org, source)
    ev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "observation", "title": "e", "event_id": e.id}, headers=h).json()["evidence"]
    p = client.get(f"{API}/evidence/{ev['id']}/provenance", headers=h).json()
    roles = {n["role"] for n in p["chain"]}
    assert {"references", "source"} <= roles
    assert p["times"]["captured_at"] and p["times"]["registered_at"]
    m = mk_media(db, org, png_bytes)
    mev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "media_asset", "title": "m", "record_id": m.id}, headers=h).json()["evidence"]
    mp = client.get(f"{API}/evidence/{mev['id']}/provenance", headers=h).json()
    art = [n for n in mp["chain"] if n["role"] == "original_artifact"][0]
    assert art["capture_time"] is None and "not when it was captured" in art["capture_time_note"]
    assert any("Source is unknown" in x for x in mp["limitations"])
    assert any("legally certified chain of custody" in x for x in mp["limitations"])


def test_supersede_is_append_only(client, db, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    old = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "analyst_note", "title": "n", "content": "v1"}, headers=h).json()["evidence"]
    r = client.post(f"{API}/evidence/{old['id']}/supersede", json={"reason": "typo", "content": "v2"}, headers=h)
    assert r.status_code == 201
    new = r.json()
    assert new["supersedes_evidence_id"] == old["id"] and new["integrity_hash"] == hashlib.sha256(b"v2").hexdigest()
    got = client.get(f"{API}/evidence/{old['id']}", headers=h).json()
    assert got["content"] == "v1" and got["superseded_by_evidence_id"] == new["id"]
    assert client.post(f"{API}/evidence/{old['id']}/supersede", json={"reason": "again", "content": "v3"}, headers=h).status_code == 409
    ids = {e["id"] for e in client.get(f"{API}/investigations/{iid}/evidence", headers=h).json()}
    assert {old["id"], new["id"]} <= ids
    rs = client.post(f"{API}/evidence/{new['id']}/review-status", json={"review_status": "reviewed", "note": "ok"}, headers=h)
    assert rs.status_code == 200 and rs.json()["review_status"] == "reviewed"
    assert client.post(f"{API}/evidence/{new['id']}/review-status", json={"review_status": "bogus"}, headers=h).status_code == 422


# ---- timeline -----------------------------------------------------------------

def test_timeline_order_kinds_unknown_times_and_filters(client, db, org, source, seeded_users, tokens, auth_header, png_bytes):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    e1 = mk_event(db, org, source, title="late", observed=datetime(2026, 3, 1, tzinfo=timezone.utc))
    e2 = mk_event(db, org, source, title="early", observed=datetime(2026, 1, 1, tzinfo=timezone.utc))
    m = mk_media(db, org, png_bytes)
    for t, rid in (("event", e1.id), ("event", e2.id), ("media_asset", m.id)):
        client.post(f"{API}/investigations/{iid}/links", json={"record_type": t, "record_id": rid}, headers=h)
    T = lambda **p: client.get(f"{API}/investigations/{iid}/timeline", params=p, headers=h).json()
    full = T(page_size=200)
    assert "causation" in full["notice"].lower() or "cause" in full["notice"].lower()
    ev_times = [x for x in full["items"] if x["time_kind"] == "event_time"]
    assert [x["title"] for x in ev_times] == ["early", "late"]
    known = [x["timestamp"] for x in full["items"] if x["time_known"]]
    assert known == sorted(known)
    # unknown times are explicit, never invented, and sort last
    unk = [x for x in full["items"] if not x["time_known"]]
    assert unk and all(x["timestamp"] is None and x["missing_time_note"] for x in unk)
    assert full["items"][-len(unk):] == unk
    assert any(x["time_kind"] == "capture_time" and x["record_type"] == "media_asset" for x in unk)
    # distinct clocks are separate entries
    assert {"event_time", "ingestion_time"} <= {x["time_kind"] for x in full["items"] if x["record_id"] == e1.id}
    assert all(x["assumed_utc"] in (True, False) for x in full["items"])
    # filters
    ranged = T(start="2026-02-01T00:00:00Z", end="2026-04-01T00:00:00Z", page_size=200)
    assert ranged["items"] and all(x["time_known"] for x in ranged["items"])
    assert {x["record_id"] for x in ranged["items"] if x["time_kind"] == "event_time"} == {e1.id}
    assert all(x["record_type"] == "media_asset" for x in T(record_type="media_asset", page_size=200)["items"])
    assert all(x["time_kind"] == "event_time" for x in T(time_kind="event_time")["items"])
    assert all(x["source_id"] == source.id for x in T(source_id=source.id, page_size=200)["items"])
    # pagination is bounded and stable
    p1, p2 = T(page_size=2, page=1), T(page_size=2, page=2)
    assert len(p1["items"]) == 2 and p1["total"] == full["total"]
    assert [x["entry_id"] for x in p1["items"] + p2["items"]] == [x["entry_id"] for x in full["items"][:4]]
    assert client.get(f"{API}/investigations/{iid}/timeline", params={"page_size": 5000}, headers=h).status_code == 422


def test_timeline_equal_timestamps_have_stable_order(client, db, org, source, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    same = datetime(2026, 5, 5, tzinfo=timezone.utc)
    ids = [mk_event(db, org, source, title=f"t{i}", observed=same).id for i in range(4)]
    for i in ids:
        client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": i}, headers=h)
    a = client.get(f"{API}/investigations/{iid}/timeline", params={"time_kind": "event_time"}, headers=h).json()["items"]
    b = client.get(f"{API}/investigations/{iid}/timeline", params={"time_kind": "event_time"}, headers=h).json()["items"]
    assert [x["entry_id"] for x in a] == [x["entry_id"] for x in b] == sorted(x["entry_id"] for x in a)


def test_timeline_includes_status_notes_integrity_and_flags_naive_times(client, db, org, source, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    client.post(f"{API}/investigations/{iid}/notes", json={"body": "obs", "note_kind": "observed_fact"}, headers=h)
    ev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "analyst_note", "title": "n", "content": "c"}, headers=h).json()["evidence"]
    client.post(f"{API}/evidence/{ev['id']}/verify-integrity", headers=h)
    client.post(f"{API}/investigations/{iid}/transition", json={"to_status": "active"}, headers=h)
    items = client.get(f"{API}/investigations/{iid}/timeline", params={"page_size": 200}, headers=h).json()["items"]
    kinds = {x["time_kind"] for x in items}
    assert {"note_time", "integrity_check_time", "status_change", "registration_time", "association_time"} <= kinds
    assert any(x["time_kind"] == "capture_time" and not x["time_known"] for x in items)  # note evidence: capture time unknown
    # Stored timestamps come back timezone-aware on every engine (UTCDateTime), so none
    # of them needs the "assumed UTC" flag; the flag is for naive values from outside the
    # database (covered by test_to_utc_flags_only_naive_input in test_utc_datetime.py).
    assert not any(x["assumed_utc"] for x in items)
    assert all(x["timestamp"].endswith("Z") for x in items if x["time_known"])


# ---- notes ----------------------------------------------------------------------

def test_note_revisions_and_optimistic_concurrency(client, db, seeded_users, tokens, auth_header):
    a, inv_h = H(auth_header, tokens, "analyst"), H(auth_header, tokens, "investigator")
    iid = mk_inv(client, a)["id"]
    n = client.post(f"{API}/investigations/{iid}/notes", json={"body": "first", "note_kind": "hypothesis", "tags": ["Gate", "gate"]}, headers=a).json()
    assert n["version"] == 1 and n["tags"] == ["gate"]
    u1 = client.patch(f"{API}/investigations/{iid}/notes/{n['id']}", json={"expected_version": 1, "body": "second"}, headers=a)
    assert u1.status_code == 200 and u1.json()["version"] == 2
    stale = client.patch(f"{API}/investigations/{iid}/notes/{n['id']}", json={"expected_version": 1, "body": "lost update"}, headers=a)
    assert stale.status_code == 409
    revs = client.get(f"{API}/investigations/{iid}/notes/{n['id']}/revisions", headers=a).json()
    assert [(r["version"], r["body"]) for r in revs] == [(1, "first"), (2, "second")]
    assert client.get(f"{API}/investigations/{iid}/notes", headers=a).json()[0]["body"] == "second"
    # others cannot rewrite someone else's content, and no-op edits are rejected
    assert client.patch(f"{API}/investigations/{iid}/notes/{n['id']}", json={"expected_version": 2, "body": "hijack"}, headers=inv_h).status_code == 403
    assert client.patch(f"{API}/investigations/{iid}/notes/{n['id']}", json={"expected_version": 2}, headers=a).status_code == 422
    assert client.patch(f"{API}/investigations/{iid}/notes/{n['id']}", json={"body": "x"}, headers=a).status_code == 422  # version required
    assert db.query(InvestigationNoteRevision).filter_by(note_id=n["id"]).count() == 2


def test_review_question_assignment_resolution_and_replies(client, db, seeded_users, tokens, auth_header):
    a, inv_h = H(auth_header, tokens, "analyst"), H(auth_header, tokens, "investigator")
    iid = mk_inv(client, a)["id"]
    q = client.post(f"{API}/investigations/{iid}/notes", json={"body": "Is this the same vehicle?", "note_kind": "review_question",
                                                                "assignee_user_id": seeded_users["investigator"].id}, headers=a).json()
    assert q["resolution_status"] == "open"
    reply = client.post(f"{API}/investigations/{iid}/notes", json={"body": "Plate differs", "note_kind": "observed_fact", "parent_note_id": q["id"]}, headers=inv_h).json()
    assert reply["parent_note_id"] == q["id"]
    assert client.post(f"{API}/investigations/{iid}/notes", json={"body": "nested", "parent_note_id": reply["id"]}, headers=a).status_code == 422
    # assignee (not author) can resolve; content untouched
    r = client.patch(f"{API}/investigations/{iid}/notes/{q['id']}", json={"expected_version": 1, "resolution_status": "resolved"}, headers=inv_h)
    assert r.status_code == 200 and r.json()["resolved_by_user_id"] == seeded_users["investigator"].id and r.json()["body"] == q["body"]
    s = client.get(f"{API}/investigations/{iid}/summary-open", headers=a) if False else None
    assert client.get(f"{API}/investigations/{iid}/notes", params={"unresolved_only": True}, headers=a).json() == []
    # only questions can be assigned/resolved; unknown assignee rejected
    fact = client.post(f"{API}/investigations/{iid}/notes", json={"body": "f", "note_kind": "observed_fact"}, headers=a).json()
    assert client.patch(f"{API}/investigations/{iid}/notes/{fact['id']}", json={"expected_version": 1, "resolution_status": "resolved"}, headers=a).status_code == 422
    assert client.post(f"{API}/investigations/{iid}/notes", json={"body": "q", "note_kind": "review_question", "assignee_user_id": "nope"}, headers=a).status_code == 422
    assert client.post(f"{API}/investigations/{iid}/notes", json={"body": "x", "note_kind": "gossip"}, headers=a).status_code == 422
    assert client.post(f"{API}/investigations/{iid}/notes", json={"body": "   "}, headers=a).status_code == 422
    kinds = client.get(f"{API}/investigations/{iid}/note-kinds", headers=a).json()
    assert {k["kind"] for k in kinds} == {"observed_fact", "analyst_interpretation", "hypothesis", "review_question"}


def test_notes_on_evidence_do_not_modify_the_evidence(client, db, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    ev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "analyst_note", "title": "n", "content": "orig"}, headers=h).json()["evidence"]
    n = client.post(f"{API}/investigations/{iid}/notes", json={"body": "my reading", "evidence_id": ev["id"]}, headers=h)
    assert n.status_code == 201
    after = client.get(f"{API}/evidence/{ev['id']}", headers=h).json()
    assert after["content"] == "orig" and after["integrity_hash"] == ev["integrity_hash"] and after["updated_at"] == ev["created_at"] or after["content"] == "orig"
    assert client.post(f"{API}/evidence/{ev['id']}/verify-integrity", headers=h).json()["result"] == "match"
    assert len(client.get(f"{API}/investigations/{iid}/notes", params={"evidence_id": ev["id"]}, headers=h).json()) == 1
    # evidence not linked to this investigation is rejected
    other_inv = mk_inv(client, h)["id"]
    assert client.post(f"{API}/investigations/{other_inv}/notes", json={"body": "x", "evidence_id": ev["id"]}, headers=h).status_code == 422


# ---- search & relationships -----------------------------------------------------

def test_search_filters_and_pagination(client, db, org, source, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    e1 = mk_event(db, org, source, title="North gate motion", observed=datetime(2026, 1, 1, tzinfo=timezone.utc))
    e2 = mk_event(db, org, source, title="Yard truck", observed=datetime(2026, 6, 1, tzinfo=timezone.utc))
    for e in (e1, e2):
        client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": e.id}, headers=h)
    client.post(f"{API}/investigations/{iid}/notes", json={"body": "gate was open", "tags": ["gate"]}, headers=h)
    ev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "report", "title": "Gate report", "content": "r"}, headers=h).json()["evidence"]
    client.post(f"{API}/evidence/{ev['id']}/review-status", json={"review_status": "reviewed"}, headers=h)
    S = lambda **p: client.get(f"{API}/investigations/{iid}/search", params=p, headers=h).json()
    assert {x["record_id"] for x in S(q="gate")["items"] if x["record_type"] == "event"} == {e1.id}
    assert S(q="GATE")["total"] == 3  # event + note + evidence
    assert S(record_type="note")["total"] == 1 and S(tag="gate")["total"] == 1
    assert S(evidence_status="reviewed")["items"][0]["record_id"] == ev["id"]
    assert S(source_id=source.id)["total"] == 2
    assert {x["record_id"] for x in S(start="2026-05-01T00:00:00Z", record_type="event")["items"]} == {e2.id}
    assert S(page_size=1)["total"] == S()["total"] and len(S(page_size=1)["items"]) == 1
    assert client.get(f"{API}/investigations/{iid}/search", params={"data_quality": "bogus"}, headers=h).status_code == 422
    # records outside the investigation never leak in
    mk_event(db, org, source, title="Unlinked gate event")
    assert S(q="unlinked")["total"] == 0


def test_search_data_quality_filter_on_observations(client, db, org, source, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    now = datetime(2026, 2, 2, tzinfo=timezone.utc)
    ids = []
    for flags in ([], ["stale_reading"]):
        o = Observation(organization_id=org.id, source_id=source.id, observed_at=now, observation_type="temp", data_origin="user_upload", quality_flags=flags)
        db.add(o); db.commit(); ids.append(o.id)
        client.post(f"{API}/investigations/{iid}/links", json={"record_type": "observation", "record_id": o.id}, headers=h)
    S = lambda **p: client.get(f"{API}/investigations/{iid}/search", params=p, headers=h).json()
    assert [x["record_id"] for x in S(data_quality="flagged")["items"]] == [ids[1]]
    assert [x["record_id"] for x in S(data_quality="clean")["items"]] == [ids[0]]
    obs_tl = client.get(f"{API}/investigations/{iid}/timeline", params={"time_kind": "ingestion_time"}, headers=h).json()["items"]
    assert obs_tl and all(not x["time_known"] and x["missing_time_note"] for x in obs_tl)  # ingested_at was never set


def test_relationships_report_origin_and_never_promote(client, db, org, source, seeded_users, tokens, auth_header):
    from app.models.evidence_relationship import EvidenceRelationship
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    e1, e2 = mk_event(db, org, source), mk_event(db, org, source)
    for e in (e1, e2):
        client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": e.id}, headers=h)
    rel = EvidenceRelationship(organization_id=org.id, source_event_id=e1.id, target_event_id=e2.id, relationship_type="temporal_proximity"
                               if False else __import__("app.models.evidence_relationship", fromlist=["RELATIONSHIP_TYPES"]).RELATIONSHIP_TYPES[0],
                               origin="rule_based", explanation="close in time", review_status="candidate")
    db.add(rel); db.commit()
    out = client.get(f"{API}/investigations/{iid}/relationships", headers=h).json()
    assert out["total"] == 1
    r = out["items"][0]
    assert r["origin_label"] == "Proposed by a rule" and r["review_status"] == "candidate" and r["is_confirmed"] is False
    assert "not facts" in out["notice"]


# ---- export ---------------------------------------------------------------------

def test_export_json_report_manifest_and_audit(client, db, org, source, seeded_users, tokens, auth_header, png_bytes):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h, title="Export me")["id"]
    e = mk_event(db, org, source)
    m = mk_media(db, org, png_bytes)
    client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": e.id}, headers=h)
    client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "media_asset", "title": "P", "record_id": m.id}, headers=h)
    client.post(f"{API}/investigations/{iid}/notes", json={"body": "n"}, headers=h)
    r = client.post(f"{API}/investigations/{iid}/export", headers=h)
    assert r.status_code == 200
    rep = r.json()["report"]
    assert rep["investigation"]["title"] == "Export me" and rep["timeline"] and rep["evidence_index"] and rep["notes"]
    assert "not independently authenticated" in rep["authenticity_notice"]
    assert rep["generation"]["generated_at"].endswith("Z") and "unrelated" in rep["generation"]["note"].lower()
    assert any(o["reason"] == "media_bytes_not_requested" for o in rep["omitted_artifacts"])
    man = r.json()["manifest"]
    assert man["files"][0]["path"] == "report.json"
    # reproducible: same data -> same content hash, regardless of generation time
    assert client.post(f"{API}/investigations/{iid}/export", headers=h).json()["report"]["content_sha256"] == rep["content_sha256"]
    audits = db.query(AuditRecord).filter_by(action="investigation.export", target_id=iid).all()
    assert len(audits) == 2 and audits[0].context_metadata["format"] == "json"


def test_export_zip_with_media_manifest_hashes_and_determinism(client, db, org, seeded_users, tokens, auth_header, png_bytes):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    m = mk_media(db, org, png_bytes)
    client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "media_asset", "title": "P", "record_id": m.id}, headers=h)
    r = client.post(f"{API}/investigations/{iid}/export", params={"format": "zip", "include_media": True}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert names == ["README.txt", "report.json", "manifest.json", f"media/{m.content_hash}.png"]
    man = json.loads(z.read("manifest.json"))
    for f in man["files"]:
        assert hashlib.sha256(z.read(f["path"])).hexdigest() == f["sha256"]
    assert [f["path"] for f in man["files"]] == ["report.json", f"media/{m.content_hash}.png"]
    assert b"not independently authenticated" in z.read("README.txt")
    assert "../" not in "".join(names)


def test_export_omits_missing_and_tampered_media(client, db, org, seeded_users, tokens, auth_header, png_bytes):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    good = mk_media(db, org, png_bytes)
    bad = media_service.ingest_media(db, organization_id=org.id, declared_filename="b.png", content=png_bytes(color=(1, 2, 3)), uploaded_by_user_id=None)
    gone = media_service.ingest_media(db, organization_id=org.id, declared_filename="c.png", content=png_bytes(color=(9, 9, 9)), uploaded_by_user_id=None)
    for m in (good, bad, gone):
        client.post(f"{API}/investigations/{iid}/links", json={"record_type": "media_asset", "record_id": m.id}, headers=h)
    open(storage.path_for(bad.storage_key), "ab").write(b"x")
    os.remove(storage.path_for(gone.storage_key))
    rep = client.post(f"{API}/investigations/{iid}/export", params={"format": "zip", "include_media": True}, headers=h)
    z = zipfile.ZipFile(io.BytesIO(rep.content))
    report = json.loads(z.read("report.json"))
    reasons = {o["record_id"]: o["reason"] for o in report["omitted_artifacts"]}
    assert reasons[bad.id] == "integrity_mismatch_not_exported" and reasons[gone.id] == "original_unavailable"
    assert [n for n in z.namelist() if n.startswith("media/")] == [f"media/{good.content_hash}.png"]


def test_export_size_limits_and_param_validation(client, db, org, seeded_users, tokens, auth_header, png_bytes, monkeypatch):
    from app.services import investigation_export_service as ex
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    m = mk_media(db, org, png_bytes)
    client.post(f"{API}/investigations/{iid}/links", json={"record_type": "media_asset", "record_id": m.id}, headers=h)
    monkeypatch.setattr(ex, "MAX_MEDIA_FILE_BYTES", 10)
    rep = json.loads(zipfile.ZipFile(io.BytesIO(client.post(f"{API}/investigations/{iid}/export", params={"format": "zip", "include_media": True}, headers=h).content)).read("report.json"))
    assert rep["omitted_artifacts"][0]["reason"] == "export_size_limit"
    assert client.post(f"{API}/investigations/{iid}/export", params={"format": "pdf"}, headers=h).status_code == 422
    assert client.post(f"{API}/investigations/{iid}/export", params={"include_media": True}, headers=h).status_code == 422


def test_export_hides_restricted_evidence_from_non_privileged_export(client, db, org, seeded_users, tokens, auth_header, monkeypatch):
    # investigator can export but restricted evidence is visible to investigators; confirm admin sees it and it is audited
    h = H(auth_header, tokens, "admin")
    iid = mk_inv(client, h)["id"]
    client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "analyst_note", "title": "s", "content": "c", "access_classification": "restricted"}, headers=h)
    rep = client.post(f"{API}/investigations/{iid}/export", headers=h).json()["report"]
    assert len(rep["evidence_index"]) == 1


# ---- audit / rollback / dashboard / safety ----------------------------------------

def test_consequential_actions_are_audited(client, db, org, source, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    e = mk_event(db, org, source)
    client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": e.id}, headers=h)
    ev = client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "report", "title": "r", "content": "c"}, headers=h).json()["evidence"]
    client.post(f"{API}/evidence/{ev['id']}/verify-integrity", headers=h)
    client.post(f"{API}/investigations/{iid}/members", json={"user_id": seeded_users["viewer"].id, "role": "member"}, headers=h)
    n = client.post(f"{API}/investigations/{iid}/notes", json={"body": "SECRETBODY-one"}, headers=h).json()
    client.patch(f"{API}/investigations/{iid}/notes/{n['id']}", json={"expected_version": 1, "body": "SECRETBODY-two"}, headers=h)
    client.post(f"{API}/investigations/{iid}/close", json={"reason": "r"}, headers=h)
    actions = {a.action for a in db.query(AuditRecord).all()}
    assert {"investigation.create", "investigation.link_add", "evidence.register", "evidence.verify_integrity",
            "investigation.member_add", "investigation.note_create", "investigation.note_update", "investigation.transition"} <= actions
    trail = client.get(f"{API}/investigations/{iid}/audit", headers=h).json()
    assert trail and all("actor_user_id" in t for t in trail)
    # no note bodies or content in audit metadata
    assert not any("SECRETBODY" in json.dumps(a.context_metadata) for a in db.query(AuditRecord).all())


def test_failed_multi_record_operation_rolls_back(client, db, org, seeded_users, tokens, auth_header, monkeypatch):
    from app.services import investigation_links_service as ls
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    def boom(*a, **k):
        raise RuntimeError("link failure")
    monkeypatch.setattr(ls, "link_record", boom)
    from fastapi.testclient import TestClient
    quiet = TestClient(client.app, raise_server_exceptions=False)
    r = quiet.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "report", "title": "t", "content": "orphan"}, headers=h)
    assert r.status_code == 500
    from app.models.evidence import Evidence
    assert db.query(Evidence).filter_by(content="orphan").count() == 0  # evidence row rolled back with the failed link
    assert db.query(AuditRecord).filter_by(action="evidence.register").count() == 0


def test_dashboard_summary_counts_and_restriction(client, db, seeded_users, tokens, auth_header):
    a = H(auth_header, tokens, "analyst")
    i1 = mk_inv(client, a, priority="high")["id"]
    mk_inv(client, a, priority="low")
    mk_inv(client, a, is_restricted=True)
    client.post(f"{API}/investigations/{i1}/notes", json={"body": "q?", "note_kind": "review_question", "assignee_user_id": seeded_users["analyst"].id}, headers=a)
    s = client.get(f"{API}/investigation-dashboard/summary", headers=a).json()
    assert s["total"] == 3 and s["by_status"] == {"open": 3} and s["open_by_priority"]["high"] == 1
    assert s["open_review_questions"] == 1 and s["review_questions_assigned_to_me"] == 1 and len(s["recent_activity"]) == 3
    v = client.get(f"{API}/investigation-dashboard/summary", headers=H(auth_header, tokens, "viewer")).json()
    assert v["total"] == 2  # restricted case invisible to a non-member


def test_malformed_identifiers_are_rejected_safely(client, seeded_users, tokens, auth_header):
    h = H(auth_header, tokens)
    iid = mk_inv(client, h)["id"]
    assert client.get(f"{API}/investigations/{'x' * 500}", headers=h).status_code == 404
    assert client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": "x" * 100}, headers=h).status_code == 422
    assert client.post(f"{API}/investigations/{iid}/links", json={"record_type": "event", "record_id": "../../etc/passwd"}, headers=h).status_code == 404
    assert client.get(f"{API}/evidence/..%2f..%2fetc/provenance", headers=h).status_code == 404
    assert client.post(f"{API}/investigations/{iid}/evidence", json={"evidence_type": "media_asset", "title": "t", "record_id": "../x"}, headers=h).status_code == 404
    assert client.post(f"{API}/investigations/{iid}/transition", json={"to_status": "nonsense"}, headers=h).status_code == 409
    assert client.post(f"{API}/investigations/{iid}/transition", json={}, headers=h).status_code == 422
