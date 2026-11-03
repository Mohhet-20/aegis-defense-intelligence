"""Phase 14 -- audit governance, data lifecycle, configuration security,
request-size limits, upload hardening."""
from __future__ import annotations

import logging
import os
import sqlite3

import pytest
from sqlalchemy import select, text

from app.core.config import Settings, get_settings
from app.core import security_config
from app.models.audit import AuditImmutableError, AuditRecord
from app.models.evidence import Evidence
from app.models.lifecycle import LifecycleRequest
from app.models.media_asset import MediaAsset
from app.models.retrieval import CopilotConversation, CopilotMessage, RetrievalDocument
from app.models.user import User
from app.models.scenario import ScenarioRun, SyntheticDataset
from app.services import audit_service, media_service, user_service

API = "/api/v1"
PW2 = "Str0ngPassphrase-42"


def _login(client, u, p):
    r = client.post(f"{API}/auth/login", json={"username_or_email": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin2(client, db, org, seeded_users):
    user_service.create_user(db, organization_id=org.id, username="admin2", email="admin2@test.example.com",
                             display_name="A2", password=PW2, role="administrator")
    db.commit()
    return _login(client, "admin2", PW2)


# ---- audit governance ---------------------------------------------------------------

def test_audit_rows_cannot_be_updated_or_deleted_through_the_orm(db, org):
    row = audit_service.record(db, action="t.one", actor_user_id=None, organization_id=org.id)
    db.commit()
    row.action = "t.tampered"
    with pytest.raises(AuditImmutableError):
        db.flush()
    db.rollback()
    row = db.scalar(select(AuditRecord).where(AuditRecord.action == "t.one"))
    db.delete(row)
    with pytest.raises(AuditImmutableError):
        db.flush()
    db.rollback()
    assert db.scalar(select(AuditRecord).where(AuditRecord.action == "t.one")) is not None


def test_no_api_route_updates_or_deletes_audit(client):
    from app.main import app
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/v1/audit"):
            assert getattr(route, "methods", set()) <= {"GET", "HEAD"}, (path, route.methods)


def test_audit_metadata_is_redacted(db, org):
    row = audit_service.record(db, action="t.redact", actor_user_id=None, organization_id=org.id, context_metadata={
        "password": "hunter2", "nested": {"api_key": "k-123", "Authorization": "Bearer abc", "ok": 1},
        "new_password": "x", "refresh_token": "r", "items": [{"client_secret": "s"}], "long": "z" * 5000, "token_count": 7})
    m = row.context_metadata
    assert m["password"] == "[REDACTED]" and m["new_password"] == "[REDACTED]" and m["refresh_token"] == "[REDACTED]"
    assert m["nested"]["api_key"] == "[REDACTED]" and m["nested"]["Authorization"] == "[REDACTED]" and m["nested"]["ok"] == 1
    assert m["items"][0]["client_secret"] == "[REDACTED]"
    assert len(m["long"]) < 2100 and m["token_count"] == 7  # non-secret key containing 'token' is kept


def test_audit_write_failure_rolls_back_the_audited_change(client, db, seeded_users, tokens, auth_header, monkeypatch):
    """Fail-closed: when the audit row cannot be written, the business change
    in the same transaction does not persist (user create + user update)."""
    from app.api.routes import users as users_route
    h = auth_header(tokens, "admin")
    real = users_route.audit_service.record
    monkeypatch.setattr(users_route.audit_service, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit store down")))
    body = {"username": "ghostuser", "email": "ghost@test.example.com", "display_name": "G", "password": PW2, "role": "viewer"}
    with pytest.raises(RuntimeError):
        client.post(f"{API}/users", headers=h, json=body)
    db.expire_all()
    assert db.query(User).filter(User.username == "ghostuser").count() == 0
    with pytest.raises(RuntimeError):
        client.patch(f"{API}/users/{seeded_users['viewer'].id}", headers=h, json={"role": "analyst"})
    db.expire_all()
    assert db.get(User, seeded_users["viewer"].id).role == "viewer"
    monkeypatch.setattr(users_route.audit_service, "record", real)
    assert client.patch(f"{API}/users/{seeded_users['viewer'].id}", headers=h, json={"role": "analyst"}).status_code == 200


def test_sqlite_trigger_blocks_raw_sql_modification_after_migration(tmp_path):
    from alembic import command
    from alembic.config import Config
    url_path = tmp_path / "mig.db"
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    settings = get_settings()
    old = settings.DATABASE_URL
    settings.DATABASE_URL = f"sqlite:///{url_path}"
    try:
        command.upgrade(cfg, "head")
        con = sqlite3.connect(url_path)
        names = {r[0] for r in con.execute("select name from sqlite_master where type='trigger'")}
        assert {"trg_audit_records_no_update", "trg_audit_records_no_delete"} <= names
        con.execute("insert into audit_records(id,action,outcome,context_metadata,created_at,updated_at) values('a1','x','success','{}','2026-01-01','2026-01-01')")
        con.commit()
        for sql in ("delete from audit_records", "update audit_records set action='y'"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                con.execute(sql)
        con.close()
        command.downgrade(cfg, "980f1f55cbaa")
        con = sqlite3.connect(url_path)
        assert not {r[0] for r in con.execute("select name from sqlite_master where type='trigger'")}
        assert con.execute("select count(*) from audit_records").fetchone()[0] == 1  # data preserved
        cols = {r[1] for r in con.execute("pragma table_info(users)")}
        assert "token_version" not in cols
        con.close()
    finally:
        settings.DATABASE_URL = old


# ---- security configuration ------------------------------------------------------------

def _settings(**kw):
    base = dict(ENVIRONMENT="production", SECRET_KEY="x" * 48, CORS_ALLOWED_ORIGINS="https://app.example.com", DATABASE_URL="postgresql+psycopg2://u:p@h/db")
    base.update(kw)
    return Settings(**base)


def test_production_startup_blockers():
    assert security_config.startup_blockers(_settings()) == []
    assert security_config.startup_blockers(_settings(SECRET_KEY=security_config.DEFAULT_SECRET))
    assert security_config.startup_blockers(_settings(SECRET_KEY="short"))
    assert security_config.startup_blockers(_settings(CORS_ALLOWED_ORIGINS="*"))
    # development is never blocked
    assert security_config.startup_blockers(_settings(ENVIRONMENT="development", SECRET_KEY="short")) == []


def test_create_app_refuses_unsafe_production_config(monkeypatch):
    from app import main
    monkeypatch.setattr(main.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(main.settings, "SECRET_KEY", "short")
    with pytest.raises(RuntimeError, match="Refusing to start"):
        main.create_app()


def test_docs_disabled_in_production_by_default(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(main.settings, "SECRET_KEY", "k" * 48)
    monkeypatch.setattr(main.settings, "CORS_ALLOWED_ORIGINS", "https://app.example.com")
    app = main.create_app()
    c = TestClient(app)
    assert c.get("/api/docs").status_code == 404 and c.get("/api/openapi.json").status_code == 404
    monkeypatch.setattr(main.settings, "ENABLE_API_DOCS", True)
    assert TestClient(main.create_app()).get("/api/openapi.json").status_code == 200


def test_security_config_endpoint_has_no_secret_values(client, seeded_users, tokens, auth_header, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "COPILOT_API_KEY", "sk-live-SUPERSECRET-abc")
    r = client.get(f"{API}/security/config", headers=auth_header(tokens, "admin"))
    assert r.status_code == 200
    blob = r.text
    assert s.SECRET_KEY not in blob and "sk-live-SUPERSECRET-abc" not in blob and "DATABASE_URL" not in blob
    body = r.json()
    assert body["secrets_configured"]["copilot_api_key_set"] is True
    assert "multi-factor authentication" in body["not_implemented"]
    assert all({"id", "severity", "title", "recommendation"} <= set(f) for f in body["findings"])
    for role in ("analyst", "investigator", "viewer"):
        assert client.get(f"{API}/security/config", headers=auth_header(tokens, role)).status_code == 403


# ---- request limits, headers, uploads ---------------------------------------------------------

def test_oversized_json_body_is_rejected_with_413(client, seeded_users, tokens, auth_header, monkeypatch):
    monkeypatch.setattr(get_settings(), "MAX_REQUEST_BODY_BYTES", 2000)
    r = client.post(f"{API}/users", headers=auth_header(tokens, "admin"), json={"username": "u" * 5000, "email": "a@b.example.com", "display_name": "x", "password": PW2})
    assert r.status_code == 413 and "limit" in r.json()["detail"]


def test_chunked_oversized_body_is_cut_off(client, seeded_users, tokens, auth_header, monkeypatch):
    monkeypatch.setattr(get_settings(), "MAX_REQUEST_BODY_BYTES", 1000)
    def gen():
        for _ in range(10):
            yield b"a" * 500
    r = client.post(f"{API}/users", headers={**auth_header(tokens, "admin"), "content-type": "application/json"}, content=gen())
    assert r.status_code == 413


def test_security_headers_present(client):
    r = client.get(f"{API}/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"


def test_cors_is_not_wildcard_for_methods_headers(client):
    r = client.options(f"{API}/users", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "TRACE", "Access-Control-Request-Headers": "x-evil"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "TRACE" not in r.headers.get("access-control-allow-methods", "")
    assert "x-evil" not in r.headers.get("access-control-allow-headers", "").lower()
    r2 = client.options(f"{API}/users", headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r2.headers


def test_request_id_header_is_sanitized(client):
    r = client.get(f"{API}/health/live", headers={"X-Request-ID": "bad id\r\nX-Injected: 1"})
    assert r.headers["x-request-id"] != "bad id" and "\n" not in r.headers["x-request-id"]
    good = client.get(f"{API}/health/live", headers={"X-Request-ID": "trace-12345678"})
    assert good.headers["x-request-id"] == "trace-12345678"


def test_media_upload_rejects_oversized_and_non_media(client, seeded_users, tokens, auth_header, png_bytes, monkeypatch):
    h = auth_header(tokens, "analyst")
    s = get_settings()
    monkeypatch.setattr(s, "CV_MAX_IMAGE_UPLOAD_BYTES", 500)
    monkeypatch.setattr(s, "CV_MAX_VIDEO_UPLOAD_BYTES", 600)
    big = client.post(f"{API}/media", headers=h, files={"file": ("x.png", png_bytes() + b"0" * 5000, "image/png")})
    assert big.status_code in (400, 413)
    monkeypatch.undo()
    fake = client.post(f"{API}/media", headers=h, files={"file": ("evil.png", b"<?php system($_GET['c']); ?>", "image/png")})
    assert fake.status_code == 400


def test_media_upload_unsafe_filename_is_only_a_sanitized_label(client, seeded_users, tokens, auth_header, png_bytes):
    h = auth_header(tokens, "analyst")
    r = client.post(f"{API}/media", headers=h, files={"file": ("../../etc/passwd\x00.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "/" not in body["declared_filename"] and ".." not in body["declared_filename"] and "\x00" not in body["declared_filename"]
    assert "storage_key" not in body


def test_storage_blocks_path_traversal(tmp_path):
    from app.cv import storage
    for key in ("../../etc/passwd", "/etc/passwd", "org/../../x"):
        with pytest.raises(storage.PathTraversalError):
            storage.read_bytes(key)


def test_media_viewer_cannot_upload(client, seeded_users, tokens, auth_header, png_bytes):
    r = client.post(f"{API}/media", headers=auth_header(tokens, "viewer"), files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 403


def test_secrets_not_in_application_logs_on_failed_login(client, seeded_users, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post(f"{API}/auth/login", json={"username_or_email": "admin", "password": "LeakCanary-Pass-77"})
    assert "LeakCanary-Pass-77" not in caplog.text


# ---- lifecycle ------------------------------------------------------------------------------------

def _mk_scenario_run(client, h):
    sc = client.post(f"{API}/scenarios", headers=h, json={"title": "S", "template_id": "threshold_sensitivity", "params": {"n_points": 100}}).json()
    client.post(f"{API}/scenarios/{sc['id']}/ready", headers=h)
    run = client.post(f"{API}/scenarios/{sc['id']}/runs", headers=h, json={}).json()
    return sc, run


def _req(client, h, rtype, rid, action="delete", reason="routine retention cleanup"):
    return client.post(f"{API}/lifecycle/requests", headers=h, json={"resource_type": rtype, "resource_id": rid, "action": action, "reason": reason})


def test_lifecycle_policies_list_managed_and_protected_types(client, seeded_users, tokens, auth_header):
    r = client.get(f"{API}/lifecycle/policies", headers=auth_header(tokens, "admin")).json()
    by = {i["resource_type"]: i for i in r["items"]}
    assert by["media_asset"]["managed"] and by["media_asset"]["actions"] == ["delete"] and by["media_asset"]["classification"] == "sensitive_source"
    assert by["scenario"]["actions"] == ["archive"]
    for protected in ("evidence", "investigation", "assessment", "audit_record", "event", "raw_record"):
        assert by[protected]["managed"] is False and by[protected]["actions"] == []
    assert "never deleted" in r["audit_note"]
    assert client.get(f"{API}/lifecycle/policies", headers=auth_header(tokens, "analyst")).status_code == 403


@pytest.mark.parametrize("rtype", ["evidence", "investigation", "assessment", "audit_record", "event", "raw_record"])
def test_protected_types_cannot_be_deleted_or_archived(client, seeded_users, tokens, auth_header, rtype):
    r = _req(client, auth_header(tokens, "admin"), rtype, "00000000-0000-0000-0000-000000000001")
    assert r.status_code == 422 and "protected" in r.json()["detail"]


def test_scenario_cannot_be_deleted_only_archived(client, seeded_users, tokens, auth_header):
    h = auth_header(tokens, "admin")
    sc, _ = _mk_scenario_run(client, h)
    assert _req(client, h, "scenario", sc["id"], "delete").status_code == 422


def test_lifecycle_requires_separate_approver_and_executes_run_delete(client, db, seeded_users, tokens, auth_header, admin2):
    h = auth_header(tokens, "admin")
    sc, run = _mk_scenario_run(client, h)
    created = _req(client, h, "scenario_run", run["id"])
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert created.json()["status"] == "pending" and created.json()["impact"]["executable"] is True
    # cannot execute before approval
    assert client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).status_code == 409
    # requester cannot approve own request
    assert client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=h).status_code == 409
    assert db.query(AuditRecord).filter(AuditRecord.action == "lifecycle.approve", AuditRecord.outcome == "denied").count() == 1
    ok = client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=admin2)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    done = client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).json()
    assert done["status"] == "executed" and done["executed_by_user_id"]
    assert db.scalar(select(ScenarioRun).where(ScenarioRun.id == run["id"])) is None
    assert client.get(f"{API}/scenarios/{sc['id']}/runs/{run['id']}", headers=h).status_code == 404
    actions = [a.action for a in db.query(AuditRecord).order_by(AuditRecord.created_at).all() if a.action.startswith("lifecycle.")]
    assert {"lifecycle.request", "lifecycle.approve", "lifecycle.delete"} <= set(actions)
    # executing twice is refused
    assert client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).status_code == 409


def test_self_approval_allowed_when_configured_off(client, seeded_users, tokens, auth_header, monkeypatch):
    monkeypatch.setattr(get_settings(), "LIFECYCLE_REQUIRE_SEPARATE_APPROVER", False)
    h = auth_header(tokens, "admin")
    _, run = _mk_scenario_run(client, h)
    rid = _req(client, h, "scenario_run", run["id"]).json()["id"]
    assert client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=h).status_code == 200


def test_reject_and_cancel_do_not_delete(client, db, seeded_users, tokens, auth_header, admin2):
    h = auth_header(tokens, "admin")
    _, run = _mk_scenario_run(client, h)
    rid = _req(client, h, "scenario_run", run["id"]).json()["id"]
    assert client.post(f"{API}/lifecycle/requests/{rid}/reject", headers=admin2, json={"note": "keep"}).json()["status"] == "rejected"
    assert client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).status_code == 409
    assert db.scalar(select(ScenarioRun).where(ScenarioRun.id == run["id"])) is not None
    rid2 = _req(client, h, "scenario_run", run["id"]).json()["id"]
    assert client.post(f"{API}/lifecycle/requests/{rid2}/cancel", headers=h).json()["status"] == "cancelled"


def test_duplicate_open_request_is_refused(client, seeded_users, tokens, auth_header):
    h = auth_header(tokens, "admin")
    _, run = _mk_scenario_run(client, h)
    assert _req(client, h, "scenario_run", run["id"]).status_code == 201
    assert _req(client, h, "scenario_run", run["id"]).status_code == 409


def test_non_admin_roles_cannot_use_lifecycle(client, seeded_users, tokens, auth_header):
    for role in ("analyst", "investigator", "viewer"):
        h = auth_header(tokens, role)
        assert client.get(f"{API}/lifecycle/requests", headers=h).status_code == 403
        assert _req(client, h, "scenario_run", "x" * 36).status_code == 403
        assert client.post(f"{API}/lifecycle/requests/abc/approve", headers=h).status_code == 403


def test_lifecycle_requests_are_org_scoped(client, db, org, seeded_users, tokens, auth_header, admin2):
    from app.models.organization import Organization
    from app.core.security import hash_password
    from app.models.user import User
    ob = Organization(name="Org B", status="active"); db.add(ob); db.flush()
    db.add(User(organization_id=ob.id, username="badmin", email="b@b.example.com", display_name="B", password_hash=hash_password(PW2), role="administrator", is_active=True)); db.commit()
    hb = _login(client, "badmin", PW2)
    ha = auth_header(tokens, "admin")
    _, run = _mk_scenario_run(client, ha)
    assert _req(client, hb, "scenario_run", run["id"]).status_code == 404  # another org's run == missing
    rid = _req(client, ha, "scenario_run", run["id"]).json()["id"]
    assert client.get(f"{API}/lifecycle/requests/{rid}", headers=hb).status_code == 404
    assert client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=hb).status_code == 404
    assert client.get(f"{API}/lifecycle/requests", headers=hb).json()["total"] == 0


def test_media_delete_blocked_while_referenced_then_allowed_and_file_removed(client, db, org, seeded_users, tokens, auth_header, admin2, png_bytes):
    from app.cv import storage
    h = auth_header(tokens, "admin")
    asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="a.png", content=png_bytes(), uploaded_by_user_id=None)
    ev = Evidence(organization_id=org.id, evidence_type="media", title="img", content="c", media_asset_id=asset.id)
    db.add(ev); db.commit()
    blocked = _req(client, h, "media_asset", asset.id)
    assert blocked.status_code == 409 and "referenced" in str(blocked.json()["detail"])
    assert db.scalar(select(MediaAsset).where(MediaAsset.id == asset.id)) is not None
    # provenance holder is retained; once the reference is gone the delete is permitted
    ev.media_asset_id = None; db.commit()
    key = asset.storage_key
    path = storage.path_for(key)
    assert os.path.exists(path)
    rid = _req(client, h, "media_asset", asset.id).json()["id"]
    client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=admin2)
    done = client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).json()
    assert done["status"] == "executed" and done["result"]["file_removed"] is True
    assert not os.path.exists(path)
    assert client.get(f"{API}/media/{asset.id}/content", headers=h).status_code == 404


def test_file_cleanup_failure_is_reported_not_success_and_can_be_retried(client, db, org, seeded_users, tokens, auth_header, admin2, png_bytes, monkeypatch):
    from app.cv import storage
    h = auth_header(tokens, "admin")
    asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="b.png", content=png_bytes(color=(1, 2, 3)), uploaded_by_user_id=None)
    rid = _req(client, h, "media_asset", asset.id).json()["id"]
    client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=admin2)
    real = storage.delete
    monkeypatch.setattr(storage, "delete", lambda k: (_ for _ in ()).throw(OSError("disk busy")))
    res = client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).json()
    assert res["status"] == "cleanup_pending" and res["failure_reason"] and res["result"]["file_removed"] is False
    assert db.scalar(select(MediaAsset).where(MediaAsset.id == asset.id)) is None  # DB part is committed
    assert db.query(AuditRecord).filter(AuditRecord.action == "lifecycle.cleanup_failed", AuditRecord.outcome == "failure").count() == 1
    still = client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2)
    assert still.status_code == 409  # retry while still failing -> explicit conflict, not success
    monkeypatch.setattr(storage, "delete", real)
    fixed = client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).json()
    assert fixed["status"] == "executed" and fixed["failure_reason"] is None


