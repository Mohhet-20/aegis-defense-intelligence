"""Phase 15 -- review signals: dedup, escalation, lifecycle, access."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.audit import AuditRecord
from app.models.mlops import ExperimentRun, ReviewSignal
from app.services import mlops_signal_service as sigs

API = "/api/v1/mlops"


def _raise(db, org, key="k1", severity="warning", **kw):
    s, created = sigs.raise_signal(db, organization_id=org.id, category=kw.pop("category", "metric_regression"), severity=severity, dedup_key=key, title="t", summary="s", **kw)
    db.commit()
    return s, created


def test_repeat_observation_dedups_and_updates_latest_values(db, org):
    s1, c1 = _raise(db, org, observed_value=0.5)
    s2, c2 = _raise(db, org, observed_value=0.4)
    assert c1 is True and c2 is False and s1.id == s2.id
    db.refresh(s1)
    assert s1.occurrence_count == 2 and s1.observed_value == 0.4 and s1.last_seen_at >= s1.first_seen_at
    assert len(db.execute(select(ReviewSignal)).scalars().all()) == 1


def test_severity_only_escalates(db, org):
    s, _ = _raise(db, org, severity="warning")
    _raise(db, org, severity="critical")
    _raise(db, org, severity="info")
    db.refresh(s)
    assert s.severity == "critical"


def test_distinct_keys_and_organizations_do_not_collide(db, org, org_b):
    a, _ = _raise(db, org, key="x")
    b, cb = _raise(db, org, key="y")
    other, co = sigs.raise_signal(db, organization_id=org_b.id, category="metric_regression", severity="warning", dedup_key="x", title="t", summary="s")
    db.commit()
    assert len({a.id, b.id, other.id}) == 3 and co is True


def test_unknown_category_or_severity_is_rejected(db, org):
    with pytest.raises(ValueError):
        sigs.raise_signal(db, organization_id=org.id, category="made_up", severity="warning", dedup_key="k", title="t", summary="s")
    with pytest.raises(ValueError):
        sigs.raise_signal(db, organization_id=org.id, category="data_drift", severity="apocalyptic", dedup_key="k", title="t", summary="s")


def test_resolved_signal_that_recurs_creates_a_new_episode(client, db, org, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    s, _ = _raise(db, org)
    assert client.post(f"{API}/signals/{s.id}/resolve", headers=a, json={"notes": "handled it"}).status_code == 200
    again, created = _raise(db, org)
    assert created is True and again.id != s.id
    assert client.get(f"{API}/signals", headers=a).json()["total"] == 2
    assert client.get(f"{API}/signals/{s.id}", headers=a).json()["status"] == "resolved"  # history kept, not reopened


def test_acknowledge_and_resolve_rules_and_audit(client, db, org, seeded_users, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    s, _ = _raise(db, org)
    assert client.post(f"{API}/signals/{s.id}/resolve", headers=a, json={"notes": "x"}).status_code == 422  # notes too short
    assert client.post(f"{API}/signals/{s.id}/resolve", headers=a, json={}).status_code == 422
    ok = client.post(f"{API}/signals/{s.id}/acknowledge", headers=a, json={"assignee_user_id": seeded_users["investigator"].id})
    assert ok.status_code == 200 and ok.json()["status"] == "acknowledged" and ok.json()["assigned_to_user_id"] == seeded_users["investigator"].id
    assert client.post(f"{API}/signals/{s.id}/acknowledge", headers=a, json={}).status_code == 409  # not open any more
    res = client.post(f"{API}/signals/{s.id}/resolve", headers=a, json={"notes": "reviewed, benign"})
    assert res.status_code == 200 and res.json()["resolution_notes"] == "reviewed, benign" and res.json()["resolved_by_user_id"] == seeded_users["analyst"].id
    assert client.post(f"{API}/signals/{s.id}/resolve", headers=a, json={"notes": "again please"}).status_code == 409
    actions = [r.action for r in db.execute(select(AuditRecord)).scalars()]
    assert "mlops.signal.acknowledge" in actions and "mlops.signal.resolve" in actions


def test_assignee_must_be_active_user_in_same_organization(client, db, org, org_b, tokens, auth_header):
    from app.core.security import hash_password
    from app.models.user import User

    a = auth_header(tokens, "analyst")
    foreign = User(organization_id=org_b.id, username="fx", email="fx@b.example.com", display_name="F", password_hash=hash_password("TestPassword123!"), role="analyst", is_active=True)
    inactive = User(organization_id=org.id, username="ix", email="ix@a.example.com", display_name="I", password_hash=hash_password("TestPassword123!"), role="analyst", is_active=False)
    db.add_all([foreign, inactive])
    db.commit()
    s, _ = _raise(db, org)
    for uid in (foreign.id, inactive.id, "no-such-user"):
        assert client.post(f"{API}/signals/{s.id}/acknowledge", headers=a, json={"assignee_user_id": uid}).status_code == 422
    assert client.get(f"{API}/signals/{s.id}", headers=a).json()["status"] == "open"


def test_viewer_can_read_but_not_act_and_cross_org_is_404(client, db, org, tokens, auth_header, b_headers):
    s, _ = _raise(db, org)
    v = auth_header(tokens, "viewer")
    assert client.get(f"{API}/signals", headers=v).status_code == 200
    assert client.get(f"{API}/signals/{s.id}", headers=v).status_code == 200
    assert client.post(f"{API}/signals/{s.id}/acknowledge", headers=v, json={}).status_code == 403
    assert client.post(f"{API}/signals/{s.id}/resolve", headers=v, json={"notes": "nope nope"}).status_code == 403
    for path, body in ((f"/signals/{s.id}", None), (f"/signals/{s.id}/acknowledge", {}), (f"/signals/{s.id}/resolve", {"notes": "not mine"})):
        r = client.get(f"{API}{path}", headers=b_headers) if body is None else client.post(f"{API}{path}", headers=b_headers, json=body)
        assert r.status_code == 404
    assert client.get(f"{API}/signals", headers=b_headers).json()["total"] == 0


def test_filters_pagination_and_counts(client, db, org, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    _raise(db, org, key="1", severity="info", category="data_drift")
    _raise(db, org, key="2", severity="serious", category="metric_regression")
    s3, _ = _raise(db, org, key="3", severity="warning", category="insufficient_data")
    client.post(f"{API}/signals/{s3.id}/resolve", headers=a, json={"notes": "done and dusted"})
    body = client.get(f"{API}/signals?page_size=2", headers=a).json()
    assert body["total"] == 3 and len(body["items"]) == 2 and body["counts"]["by_status"]["open"] == 2 and body["counts"]["unresolved_by_severity"]["serious"] == 1
    assert [s["category"] for s in client.get(f"{API}/signals?status=resolved", headers=a).json()["items"]] == ["insufficient_data"]
    assert client.get(f"{API}/signals?severity=serious", headers=a).json()["total"] == 1
    assert client.get(f"{API}/signals?category=data_drift", headers=a).json()["total"] == 1
    for bad in ("page_size=201", "status=bogus", "severity=extreme", "page=0"):
        assert client.get(f"{API}/signals?{bad}", headers=a).status_code == 422
    # most severe first among open items
    assert client.get(f"{API}/signals?status=open", headers=a).json()["items"][0]["severity"] == "serious"


def test_signal_payload_is_advisory_and_bounded(client, db, org, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    big = {f"k{i}": "x" * 500 for i in range(200)}
    s, _ = _raise(db, org, evidence=big)
    out = client.get(f"{API}/signals/{s.id}", headers=a).json()
    assert "not evidence of a real-world condition" in out["advisory_notice"]
    assert len(str(out["evidence"])) < get_settings().MLOPS_MAX_METADATA_BYTES * 2


def test_staleness_scan_flags_old_evaluations_once(client, db, org, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    mid = client.post(f"{API}/models", headers=a, json={"name": "st", "version": "1.0.0", "task_type": "classification"}).json()["id"]
    r = client.post(f"{API}/experiments", headers=a, json={"model_record_id": mid, "experiment_name": "e", "classification": {"dataset_name": "d", "dataset_version": "1", "is_synthetic": False, "samples": clf_samples()}}).json()
    first = client.post(f"{API}/signals/scan", headers=a).json()
    assert first["staleness"]["signals_created"] == 0
    row = db.get(ExperimentRun, r["id"])
    row.started_at = row.completed_at = datetime.now(timezone.utc) - timedelta(days=get_settings().MLOPS_EVALUATION_STALE_DAYS + 5)
    db.commit()
    client.post(f"{API}/signals/scan", headers=a)
    client.post(f"{API}/signals/scan", headers=a)
    stale = client.get(f"{API}/signals?category=evaluation_stale", headers=a).json()["items"]
    assert len(stale) == 1 and stale[0]["occurrence_count"] >= 2 and stale[0]["model_record_id"] == mid
