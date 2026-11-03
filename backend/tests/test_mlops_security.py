"""Phase 15 -- authentication, RBAC matrix, input hardening and migration."""
from __future__ import annotations

import os
import sqlite3

import pytest

from app.core.config import get_settings
from app.core.security import ROLE_PERMISSIONS, Permission, Role

API = "/api/v1"
NEW_PERMISSIONS = ("MLOPS_READ", "MLOPS_REGISTER", "MLOPS_RUN", "MLOPS_REVIEW", "MLOPS_MONITOR", "MLOPS_APPROVE", "OBSERVABILITY_READ")


def _paths(app):
    out = []
    for path, ops in app.openapi()["paths"].items():
        if path.startswith(f"{API}/mlops") or path.startswith(f"{API}/observability"):
            for method in ops:
                out.append((method.upper(), path))
    return sorted(out)


def test_every_mlops_and_observability_route_requires_authentication(client):
    routes = _paths(client.app)
    assert len(routes) >= 24
    for method, path in routes:
        url = path.replace("{", "x").replace("}", "")
        r = client.request(method, url)
        assert r.status_code == 401, (method, path, r.status_code)


def test_role_permission_matrix_for_prompt15():
    has = lambda role, name: getattr(Permission, name) in ROLE_PERMISSIONS[role]
    assert all(has(Role.ADMINISTRATOR, p) for p in NEW_PERMISSIONS)
    assert [p for p in NEW_PERMISSIONS if has(Role.ANALYST, p)] == ["MLOPS_READ", "MLOPS_REGISTER", "MLOPS_RUN", "MLOPS_REVIEW", "MLOPS_MONITOR"]
    for role in (Role.INVESTIGATOR, Role.VIEWER):
        assert [p for p in NEW_PERMISSIONS if has(role, p)] == ["MLOPS_READ"]
    for role in (Role.ANALYST, Role.INVESTIGATOR, Role.VIEWER):
        assert not has(role, "MLOPS_APPROVE") and not has(role, "OBSERVABILITY_READ")


@pytest.mark.parametrize("role,method,path,body,expected", [
    ("viewer", "get", "/mlops/models", None, 200),
    ("viewer", "get", "/mlops/families", None, 200),
    ("viewer", "get", "/mlops/signals", None, 200),
    ("viewer", "get", "/mlops/monitoring/coverage", None, 200),
    ("viewer", "post", "/mlops/models", {}, 403),
    ("viewer", "post", "/mlops/experiments", {}, 403),
    ("viewer", "put", "/mlops/baselines", {}, 403),
    ("viewer", "post", "/mlops/monitoring/snapshots", {}, 403),
    ("viewer", "post", "/mlops/signals/scan", None, 403),
    ("investigator", "post", "/mlops/models", {}, 403),
    ("analyst", "get", "/observability/health", None, 403),
    ("analyst", "get", "/observability/metrics", None, 403),
    ("admin", "get", "/observability/metrics", None, 200),
])
def test_role_gates_are_enforced_before_validation(client, tokens, auth_header, role, method, path, body, expected):
    r = getattr(client, method)(f"{API}{path}", headers=auth_header(tokens, role), **({"json": body} if body is not None else {}))
    assert r.status_code == expected, r.text


def test_organization_id_in_a_request_body_is_rejected_not_trusted(client, tokens, auth_header, org_b):
    a = auth_header(tokens, "analyst")
    r = client.post(f"{API}/mlops/models", headers=a, json={"name": "m", "version": "1.0.0", "task_type": "classification", "owner_organization_id": org_b.id})
    assert r.status_code == 422
    r = client.post(f"{API}/mlops/experiments", headers=a, json={"model_record_id": "x", "experiment_name": "e", "organization_id": org_b.id,
                                                                  "classification": {"dataset_name": "d", "dataset_version": "1", "is_synthetic": True, "samples": [{"true_label": "a", "predicted_label": "a"}]}})
    assert r.status_code == 422


def test_denied_attempts_are_audited_without_leaking_resource_details(client, db, tokens, auth_header):
    from sqlalchemy import select
    from app.models.audit import AuditRecord

    client.post(f"{API}/mlops/models", headers=auth_header(tokens, "viewer"), json={"name": "sneaky", "version": "1.0.0", "task_type": "classification"})
    rows = [r for r in db.execute(select(AuditRecord).where(AuditRecord.action == "authz.denied")).scalars()]
    assert rows and all("sneaky" not in str(r.context_metadata) for r in rows)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a" * 300, "'; DROP TABLE model_records;--", "<script>alert(1)</script>"])
def test_hostile_identifiers_are_handled_as_plain_data(client, tokens, auth_header, bad):
    a = auth_header(tokens, "analyst")
    for path in (f"/mlops/models/{bad}", f"/mlops/experiments/{bad}", f"/mlops/signals/{bad}", f"/mlops/monitoring/snapshots/{bad}"):
        r = client.get(f"{API}{path}", headers=a)
        assert r.status_code in (404, 422), (path, r.status_code)
    assert client.get(f"{API}/mlops/models?q={bad}", headers=a).status_code in (200, 422)


