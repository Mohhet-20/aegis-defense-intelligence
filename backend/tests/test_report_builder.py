"""Phase 16: report generation, export hardening, storage, retention, audit."""
from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import security
from app.core.config import get_settings
from app.core.security import Permission, Role
from app.models.audit import AuditRecord
from app.models.data_source import DataSource
from app.models.report import ReportRun
from app.reporting.window import now_utc
from app.services import report_service
from tests.analytics_fixtures import EVENTS_EVENT_BASIS, WINDOW_Q, seed

BASE = "/api/v1/reporting"


@pytest.fixture()
def H(auth_header, tokens):
    return lambda role: auth_header(tokens, role)


@pytest.fixture()
def data(db, org, org_b):
    return seed(db, org, org_b)


def make(client, H, role="analyst", **over):
    body = {"template_key": "platform_activity", "format": "json", **WINDOW_Q, **over}
    return client.post(f"{BASE}/reports", json=body, headers=H(role))


def audits(db, action):
    db.expire_all()
    return db.execute(select(AuditRecord).where(AuditRecord.action == action)).scalars().all()


def test_generate_json_report_end_to_end(client, H, db, data):
    r = make(client, H, notes="Analyst view: looks routine.\n<b>bold</b>", title="Weekly check")
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["status"] == "completed" and meta["downloadable"] and meta["has_commentary"]
    assert meta["sample_summary"]["events"]["events"] == EVENTS_EVENT_BASIS
    assert meta["section_status"]["events"] == "ok" and meta["expires_at"] is not None
    assert "integrity check" in meta["integrity_note"]
    d = client.get(f"{BASE}/reports/{meta['id']}/download", headers=H("analyst"))
    assert d.status_code == 200 and d.headers["content-type"].startswith("application/json")
    assert d.headers["x-content-type-options"] == "nosniff" and "attachment" in d.headers["content-disposition"] and d.headers["cache-control"].startswith("no-store")
    import hashlib
    assert hashlib.sha256(d.content).hexdigest() == meta["content_sha256"] and len(d.content) == meta["artifact_bytes"]
    doc = d.json()
    assert doc["report"]["title"] == "Weekly check" and doc["report"]["window"]["interval"] == "start <= t < end"
    assert doc["sections"]["events"]["values"]["events.count"]["value"] == EVENTS_EVENT_BASIS
    assert doc["analyst_commentary"]["text"].startswith("Analyst view") and "not part of the automatic findings" in doc["analyst_commentary"]["note"]
    assert doc["ai_generated_text"] is None
    assert "machine" not in json.dumps(doc["analyst_commentary"]).lower() and "Generated automatically" in doc["automatic_findings_label"]
    assert "events.count" in doc["metric_definitions"]
    g, dl = audits(db, "report.generated"), audits(db, "report.downloaded")
    assert len(g) == 1 and g[0].target_id == meta["id"] and g[0].context_metadata["sha256"] == meta["content_sha256"]
    assert len(dl) == 1
    assert client.get(f"{BASE}/reports/{meta['id']}", headers=H("analyst")).json()["download_count"] == 1


def test_report_numbers_match_dashboard_sections(client, H, data):
    meta = make(client, H, template_key="ingestion_quality").json()
    doc = client.get(f"{BASE}/reports/{meta['id']}/download", headers=H("analyst")).json()
    for sid in ("ingestion", "events", "observations"):
        live = client.get(f"{BASE}/analytics/{sid}", params=WINDOW_Q, headers=H("analyst")).json()
        assert doc["sections"][sid]["values"] == live["values"] and doc["sections"][sid]["tables"] == live["tables"]