def test_database_failure_during_execute_changes_nothing_and_reports_failed(client, db, org, seeded_users, tokens, auth_header, admin2, monkeypatch):
    from app.services import lifecycle_service
    h = auth_header(tokens, "admin")
    _, run = _mk_scenario_run(client, h)
    rid = _req(client, h, "scenario_run", run["id"]).json()["id"]
    client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=admin2)
    monkeypatch.setattr(lifecycle_service.audit_service, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")) if k.get("action") == "lifecycle.delete" and k.get("outcome", "success") == "success" else None)
    res = client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).json()
    assert res["status"] == "failed" and "database operation failed" in res["failure_reason"]
    db.expire_all()
    assert db.scalar(select(ScenarioRun).where(ScenarioRun.id == run["id"])) is not None  # rolled back


def test_dataset_delete_blocked_while_a_run_references_it(client, db, seeded_users, tokens, auth_header):
    h = auth_header(tokens, "admin")
    ds = client.post(f"{API}/synthetic-datasets", headers=h, json={"name": "d", "params": {"n_points": 20}}).json()
    _, run = _mk_scenario_run(client, h)
    row = db.get(ScenarioRun, run["id"]); row.dataset_ref = {"dataset_id": ds["id"]}; db.commit()
    r = _req(client, h, "synthetic_dataset", ds["id"])
    assert r.status_code == 409 and r.json()["detail"]["blockers"]
    row.dataset_ref = None; db.commit()
    assert _req(client, h, "synthetic_dataset", ds["id"]).status_code == 201