def test_error_bodies_never_echo_internals(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    r = client.post(f"{API}/mlops/models", headers=a, json={"name": "m", "version": "1.0.0", "task_type": "classification", "artifact_reference": "artifact:/etc/shadow"})
    assert r.status_code == 422 and "Traceback" not in r.text and "/home/" not in r.text
    r = client.post(f"{API}/mlops/models", headers=a, content=b"{not json", )
    assert r.status_code == 422 and "Traceback" not in r.text


def test_non_finite_numbers_in_any_mlops_body_yield_422_not_500(client, tokens, auth_header):
    h = {**auth_header(tokens, "analyst"), "Content-Type": "application/json"}
    body = '{"model_record_id":"x","experiment_name":"e","classification":{"dataset_name":"d","dataset_version":"1","is_synthetic":true,"positive_label":"a","samples":[{"true_label":"a","predicted_label":"a","positive_probability":NaN}]}}'
    r = client.post(f"{API}/mlops/experiments", headers=h, content=body)
    assert r.status_code == 422 and "NaN" not in r.text


# ---- migration ------------------------------------------------------------------------------
def _alembic(tmp_path):
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    return cfg


def test_migration_matches_orm_and_round_trips_with_legacy_data(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    import app.models  # noqa: F401  (register every table)
    from app.db.base import Base
    from app.models.mlops import ExperimentBaseline, ExperimentRun, ModelLifecycleEvent, MonitoringSnapshot, ReviewSignal

    cfg = _alembic(tmp_path)
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert heads == ["c16r3p0rt01"], heads  # Phase 16 is the head; Phase 15's revision must remain its ancestor
    assert ScriptDirectory.from_config(cfg).get_revision("c16r3p0rt01").down_revision == "b15e0ps0001"
    settings = get_settings()
    old = settings.DATABASE_URL
    path = tmp_path / "p15.db"
    settings.DATABASE_URL = f"sqlite:///{path}"
    try:
        command.upgrade(cfg, "a14c0de5ec01")
        con = sqlite3.connect(path)
        con.execute("insert into model_records(id,name,version,model_type,status,evaluation_metadata,created_at,updated_at) values('m-dep','legacy','1','heuristic','deprecated','{}','2026-01-01','2026-01-01')")
        con.execute("insert into model_records(id,name,version,model_type,status,evaluation_metadata,created_at,updated_at) values('m-ret','legacy','2','heuristic','retired','{}','2026-01-01','2026-01-01')")
        con.execute("insert into model_records(id,name,version,model_type,status,evaluation_metadata,created_at,updated_at) values('m-act','legacy','3','heuristic','active','{}','2026-01-01','2026-01-01')")
        con.commit()
        con.close()

        command.upgrade(cfg, "head")
        con = sqlite3.connect(path)
        state = dict(con.execute("select id, lifecycle_state from model_records"))
        assert state == {"m-dep": "deprecated", "m-ret": "archived", "m-act": "registered"}  # backfilled, nothing lost
        assert con.execute("select count(*) from model_records where owner_organization_id is not null").fetchone()[0] == 0
        # the migrated schema has every column the ORM declares for the new/changed tables
        for model in (ExperimentRun, ExperimentBaseline, ModelLifecycleEvent, MonitoringSnapshot, ReviewSignal):
            table = model.__table__
            cols = {r[1] for r in con.execute(f"pragma table_info({table.name})")}
            assert {c.name for c in table.columns} <= cols, (table.name, {c.name for c in table.columns} - cols)
        mr_cols = {r[1] for r in con.execute("pragma table_info(model_records)")}
        assert {c.name for c in Base.metadata.tables["model_records"].columns} <= mr_cols
        idx = {r[1] for r in con.execute("pragma index_list(model_records)")}
        assert "uq_model_records_name_version" in idx
        con.close()

        command.downgrade(cfg, "a14c0de5ec01")
        con = sqlite3.connect(path)
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        assert not ({"experiment_runs", "experiment_baselines", "model_lifecycle_events", "monitoring_snapshots", "review_signals"} & tables)
        assert "lifecycle_state" not in {r[1] for r in con.execute("pragma table_info(model_records)")}
        assert con.execute("select count(*) from model_records").fetchone()[0] == 3  # legacy rows survive the downgrade
        con.close()

        command.upgrade(cfg, "head")  # and re-applies cleanly
        con = sqlite3.connect(path)
        assert dict(con.execute("select id, lifecycle_state from model_records"))["m-ret"] == "archived"
        con.close()
    finally:
        settings.DATABASE_URL = old


def test_migration_skips_unique_index_and_warns_when_legacy_duplicates_exist(tmp_path, caplog):
    from alembic import command

    cfg = _alembic(tmp_path)
    settings = get_settings()
    old = settings.DATABASE_URL
    path = tmp_path / "dup.db"
    settings.DATABASE_URL = f"sqlite:///{path}"
    try:
        command.upgrade(cfg, "a14c0de5ec01")
        con = sqlite3.connect(path)
        for i in (1, 2):
            con.execute("insert into model_records(id,name,version,model_type,status,evaluation_metadata,created_at,updated_at) values(?,?,?,?,?,?,?,?)", (f"d{i}", "dup", "1", "heuristic", "registered", "{}", "2026-01-01", "2026-01-01"))
        con.commit()
        con.close()
        command.upgrade(cfg, "head")
        con = sqlite3.connect(path)
        assert con.execute("select count(*) from model_records").fetchone()[0] == 2  # data untouched
        assert "uq_model_records_name_version" not in {r[1] for r in con.execute("pragma index_list(model_records)")}
        con.close()
    finally:
        settings.DATABASE_URL = old