def test_csv_report_is_tidy_and_formula_safe(client, H, db, data):
    db.add(DataSource(organization_id=data and db.get(DataSource, data["A"]).organization_id, name="=HYPERLINK(\"http://evil\")", source_type="x"))
    src = db.get(DataSource, data["A"])
    src.name = "=cmd|' /C calc'!A0"
    db.commit()
    meta = make(client, H, format="csv").json()
    raw = client.get(f"{BASE}/reports/{meta['id']}/download", headers=H("analyst"))
    assert raw.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(raw.content.decode("utf-8-sig"))))
    assert rows[0] == ["section", "kind", "id", "row", "column", "value", "unit", "note"]
    cells = [c for r in rows for c in r]
    assert not any(c and c[0] in "=+-@\t\r" for c in cells if not _is_number(c))
    assert "'=cmd|' /C calc'!A0" in cells
    val = [r for r in rows if r[:3] == ["events", "value", "events.count"] and r[4] == "value"]
    assert val and val[0][5] == str(EVENTS_EVENT_BASIS)


def _is_number(c):
    try:
        float(c)
        return True
    except ValueError:
        return False


def test_html_report_escapes_everything(client, H, db, data):
    db.get(DataSource, data["A"]).name = "<script>alert(1)</script>"
    db.commit()
    meta = make(client, H, format="html", notes="<img src=x onerror=alert(2)>", title="<b>T</b>").json()
    r = client.get(f"{BASE}/reports/{meta['id']}/download", headers=H("analyst"))
    html = r.text
    assert r.headers["content-type"].startswith("text/html") and "default-src 'none'" in r.headers["content-security-policy"]
    assert "<script" not in html.lower() and "onerror=alert" not in html.replace("&lt;img src=x onerror=alert(2)&gt;", "")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "&lt;b&gt;T&lt;/b&gt;" in html
    assert "Automatic findings" in html and "Analyst commentary" in html and "Metric definitions" in html


def test_validation_rejects_bad_requests(client, H, data):
    for over in ({"template_key": "nope"}, {"format": "pdf"}, {"sections": ["events"]}, {"template_key": "custom"}, {"template_key": "custom", "sections": ["bogus"]},
                 {"days": 5}, {"notes": "x" * 4001}, {"idempotency_key": "has space"}, {"visibility": "public"}, {"unknown_field": 1}, {"title": "   "}):
        r = make(client, H, **over)
        assert r.status_code == 422, (over, r.text)
    assert make(client, H, template_key="custom", sections=["events", "geo"]).status_code == 201


def test_validate_endpoint_echoes_resolved_plan_without_creating_anything(client, H, db, data):
    r = client.post(f"{BASE}/reports/validate", json={"template_key": "sensor_coverage", "format": "csv", **WINDOW_Q}, headers=H("analyst"))
    assert r.status_code == 200 and r.json()["sections"] == ["sensors", "observations"] and "sensor:read" in r.json()["required_permissions"]
    assert db.execute(select(ReportRun)).first() is None


def test_permissions_for_generation(client, H, data, monkeypatch):
    assert make(client, H, "viewer").status_code == 403                    # viewer lacks report:generate
    perms = set(security.ROLE_PERMISSIONS[Role.ANALYST]) - {Permission.GEOSPATIAL_READ}
    monkeypatch.setitem(security.ROLE_PERMISSIONS, Role.ANALYST, perms)
    r = make(client, H, template_key="geospatial_summary")
    assert r.status_code == 403 and "lack permission" in r.json()["detail"]
    assert not any(t["available"] for t in client.get(f"{BASE}/templates", headers=H("analyst")).json()["templates"] if t["key"] == "geospatial_summary")
    assert client.post(f"{BASE}/reports", json={"template_key": "platform_activity"}).status_code == 401