def test_copilot_conversation_delete_removes_messages(client, db, seeded_users, tokens, auth_header, admin2):
    h = auth_header(tokens, "admin")
    client.post(f"{API}/retrieval/index", headers=h, json={})
    ask = client.post(f"{API}/copilot/ask", headers=h, json={"task": "question", "question": "what happened"})
    assert ask.status_code == 200, ask.text
    conv = db.scalar(select(CopilotConversation))
    assert db.query(CopilotMessage).filter(CopilotMessage.conversation_id == conv.id).count() >= 1
    rid = _req(client, h, "copilot_conversation", conv.id).json()["id"]
    client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=admin2)
    done = client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).json()
    assert done["status"] == "executed" and done["result"]["messages_deleted"] >= 1
    db.expire_all()
    assert db.query(CopilotMessage).count() == 0 and db.query(CopilotConversation).count() == 0


def test_scenario_archive_invalidates_retrieval_index(client, db, seeded_users, tokens, auth_header, admin2):
    h = auth_header(tokens, "admin")
    sc, _ = _mk_scenario_run(client, h)
    client.post(f"{API}/retrieval/index", headers=h, json={})
    docs = db.query(RetrievalDocument).filter(RetrievalDocument.record_type == "scenario", RetrievalDocument.record_id == sc["id"]).all()
    rid = _req(client, h, "scenario", sc["id"], "archive").json()["id"]
    client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=admin2)
    assert client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2).json()["status"] == "executed"
    db.expire_all()
    assert client.get(f"{API}/scenarios/{sc['id']}", headers=h).json()["status"] == "archived"
    for d in db.query(RetrievalDocument).filter(RetrievalDocument.record_type == "scenario", RetrievalDocument.record_id == sc["id"]):
        assert d.status == "invalidated"
    # an archived scenario cannot be archived again
    assert _req(client, h, "scenario", sc["id"], "archive").status_code == 409


