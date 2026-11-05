"""Model registry: validation, immutability, lifecycle governance,
organization visibility, derived evaluation status, artifact verification."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.audit import AuditRecord
from app.models.mlops import ExperimentRun, ModelLifecycleEvent, ReviewSignal
from app.models.model_record import ModelImmutableError, ModelRecord

API = "/api/v1/mlops"


def _det(client, headers, version="1.0.0", name="person-detector", **extra):
    body = {"name": name, "version": version, "task_type": "object_detection", "adapter_key": "mock_detector_v1", "supported_media_types": ["image"], **extra}
    return client.post(f"{API}/models", headers=headers, json=body)


def _clf(client, headers, version="1.0.0", name="text-clf", **extra):
    return client.post(f"{API}/models", headers=headers, json={"name": name, "version": version, "task_type": "classification", **extra})


def _eval(client, headers, model_id, key=None, wrong=0, samples=None):
    s = samples or ([{"true_label": "a", "predicted_label": "a"}] * 30 + [{"true_label": "b", "predicted_label": "b"}] * 30)
    body = {"model_record_id": model_id, "experiment_name": "e", "classification": {"dataset_name": "d", "dataset_version": "1", "is_synthetic": False, "samples": s}}
    if key:
        body["idempotency_key"] = key
    return client.post(f"{API}/experiments", headers=headers, json=body)


# ---- registration validation -------------------------------------------------------
def test_register_detection_version_records_owner_creator_and_event(client, db, org, seeded_users, tokens, auth_header):
    r = _det(client, auth_header(tokens, "analyst"), release_notes="first", input_schema_version="img-1", framework_metadata={"runtime": "cpu"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["scope"] == "organization" and body["lifecycle_state"] == "registered" and body["legacy_status"] == "registered"
    assert body["artifact_reference"] == "adapter:mock_detector_v1" and body["artifact"]["available"] is True
    row = db.get(ModelRecord, body["id"])
    assert row.owner_organization_id == org.id and row.created_by_user_id == seeded_users["analyst"].id
    ev = db.execute(select(ModelLifecycleEvent).where(ModelLifecycleEvent.model_record_id == row.id)).scalars().all()
    assert [e.action for e in ev] == ["register"]


@pytest.mark.parametrize("patch,why", [
    ({"version": "v1"}, "non-semver version"),
    ({"version": "1.0"}, "two-part version"),
    ({"name": "bad/name"}, "slash in name"),
    ({"name": ""}, "empty name"),
    ({"adapter_key": "nope"}, "unregistered adapter"),
    ({"adapter_key": None}, "detection needs an adapter"),
    ({"artifact_reference": "https://evil.example.com/model.bin"}, "URL reference"),
    ({"artifact_reference": "artifact:../../etc/passwd"}, "path traversal"),
    ({"artifact_reference": "artifact:/etc/passwd"}, "absolute path"),
    ({"artifact_reference": "artifact:a//b"}, "empty segment"),
    ({"artifact_reference": "adapter:other_adapter"}, "reference not matching adapter"),
    ({"artifact_digest": "abc"}, "malformed digest"),
    ({"artifact_digest": "a" * 64}, "digest with adapter reference"),
    ({"input_schema_version": "bad version!"}, "bad schema version"),
    ({"supported_media_types": ["audio"]}, "bad media type"),
    ({"unknown_field": 1}, "unknown field"),
])
def test_register_rejects_invalid_input(client, tokens, auth_header, patch, why):
    body = {"name": "n", "version": "1.0.0", "task_type": "object_detection", "adapter_key": "mock_detector_v1", **patch}
    body = {k: v for k, v in body.items() if v is not None}
    r = client.post(f"{API}/models", headers=auth_header(tokens, "analyst"), json=body)
    assert r.status_code == 422, (why, r.text)


def test_register_rejects_non_finite_and_oversized_metadata(client, tokens, auth_header):
    h = {**auth_header(tokens, "analyst"), "Content-Type": "application/json"}
    nan = '{"name":"m","version":"1.0.0","task_type":"classification","framework_metadata":{"x":NaN}}'
    assert client.post(f"{API}/models", headers=h, content=nan).status_code == 422
    big = {"name": "m", "version": "1.0.0", "task_type": "classification", "framework_metadata": {"blob": "x" * (get_settings().MLOPS_MAX_METADATA_BYTES + 10)}}
    r = client.post(f"{API}/models", headers=auth_header(tokens, "analyst"), json=big)
    assert r.status_code == 422 and "too large" in r.json()["detail"]
    deep = {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}
    assert client.post(f"{API}/models", headers=auth_header(tokens, "analyst"), json={"name": "m", "version": "1.0.0", "task_type": "classification", "framework_metadata": deep}).status_code == 422


def test_duplicate_name_version_rejected_even_across_organizations(client, tokens, auth_header, b_headers):
    assert _clf(client, auth_header(tokens, "analyst")).status_code == 201
    r = _clf(client, auth_header(tokens, "analyst"))
    assert r.status_code == 409 and r.json()["error_category"] == "validation"
    other = _clf(client, b_headers)  # same name+version in another org: the registry namespace is global
    assert other.status_code == 409
    assert "organization" not in json.dumps(other.json()).lower().replace("registered versions are immutable", "")


def test_viewer_and_investigator_cannot_register_and_denial_is_audited(client, db, tokens, auth_header):
    for role in ("viewer", "investigator"):
        assert _clf(client, auth_header(tokens, role)).status_code == 403
    assert client.post(f"{API}/models", json={}).status_code == 401
    denied = db.execute(select(AuditRecord).where(AuditRecord.action == "authz.denied")).scalars().all()
    assert any(d.context_metadata["permission"] == "mlops:register" for d in denied)


# ---- immutability -----------------------------------------------------------------
def test_registered_version_identity_fields_are_immutable(client, db, tokens, auth_header):
    mid = _det(client, auth_header(tokens, "analyst"), release_notes="orig").json()["id"]
    row = db.get(ModelRecord, mid)
    for column, value in (("artifact_reference", "adapter:other"), ("name", "renamed"), ("version", "9.9.9"), ("adapter_key", "other"), ("artifact_digest", "f" * 64), ("release_notes", "rewritten")):
        setattr(row, column, value)
        with pytest.raises(ModelImmutableError):
            db.commit()
        db.rollback()
        row = db.get(ModelRecord, mid)
    row.evaluation_metadata = {"note": 1}  # governance/descriptive columns may change
    db.commit()


def test_legacy_platform_rows_keep_prompt4_behaviour(db):
    legacy = ModelRecord(name="legacy", version="v0", model_type="heuristic", status="registered")
    db.add(legacy)
    db.commit()
    legacy.artifact_reference = "anything"
    db.commit()  # owner is NULL: not guarded (documented limitation)
    assert db.get(ModelRecord, legacy.id).lifecycle_state == "registered"


# ---- visibility / tenancy ------------------------------------------------------------
def test_other_organization_cannot_see_or_touch_a_registered_version(client, tokens, auth_header, b_headers):
    mid = _clf(client, auth_header(tokens, "analyst")).json()["id"]
    assert client.get(f"{API}/models/{mid}", headers=b_headers).status_code == 404
    assert client.get(f"{API}/models/{mid}/history", headers=b_headers).status_code == 404
    assert client.post(f"{API}/models/{mid}/transition", headers=b_headers, json={"action": "deprecate", "reason": "not mine"}).status_code == 404
    assert client.post(f"{API}/models/{mid}/verify-artifact", headers=b_headers).status_code == 404
    assert _eval(client, b_headers, mid).status_code == 404
    assert client.get(f"{API}/models/does-not-exist", headers=b_headers).status_code == 404
    assert mid not in [m["id"] for m in client.get(f"{API}/models", headers=b_headers).json()["items"]]
    fams = client.get(f"{API}/families", headers=b_headers).json()
    assert fams["total"] == 0


def test_foreign_owned_detection_model_is_hidden_from_legacy_cv_endpoints_and_inference(client, tokens, auth_header, b_headers, png_bytes):
    mid = _det(client, auth_header(tokens, "analyst")).json()["id"]
    assert client.get(f"/api/v1/cv/models/{mid}", headers=auth_header(tokens, "analyst")).status_code == 200
    assert client.get(f"/api/v1/cv/models/{mid}", headers=b_headers).status_code == 404
    assert mid not in [m["id"] for m in client.get("/api/v1/cv/models", headers=b_headers).json()["items"]]
    media = client.post("/api/v1/media", headers=b_headers, files={"file": ("x.png", png_bytes(), "image/png")}).json()
    r = client.post("/api/v1/inference/jobs", headers=b_headers, json={"media_asset_id": media["id"], "model_record_id": mid, "job_type": "image_detection"})
    assert r.status_code in (400, 404, 422), r.text
    r = client.post("/api/v1/model-evaluations", headers=b_headers, json={"model_record_id": mid, "dataset_name": "d", "dataset_version": "1", "is_synthetic": True,
                                                                          "samples": [{"true_label": "a", "predicted_label": "a"}]})
    assert r.status_code == 404


def test_platform_level_rows_remain_visible_to_every_organization(client, db, tokens, auth_header, b_headers):
    legacy = ModelRecord(name="platform-model", version="v1", model_type="heuristic", status="registered")
    db.add(legacy)
    db.commit()
    for h in (auth_header(tokens, "analyst"), b_headers):
        d = client.get(f"{API}/models/{legacy.id}", headers=h).json()
        assert d["scope"] == "platform" and d["artifact"]["available"] is False


# ---- lifecycle ---------------------------------------------------------------------
def test_transition_rules_reason_permissions_and_state_machine(client, db, tokens, auth_header):
    analyst, admin = auth_header(tokens, "analyst"), auth_header(tokens, "admin")
    mid = _clf(client, analyst).json()["id"]
    t = lambda h, action, reason="valid reason": client.post(f"{API}/models/{mid}/transition", headers=h, json={"action": action, "reason": reason})
    assert t(analyst, "request_review").status_code == 200  # review authority only
    assert t(analyst, "approve").status_code == 403  # analyst lacks mlops:approve
    assert t(analyst, "deprecate").status_code == 403
    assert t(auth_header(tokens, "viewer"), "request_review").status_code == 403
    assert t(admin, "reject_review", "no").status_code == 422  # reason too short
    assert t(admin, "archive").status_code == 409  # not allowed from review_required
    assert t(admin, "reactivate").status_code == 409
    assert t(admin, "reject_review").status_code == 200
    assert client.get(f"{API}/models/{mid}", headers=admin).json()["lifecycle_state"] == "registered"
    denied = db.execute(select(AuditRecord).where(AuditRecord.action == "authz.denied")).scalars().all()
    assert {d.context_metadata["permission"] for d in denied} >= {"mlops:approve"}
    assert client.post(f"{API}/models/{mid}/transition", headers=admin, json={"action": "explode", "reason": "valid reason"}).status_code == 422


def test_approval_requires_fresh_evaluation_separate_approver_and_no_open_serious_signal(client, db, tokens, auth_header):
    analyst, admin = auth_header(tokens, "analyst"), auth_header(tokens, "admin")
    mid = _clf(client, analyst).json()["id"]
    appr = lambda h: client.post(f"{API}/models/{mid}/transition", headers=h, json={"action": "approve", "reason": "approval attempt"})
    r = appr(admin)
    assert r.status_code == 409 and "evaluation" in r.json()["detail"]  # no evidence

    assert _eval(client, analyst, mid).json()["status"] == "succeeded"
    # registrant == approver is refused (separation of duties): give the analyst approval authority temporarily
    from app.core.security import ROLE_PERMISSIONS, Permission, Role
    ROLE_PERMISSIONS[Role.ANALYST].add(Permission.MLOPS_APPROVE)
    try:
        r = appr(analyst)
        assert r.status_code == 409 and "cannot also approve" in r.json()["detail"]
    finally:
        ROLE_PERMISSIONS[Role.ANALYST].discard(Permission.MLOPS_APPROVE)

    # stale evidence
    run = db.execute(select(ExperimentRun)).scalars().first()
    run.completed_at = datetime.now(timezone.utc) - timedelta(days=get_settings().MLOPS_APPROVAL_MAX_EVAL_AGE_DAYS + 5)
    db.commit()
    r = appr(admin)
    assert r.status_code == 409 and "older than" in r.json()["detail"]
    run.completed_at = datetime.now(timezone.utc)
    db.commit()

    # open serious signal blocks approval until it is resolved
    from app.services import mlops_signal_service as sigs
    s, _ = sigs.raise_signal(db, organization_id=run.organization_id, category="metric_regression", severity="serious", dedup_key="k", title="t", summary="s", model_record_id=mid)
    db.commit()
    r = appr(admin)
    assert r.status_code == 409 and "serious" in r.json()["detail"]
    assert client.post(f"{API}/signals/{s.id}/resolve", headers=analyst, json={"notes": "reviewed and accepted"}).status_code == 200
    ok = appr(admin)
    assert ok.status_code == 200 and ok.json()["lifecycle_state"] == "approved"


def test_metrics_alone_never_approve_a_version(client, tokens, auth_header):
    analyst = auth_header(tokens, "analyst")
    mid = _clf(client, analyst).json()["id"]
    assert _eval(client, analyst, mid).json()["metrics"]["accuracy"]["value"] == 1.0
    assert client.get(f"{API}/models/{mid}", headers=analyst).json()["lifecycle_state"] == "registered"


def test_deprecation_preserves_history_blocks_new_inference_and_reactivation_is_explicit(client, db, tokens, auth_header, png_bytes):
    analyst, admin = auth_header(tokens, "analyst"), auth_header(tokens, "admin")
    mid = _det(client, analyst).json()["id"]
    run = client.post(f"{API}/experiments", headers=analyst, json={"model_record_id": mid, "experiment_name": "det", "detection": {"sample_count": 5}}).json()
    assert run["status"] == "succeeded"
    media = client.post("/api/v1/media", headers=analyst, files={"file": ("x.png", png_bytes(), "image/png")}).json()
    job = lambda: client.post("/api/v1/inference/jobs", headers=analyst, json={"media_asset_id": media["id"], "model_record_id": mid, "job_type": "image_detection"})
    assert job().status_code in (200, 201)

    d = client.post(f"{API}/models/{mid}/transition", headers=admin, json={"action": "deprecate", "reason": "superseded by 2.0.0"})
    assert d.status_code == 200 and d.json()["lifecycle_state"] == "deprecated" and d.json()["legacy_status"] == "deprecated"
    assert job().status_code in (400, 422)  # legacy gate: new inference refused
    # history and results survive
    assert client.get(f"{API}/experiments/{run['id']}", headers=analyst).json()["metrics"] is not None
    assert [e["action"] for e in client.get(f"{API}/models/{mid}/history", headers=analyst).json()["items"]] == ["deprecate", "register"]
    assert db.execute(select(ExperimentRun)).scalars().all()
    # reactivation is an explicit, evidenced, audited operation
    assert client.post(f"{API}/models/{mid}/transition", headers=admin, json={"action": "reactivate", "reason": "re-validated"}).status_code == 200
    assert client.get(f"{API}/models/{mid}", headers=analyst).json()["legacy_status"] == "active"
    actions = [a.action for a in db.execute(select(AuditRecord)).scalars()]
    assert "mlops.model.deprecate" in actions and "mlops.model.reactivate" in actions


def test_archived_is_terminal_and_cannot_be_evaluated(client, tokens, auth_header):
    analyst, admin = auth_header(tokens, "analyst"), auth_header(tokens, "admin")
    mid = _clf(client, analyst).json()["id"]
    for action in ("deprecate", "archive"):
        assert client.post(f"{API}/models/{mid}/transition", headers=admin, json={"action": action, "reason": "retiring this"}).status_code == 200
    assert client.post(f"{API}/models/{mid}/transition", headers=admin, json={"action": "reactivate", "reason": "try again"}).status_code == 409
    assert _eval(client, analyst, mid).status_code == 409


def test_history_hides_other_organizations_actor_identity(client, db, org_b, tokens, auth_header):
    legacy = ModelRecord(name="platform-x", version="v1", model_type="heuristic", status="registered")
    db.add(legacy)
    db.commit()
    assert client.post(f"{API}/models/{legacy.id}/transition", headers=auth_header(tokens, "admin"), json={"action": "request_review", "reason": "platform review"}).status_code == 200
    from app.core.security import hash_password
    from app.models.user import User
    db.add(User(organization_id=org_b.id, username="banalyst", email="ba@b.example.com", display_name="BA", password_hash=hash_password("TestPassword123!"), role="analyst", is_active=True))
    db.commit()
    tok = client.post("/api/v1/auth/login", json={"username_or_email": "banalyst", "password": "TestPassword123!"}).json()["access_token"]
    ev = client.get(f"{API}/models/{legacy.id}/history", headers={"Authorization": f"Bearer {tok}"}).json()["items"][0]
    assert ev["actor_user_id"] is None and ev["actor_scope"] == "other_organization" and ev["evidence"] == {}
    own = client.get(f"{API}/models/{legacy.id}/history", headers=auth_header(tokens, "admin")).json()["items"][0]
    assert own["actor_user_id"] and own["actor_scope"] == "your_organization"


def test_lifecycle_events_are_append_only(db, client, tokens, auth_header):
    mid = _clf(client, auth_header(tokens, "analyst")).json()["id"]
    ev = db.execute(select(ModelLifecycleEvent).where(ModelLifecycleEvent.model_record_id == mid)).scalars().first()
    from app.models.mlops import AppendOnlyError
    ev.reason = "tampered"
    with pytest.raises(AppendOnlyError):
        db.commit()
    db.rollback()
    db.delete(db.get(ModelLifecycleEvent, ev.id))
    with pytest.raises(AppendOnlyError):
        db.commit()


# ---- listing / families / derived evaluation status ------------------------------------
def test_listing_filters_sorting_pagination_and_families(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    for v in ("1.0.0", "1.1.0", "2.0.0"):
        assert _clf(client, a, version=v, name="alpha").status_code == 201
    assert _det(client, a, version="1.0.0", name="beta").status_code == 201
    lst = client.get(f"{API}/models?page_size=2&sort=version&order=asc", headers=a).json()
    assert lst["total"] == 4 and len(lst["items"]) == 2
    assert [m["name"] for m in client.get(f"{API}/models?task=object_detection", headers=a).json()["items"]] == ["beta"]
    assert client.get(f"{API}/models?q=alph&family=alpha", headers=a).json()["total"] == 3
    assert client.get(f"{API}/models?page_size=500", headers=a).status_code == 422
    assert client.get(f"{API}/models?sort=password", headers=a).status_code == 422
    fams = {f["name"]: f for f in client.get(f"{API}/families", headers=a).json()["items"]}
    assert fams["alpha"]["version_count"] == 3 and fams["alpha"]["latest_version"] and fams["beta"]["task_types"] == ["object_detection"]


def test_evaluation_status_is_derived_not_stored(client, db, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _clf(client, a).json()["id"]
    status = lambda: client.get(f"{API}/models/{mid}", headers=a).json()["evaluation"]
    assert status()["status"] == "none"
    run = _eval(client, a, mid).json()
    assert status()["status"] == "passed" and status()["metrics"]["accuracy"] == 1.0
    row = db.get(ExperimentRun, run["id"])
    row.started_at = row.completed_at = datetime.now(timezone.utc) - timedelta(days=get_settings().MLOPS_EVALUATION_STALE_DAYS + 3)
    db.commit()
    assert status()["status"] == "stale"
    bad = _eval(client, a, mid, samples=[{"true_label": "a", "predicted_label": "a"}] * 3)  # valid, newest
    assert bad.json()["status"] == "succeeded" and status()["status"] == "passed"


# ---- artifact verification ------------------------------------------------------------
def test_verify_artifact_detects_digest_mismatch_and_raises_signal(client, db, tokens, auth_header, monkeypatch, tmp_path):
    a = auth_header(tokens, "analyst")
    root = tmp_path / "store"
    (root / "sub").mkdir(parents=True)
    f = root / "sub" / "w.bin"
    f.write_bytes(b"original")
    monkeypatch.setattr(get_settings(), "MLOPS_ARTIFACT_ROOT", str(root))
    m = _clf(client, a, artifact_reference="artifact:sub/w.bin").json()
    ok = client.post(f"{API}/models/{m['id']}/verify-artifact", headers=a).json()
    assert ok["available"] is True and ok["digest_checked"] is True and ok["digest_match"] is True and ok["review_signal_id"] is None
    f.write_bytes(b"tampered")
    bad = client.post(f"{API}/models/{m['id']}/verify-artifact", headers=a).json()
    assert bad["available"] is False and bad["digest_match"] is False and bad["review_signal_id"]
    sig = db.get(ReviewSignal, bad["review_signal_id"])
    assert sig.category == "artifact_unavailable" and sig.severity == "serious"
    again = client.post(f"{API}/models/{m['id']}/verify-artifact", headers=a).json()
    assert again["review_signal_id"] == bad["review_signal_id"]  # deduplicated


def test_symlink_escape_is_not_followed(client, tokens, auth_header, monkeypatch, tmp_path):
    a = auth_header(tokens, "analyst")
    root, outside = tmp_path / "store", tmp_path / "outside.bin"
    root.mkdir()
    outside.write_bytes(b"secret")
    (root / "link.bin").symlink_to(outside)
    monkeypatch.setattr(get_settings(), "MLOPS_ARTIFACT_ROOT", str(root))
    m = _clf(client, a, artifact_reference="artifact:link.bin")
    assert m.status_code == 201 and m.json()["artifact"]["available"] is False and m.json()["artifact_digest"] is None


def test_file_reference_without_configured_root_is_unavailable_not_an_error(client, tokens, auth_header):
    m = _clf(client, auth_header(tokens, "analyst"), artifact_reference="artifact:model.bin").json()
    assert m["artifact"]["available"] is False and "not configured" in m["artifact"]["reason"]