def test_private_and_organization_visibility_and_tenant_isolation(client, H, b_headers, data):
    priv = make(client, H, "analyst").json()
    shared = make(client, H, "analyst", visibility="organization").json()
    for rid in (priv["id"], shared["id"]):
        assert client.get(f"{BASE}/reports/{rid}", headers=b_headers).status_code == 404       # other organization
        assert client.get(f"{BASE}/reports/{rid}/download", headers=b_headers).status_code == 404
    assert client.get(f"{BASE}/reports/{priv['id']}", headers=H("investigator")).status_code == 404   # private to its creator...
    assert client.get(f"{BASE}/reports/{priv['id']}/download", headers=H("investigator")).status_code == 404
    assert client.get(f"{BASE}/reports/{priv['id']}", headers=H("admin")).status_code == 200          # ...and administrators
    assert client.get(f"{BASE}/reports/{shared['id']}/download", headers=H("investigator")).status_code == 200
    ids = lambda role: {r["id"] for r in client.get(f"{BASE}/reports", headers=H(role)).json()["items"]}
    assert ids("analyst") == {priv["id"], shared["id"]} and ids("investigator") == {shared["id"]} and ids("admin") == {priv["id"], shared["id"]}
    assert client.get(f"{BASE}/reports", headers=b_headers).json()["items"] == []
    assert client.get(f"{BASE}/reports/not-a-real-id", headers=H("analyst")).status_code == 404
    assert client.get(f"{BASE}/reports/..%2f..%2fetc%2fpasswd/download", headers=H("analyst")).status_code == 404


def test_org_report_requires_reader_to_hold_the_data_permissions(client, H, data, monkeypatch):
    shared = make(client, H, "analyst", template_key="evidence_provenance", visibility="organization").json()
    perms = set(security.ROLE_PERMISSIONS[Role.INVESTIGATOR]) - {Permission.EVIDENCE_READ}
    monkeypatch.setitem(security.ROLE_PERMISSIONS, Role.INVESTIGATOR, perms)
    assert client.get(f"{BASE}/reports/{shared['id']}/download", headers=H("investigator")).status_code == 404
    assert shared["id"] not in {r["id"] for r in client.get(f"{BASE}/reports", headers=H("investigator")).json()["items"]}


def test_idempotency(client, H, db, data):
    a = make(client, H, idempotency_key="k-1")
    b = make(client, H, idempotency_key="k-1")
    assert a.status_code == 201 and b.status_code == 200 and b.json()["replayed"] is True and a.json()["id"] == b.json()["id"]
    assert len(db.execute(select(ReportRun)).scalars().all()) == 1
    c = make(client, H, idempotency_key="k-1", format="csv")
    assert c.status_code == 409
    assert make(client, H, "admin", idempotency_key="k-1").status_code == 409   # same key, different caller


def test_failed_generation_never_looks_complete(client, H, db, data, monkeypatch):
    from app.reporting import render

    def boom(doc):
        raise RuntimeError("secret path /var/lib/x leaked")
    monkeypatch.setitem(render.RENDERERS, "json", boom)
    r = make(client, H)
    assert r.status_code == 201
    m = r.json()
    assert m["status"] == "failed" and m["downloadable"] is False and m["artifact_name"] is None and m["content_sha256"] is None and m["expires_at"] is None
    assert m["error_category"] == "generation_failed" and "secret" not in json.dumps(m) and "/var/lib" not in json.dumps(m)
    d = client.get(f"{BASE}/reports/{m['id']}/download", headers=H("analyst"))
    assert d.status_code == 409 and "failed" in d.json()["detail"]
    root = report_service.storage_root()
    assert not list(root.rglob(f"{m['id']}*")) and not list(root.rglob(".tmp-*"))
    fa = audits(db, "report.generation_failed")
    assert len(fa) == 1 and fa[0].outcome == "failure" and not audits(db, "report.generated")


def test_oversized_artifact_fails_cleanly(client, H, data, monkeypatch):
    monkeypatch.setattr(get_settings(), "REPORT_MAX_ARTIFACT_BYTES", 200)
    m = make(client, H).json()
    assert m["status"] == "failed" and m["error_category"] == "too_large" and "size limit" in m["error_message"]


