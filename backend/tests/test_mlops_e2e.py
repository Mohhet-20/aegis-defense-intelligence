"""End-to-end workflow: register -> evaluate -> metrics + reproducibility
-> baseline comparison -> threshold breach signal -> acknowledge -> resolve (audited)
-> approve. Plus the unavailable-artifact failure scenario."""
from __future__ import annotations

from sqlalchemy import select

from app.models.audit import AuditRecord

API = "/api/v1/mlops"


def _clf_model(client, headers, version="1.0.0", name="threat-text-classifier"):
    r = client.post(f"{API}/models", headers=headers, json={"name": name, "version": version, "task_type": "classification",
                                                            "release_notes": "synthetic test model", "framework_metadata": {"framework": "none"}})
    assert r.status_code == 201, r.text
    return r.json()


def _run(client, headers, model_id, samples, key, name="eval", positive="pos"):
    return client.post(f"{API}/experiments", headers=headers, json={
        "model_record_id": model_id, "experiment_name": name, "idempotency_key": key,
        "classification": {"dataset_name": "synthetic-binary", "dataset_version": "1", "is_synthetic": True, "positive_label": positive, "samples": samples}})


def test_full_workflow_register_evaluate_compare_signal_resolve_approve(client, db, tokens, auth_header, clf_samples):
    analyst, admin = auth_header(tokens, "analyst"), auth_header(tokens, "admin")
    v1 = _clf_model(client, analyst, "1.0.0")
    v2 = _clf_model(client, analyst, "1.1.0")
    assert v1["lifecycle_state"] == "registered" and v1["evaluation"]["status"] == "none"

    good = _run(client, analyst, v1["id"], clf_samples(wrong=0), "baseline-run-0001")
    assert good.status_code == 201, good.text
    g = good.json()
    assert g["status"] == "succeeded" and g["metrics"]["accuracy"]["value"] == 1.0
    assert g["metrics"]["accuracy"]["ci95"] is not None and g["metrics"]["macro_f1"]["ci95"] is None  # CI only where justified
    repro = g["reproducibility"]
    assert repro["python_version"] and repro["metric_implementation_version"] and g["config_fingerprint"] and g["dataset_fingerprint"]

    # baseline selection is explicit and audited
    b = client.put(f"{API}/baselines", headers=analyst, json={"run_id": g["id"], "reason": "reference run"})
    assert b.status_code == 200, b.text

    bad = _run(client, analyst, v2["id"], clf_samples(wrong=12), "candidate-run-0001")
    assert bad.status_code == 201, bad.text
    r = bad.json()
    assert r["metrics"]["recall"]["value"] < g["metrics"]["recall"]["value"]

    cmp_ = client.get(f"{API}/experiments/{r['id']}/comparison", headers=analyst).json()
    assert cmp_["status"] == "compared" and cmp_["summary"]["review_recommended"] is True
    recall = next(m for m in cmp_["metrics"] if m["metric"] == "recall")
    assert recall["change"] == "regressed" and recall["exceeds_review_threshold"] is True
    assert recall["absolute_difference"] < 0 and recall["relative_difference"] < 0
    assert "overall" in cmp_["summary"]["statement"].lower() and "better" not in cmp_["summary"]["statement"].lower()

    # a metric_regression review signal was created for the candidate model version
    sigs = client.get(f"{API}/signals?category=metric_regression", headers=analyst).json()
    assert sigs["total"] >= 1
    s = sigs["items"][0]
    assert s["model_record_id"] == v2["id"] and s["status"] == "open" and s["threshold_value"] is not None
    assert "not evidence of a real-world condition" in s["advisory_notice"]

    ack = client.post(f"{API}/signals/{s['id']}/acknowledge", headers=analyst, json={})
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"
    res = client.post(f"{API}/signals/{s['id']}/resolve", headers=analyst, json={"notes": "Reviewed: sample set skewed; re-run planned"})
    assert res.status_code == 200 and res.json()["status"] == "resolved"

    actions = [a.action for a in db.execute(select(AuditRecord).order_by(AuditRecord.created_at)).scalars()]
    for expected in ("mlops.model.register", "mlops.experiment.run", "mlops.baseline.select", "mlops.signal.raised", "mlops.signal.acknowledge", "mlops.signal.resolve"):
        assert expected in actions, expected

    # approval: v1 has fresh evidence; registrant (analyst) is not the approver (admin)
    ap = client.post(f"{API}/models/{v1['id']}/transition", headers=admin, json={"action": "approve", "reason": "Evaluated against baseline dataset"})
    assert ap.status_code == 200, ap.text
    assert ap.json()["lifecycle_state"] == "approved"
    hist = client.get(f"{API}/models/{v1['id']}/history", headers=admin).json()
    assert [e["action"] for e in hist["items"]][:2] == ["approve", "register"]
    assert hist["items"][0]["evidence"]["evidence_is_synthetic_only"] is True


def test_unavailable_artifact_failure_scenario_is_recorded_and_signalled(client, db, tokens, auth_header, org, monkeypatch, tmp_path):
    from app.core.config import get_settings

    analyst = auth_header(tokens, "analyst")
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "m.bin").write_bytes(b"weights-v1")
    monkeypatch.setattr(get_settings(), "MLOPS_ARTIFACT_ROOT", str(root))
    r = client.post(f"{API}/models", headers=analyst, json={"name": "file-backed", "version": "1.0.0", "task_type": "classification", "artifact_reference": "artifact:m.bin"})
    assert r.status_code == 201, r.text
    model = r.json()
    assert model["artifact_digest"]  # computed at registration from the real file
    (root / "m.bin").unlink()  # artifact disappears after registration

    run = client.post(f"{API}/experiments", headers=analyst, json={"model_record_id": model["id"], "experiment_name": "after-loss", "classification": {
        "dataset_name": "d", "dataset_version": "1", "is_synthetic": True, "samples": [{"true_label": "a", "predicted_label": "a"}]}})
    assert run.status_code == 201
    body = run.json()
    assert body["status"] == "failed" and body["error_category"] == "missing_artifact" and body["metrics"] is None
    assert "m.bin" not in (body["error_message"] or "") and str(root) not in (body["error_message"] or "")
    cats = {s["category"] for s in client.get(f"{API}/signals", headers=analyst).json()["items"]}
    assert {"evaluation_failed", "artifact_unavailable"} <= cats
