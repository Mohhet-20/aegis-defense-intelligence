"""Phase 16: tenant isolation, restricted-record handling, section permissions, audit."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core import security
from app.core.security import Permission, Role
from app.models.audit import AuditRecord
from app.models.evidence import Evidence
from app.models.investigation import Investigation
from app.models.investigation_workspace import InvestigationMember
from tests.analytics_fixtures import T, WINDOW_Q, seed

BASE = "/api/v1/reporting"


@pytest.fixture()
def H(auth_header, tokens):
    return lambda role: auth_header(tokens, role)


@pytest.fixture()
def data(db, org, org_b):
    return seed(db, org, org_b)


def sec(client, H, role, name, **q):
    r = client.get(f"{BASE}/analytics/{name}", params={**WINDOW_Q, **q}, headers=H(role))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def inv_data(db, org, org_b, seeded_users):
    admin, analyst = seeded_users["admin"], seeded_users["analyst"]
    a = Investigation(organization_id=org.id, title="Open public", status="open", priority="high", created_at=T(10, 1), is_restricted=False, assigned_user_id=analyst.id)
    b = Investigation(organization_id=org.id, title="Restricted to admin", status="open", priority="low", created_at=T(10, 2), is_restricted=True, assigned_user_id=admin.id)
    c = Investigation(organization_id=org.id, title="Closed in window", status="closed", priority="low", created_at=T(10, 0), closed_at=T(12, 0), is_restricted=False)
    d = Investigation(organization_id=org.id, title="Restricted w/ analyst member", status="open", priority="low", created_at=T(11), is_restricted=True)
    o = Investigation(organization_id=org_b.id, title="Other org", status="open", priority="low", created_at=T(11))
    db.add_all([a, b, c, d, o])
    db.flush()
    db.add(InvestigationMember(organization_id=org.id, investigation_id=d.id, user_id=analyst.id, role="reviewer"))
    db.add_all([
        Evidence(organization_id=org.id, evidence_type="note", title="pub", access_classification="standard", review_status="unreviewed", created_at=T(11), integrity_hash="x", content="c"),
        Evidence(organization_id=org.id, evidence_type="note", title="secret", access_classification="restricted", review_status="unreviewed", created_at=T(11), content="c"),
        Evidence(organization_id=org_b.id, evidence_type="note", title="other", access_classification="standard", review_status="unreviewed", created_at=T(11), content="c"),
    ])
    db.commit()


def test_restricted_investigations_are_excluded_per_viewer(client, H, inv_data):
    # admin sees all 4 org investigations; analyst sees open-public, closed, and the restricted one they are a member of (not admin's)
    assert sum(r[1] for r in sec(client, H, "admin", "investigations")["tables"]["investigations_by_status"]["rows"]) == 4
    an = sec(client, H, "analyst", "investigations")
    assert sum(r[1] for r in an["tables"]["investigations_by_status"]["rows"]) == 3
    assert "Restricted to admin" not in str(an)
    assert an["values"]["investigations.created_count"]["value"] == 3 - 0  # created T10 1h, T10 0h, T11 (member-restricted)
    assert an["values"]["investigations.closed_count"]["value"] == 1
    assert an["values"]["investigations.time_to_close_p50_days"]["value"] == 2.0
    viewer = sec(client, H, "viewer", "investigations")
    assert sum(r[1] for r in viewer["tables"]["investigations_by_status"]["rows"]) == 2  # no restricted ones


def test_assignment_distribution_is_admin_only_and_unranked(client, H, inv_data):
    assert "investigations_assignment" not in sec(client, H, "analyst", "investigations")["tables"]
    t = sec(client, H, "admin", "investigations")["tables"]["investigations_assignment"]
    names = [r[0] for r in t["rows"]]
    assert names == sorted(names) and "not a ranking" in t["title"]


def test_restricted_evidence_hidden_from_viewer_but_not_analyst(client, H, inv_data):
    assert sec(client, H, "analyst", "evidence")["values"]["evidence.count"]["value"] == 2
    v = sec(client, H, "viewer", "evidence")
    assert v["values"]["evidence.count"]["value"] == 1
    assert any("Restricted evidence is excluded" in c for c in v["caveats"])
    assert v["values"]["evidence.missing_integrity_hash_rate"]["value"] == 0.0


def test_other_org_cannot_see_this_orgs_numbers(client, H, b_headers, data, inv_data):
    r = client.get(f"{BASE}/analytics/events", params=WINDOW_Q, headers=b_headers)
    assert r.status_code == 200
    assert r.json()["values"]["events.count"]["value"] == 1     # only its own single event
    inv = client.get(f"{BASE}/analytics/investigations", params=WINDOW_Q, headers=b_headers).json()
    assert sum(x[1] for x in inv["tables"]["investigations_by_status"]["rows"]) == 1


def test_unauthenticated_and_missing_permission(client, H, data):
    assert client.get(f"{BASE}/analytics/events", params=WINDOW_Q).status_code == 401
    assert client.get(f"{BASE}/dashboards/executive").status_code == 401


def test_section_without_permission_returns_no_numbers(client, H, data, monkeypatch):
    perms = set(security.ROLE_PERMISSIONS[Role.VIEWER]) - {Permission.EVENT_READ}
    monkeypatch.setitem(security.ROLE_PERMISSIONS, Role.VIEWER, perms)
    env = sec(client, H, "viewer", "events")
    assert env["status"] == "not_authorized" and env["values"] == {} and env["tables"] == {} and env["sample_counts"] == {}
    ex = client.get(f"{BASE}/dashboards/executive", params=WINDOW_Q, headers=H("viewer")).json()
    assert ex["section_status"]["events"] == "not_authorized"
    k = next(x for x in ex["kpis"] if x["metric_id"] == "events.count")
    assert k["value"] is None and k["reason"] == "not_authorized"
    assert ex["section_status"]["observations"] != "not_authorized"


def test_geo_requires_its_own_permission(client, H, data, monkeypatch):
    perms = set(security.ROLE_PERMISSIONS[Role.VIEWER]) - {Permission.GEOSPATIAL_READ}
    monkeypatch.setitem(security.ROLE_PERMISSIONS, Role.VIEWER, perms)
    assert sec(client, H, "viewer", "geo")["status"] == "not_authorized"


def test_executive_dashboard_matches_section_endpoints(client, H, data):
    ex = client.get(f"{BASE}/dashboards/executive", params=WINDOW_Q, headers=H("analyst")).json()
    for name in ("events", "observations", "ingestion"):
        solo = sec(client, H, "analyst", name)
        assert ex["sections"][name]["values"] == solo["values"]
        assert ex["sections"][name]["tables"] == solo["tables"]
    assert not any("threat" in k["label"].lower() or "risk score" in k["label"].lower() for k in ex["kpis"])
    assert len(ex["kpis"]) == 12


def test_analytics_reads_are_audited(client, H, db, data):
    sec(client, H, "analyst", "events")
    rows = db.execute(select(AuditRecord).where(AuditRecord.action == "analytics.viewed")).scalars().all()
    assert rows and rows[-1].target_id == "events" and rows[-1].context_metadata["window"]["time_basis"] == "event"


def test_errors_are_sanitised(client, H, data):
    r = client.get(f"{BASE}/analytics/events", params={"start": "not-a-date", "end": "x"}, headers=H("analyst"))
    assert r.status_code == 422
    assert "Traceback" not in r.text and "/home/" not in r.text
    r = client.get(f"{BASE}/analytics/events", params={"source_id": "<script>" * 30}, headers=H("analyst"))
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/json")


def test_metric_catalog_endpoint(client, H):
    r = client.get(f"{BASE}/metrics", headers=H("viewer")).json()
    ids = {m["id"] for m in r["metrics"]}
    assert "events.count" in ids and all(m["definition"] for m in r["metrics"])
    assert client.get(f"{BASE}/metrics", params={"section": "zzz"}, headers=H("viewer")).status_code == 404
    only = client.get(f"{BASE}/metrics", params={"section": "geo"}, headers=H("viewer")).json()["metrics"]
    assert only and all(m["section"] == "geo" for m in only)