def test_expiry_and_purge(client, H, db, data):
    m = make(client, H, visibility="organization").json()
    run = db.get(ReportRun, m["id"])
    file = report_service._artifact_path(run)
    assert file.is_file()
    run.expires_at = now_utc() - timedelta(minutes=1)
    db.commit()
    d = client.get(f"{BASE}/reports/{m['id']}/download", headers=H("analyst"))
    assert d.status_code == 409 and "expired" in d.json()["detail"]
    assert not file.exists()
    assert client.get(f"{BASE}/reports/{m['id']}", headers=H("analyst")).json()["status"] == "expired"
    assert audits(db, "report.expired")
    # purge endpoint: admin only
    m2 = make(client, H).json()
    db.get(ReportRun, m2["id"]).expires_at = now_utc() - timedelta(days=1)
    db.commit()
    assert client.post(f"{BASE}/reports/purge-expired", headers=H("analyst")).status_code == 403
    assert client.post(f"{BASE}/reports/purge-expired", headers=H("admin")).json() == {"expired": 1}
    assert client.get(f"{BASE}/reports/{m2['id']}", headers=H("admin")).json()["status"] == "expired"


def test_tampered_file_is_not_served(client, H, db, data):
    m = make(client, H).json()
    run = db.get(ReportRun, m["id"])
    f = report_service._artifact_path(run)
    f.write_bytes(f.read_bytes() + b" ")
    d = client.get(f"{BASE}/reports/{m['id']}/download", headers=H("analyst"))
    assert d.status_code == 409 and "no longer matches" in d.json()["detail"]
    assert audits(db, "report.integrity_mismatch")
    f.unlink()
    assert client.get(f"{BASE}/reports/{m['id']}/download", headers=H("analyst")).status_code == 409


def test_filename_is_sanitised_and_storage_name_ignores_title(client, H, db, data):
    m = make(client, H, title='../../etc/passwd"; rm -rf /').json()
    assert "/" not in m["artifact_name"] and '"' not in m["artifact_name"] and m["artifact_name"].startswith("aegis-platform_activity-") and m["artifact_name"].endswith(".json")
    run = db.get(ReportRun, m["id"])
    f = report_service._artifact_path(run)
    assert f.name == f"{m['id']}.json" and report_service.storage_root().resolve() in f.resolve().parents
    d = client.get(f"{BASE}/reports/{m['id']}/download", headers=H("analyst"))
    assert d.headers["content-disposition"] == f'attachment; filename="{m["artifact_name"]}"'


def test_report_has_no_public_url(client, H, data):
    m = make(client, H).json()
    for path in (f"/reports/{m['id']}.json", f"/media_storage/reports/{m['id']}.json", f"/static/{m['id']}.json"):
        assert client.get(path, headers=H("analyst")).status_code == 404
    assert client.get(f"{BASE}/reports/{m['id']}/download").status_code == 401


def test_empty_window_produces_honest_report(client, H, data):
    m = make(client, H, start="2025-03-01T00:00:00Z", end="2025-03-02T00:00:00Z").json()
    doc = client.get(f"{BASE}/reports/{m['id']}/download", headers=H("analyst")).json()
    assert m["status"] == "completed" and m["section_status"]["events"] == "empty"
    assert doc["sections"]["events"]["values"]["events.count"]["value"] == 0
    assert doc["sections"]["events"]["values"]["events.missing_description_rate"]["value"] is None
    assert any("does not show that nothing happened" in t for t in doc["automatic_findings"]["events"]["text"])


def test_list_pagination_and_filters(client, H, data):
    for _ in range(3):
        make(client, H)
    make(client, H, format="csv")
    page = client.get(f"{BASE}/reports", params={"page_size": 2}, headers=H("analyst")).json()
    assert len(page["items"]) == 2 and page["total"] == 4 and page["page_size"] == 2
    assert client.get(f"{BASE}/reports", params={"page_size": 201}, headers=H("analyst")).status_code == 422
    assert client.get(f"{BASE}/reports", params={"status": "bogus"}, headers=H("analyst")).status_code == 422
    assert client.get(f"{BASE}/reports", params={"status": "completed", "template_key": "platform_activity"}, headers=H("analyst")).json()["total"] == 4


def test_templates_are_backed_by_real_sections():
    from app.reporting.templates import SECTION_PERMISSIONS, TEMPLATES
    from app.services import analytics_service as an

    for k, t in TEMPLATES.items():
        for s in t["sections"]:
            assert s in an.SECTIONS and s in SECTION_PERMISSIONS, (k, s)