def test_preview_is_a_dry_run_and_respects_retention_windows(client, db, org, seeded_users, tokens, auth_header, monkeypatch):
    from datetime import datetime, timedelta, timezone
    h = auth_header(tokens, "admin")
    _, run = _mk_scenario_run(client, h)
    row = db.get(ScenarioRun, run["id"]); row.created_at = datetime.now(timezone.utc) - timedelta(days=400); db.commit()
    before = db.query(ScenarioRun).count()
    pv = client.get(f"{API}/lifecycle/preview?resource_type=scenario_run", headers=h).json()
    assert pv["total_eligible"] == 1 and pv["items"][0]["resource_id"] == run["id"] and pv["items"][0]["impact"]["executable"] is True
    assert db.query(ScenarioRun).count() == before and db.query(LifecycleRequest).count() == 0
    none = client.get(f"{API}/lifecycle/preview?resource_type=media_asset", headers=h).json()
    assert none["total_eligible"] == 0 and "No retention window" in none["note"]
    assert client.get(f"{API}/lifecycle/preview?resource_type=evidence", headers=h).status_code == 422
    explicit = client.get(f"{API}/lifecycle/preview?resource_type=scenario_run&older_than_days=1000", headers=h).json()
    assert explicit["total_eligible"] == 0


def test_audit_retention_is_report_only(client, db, org, seeded_users, tokens, auth_header, monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(get_settings(), "AUDIT_RETENTION_DAYS", 30)
    old = AuditRecord(action="old.event", organization_id=org.id, outcome="success", context_metadata={})
    db.add(old); db.commit()
    db.execute(text("update audit_records set created_at=:d where id=:i"), {"d": datetime.now(timezone.utc) - timedelta(days=90), "i": old.id}); db.commit()
    rep = client.get(f"{API}/lifecycle/audit-retention", headers=auth_header(tokens, "admin")).json()
    assert rep["eligible_for_external_archival"] >= 1 and "never deletes" in rep["note"]
    assert db.query(AuditRecord).filter(AuditRecord.action == "old.event").count() == 1


def test_deleted_media_not_listed_or_retrievable(client, db, org, seeded_users, tokens, auth_header, admin2, png_bytes):
    h = auth_header(tokens, "admin")
    asset = media_service.ingest_media(db, organization_id=org.id, declared_filename="c.png", content=png_bytes(color=(9, 9, 9)), uploaded_by_user_id=None)
    rid = _req(client, h, "media_asset", asset.id).json()["id"]
    client.post(f"{API}/lifecycle/requests/{rid}/approve", headers=admin2)
    client.post(f"{API}/lifecycle/requests/{rid}/execute", headers=admin2)
    assert client.get(f"{API}/media/{asset.id}", headers=h).status_code == 404
    assert asset.id not in str(client.get(f"{API}/media", headers=h).json())


def test_seed_script_refuses_to_run_in_production(monkeypatch):
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "seed.py")
    spec = importlib.util.spec_from_file_location("seed_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")
    with pytest.raises(SystemExit, match="Refusing to seed"):
        mod.main()


def test_connector_local_dev_escape_hatch_is_disabled_in_production(monkeypatch):
    from app.connectors.types import ConnectorConfigError
    from app.connectors.url_safety import validate_url
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")
    with pytest.raises(ConnectorConfigError, match="allow_local_dev"):
        validate_url("http://127.0.0.1:9/x", allow_local_dev=True)
    with pytest.raises(ConnectorConfigError):
        validate_url("http://169.254.169.254/latest/meta-data/")  # plain http + metadata IP still blocked
