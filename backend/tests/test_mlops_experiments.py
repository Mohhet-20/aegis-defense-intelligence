"""Experiment tracking: fingerprints, idempotency, limits, failure
handling, honest metrics, baseline comparison compatibility."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.mlops import compare
from app.mlops.fingerprint import canonical_json, fingerprint
from app.models.mlops import ExperimentRun

API = "/api/v1/mlops"


def _model(client, h, task="classification", version="1.0.0", name="m"):
    body = {"name": name, "version": version, "task_type": task}
    if task == "object_detection":
        body.update(adapter_key="mock_detector_v1", supported_media_types=["image"])
    r = client.post(f"{API}/models", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _clf_body(mid, samples, key=None, ds="d", dv="1", synthetic=False, **cfg):
    b = {"model_record_id": mid, "experiment_name": "exp", "classification": {"dataset_name": ds, "dataset_version": dv, "is_synthetic": synthetic, "samples": samples, **cfg}}
    if key:
        b["idempotency_key"] = key
    return b


# ---- fingerprints -------------------------------------------------------------------
def test_fingerprint_is_deterministic_order_independent_and_rejects_nan():
    assert fingerprint({"a": 1, "b": [1, 2]}) == fingerprint({"b": [1, 2], "a": 1})
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_same_inputs_give_same_fingerprints_and_different_data_changes_dataset_fingerprint(client, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    r1 = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples())).json()
    r2 = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples())).json()
    assert r1["id"] != r2["id"] and r1["run_fingerprint"] == r2["run_fingerprint"] and r1["dataset_fingerprint"] == r2["dataset_fingerprint"]
    r3 = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(wrong=3))).json()
    # the dataset fingerprint covers the evaluation data (references + ground truth), not the model's predictions
    assert r3["dataset_fingerprint"] == r1["dataset_fingerprint"] and r3["run_fingerprint"] != r1["run_fingerprint"]
    r4 = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(n_pos=41))).json()
    assert r4["dataset_fingerprint"] != r1["dataset_fingerprint"]
    assert r1["reproducibility"]["python_version"] and r1["reproducibility"]["metric_implementation_version"] == compare.METRIC_IMPL_VERSION


# ---- idempotency -------------------------------------------------------------------
def test_idempotency_replay_returns_existing_run_and_conflicting_payload_is_409(client, db, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    first = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(), key="idem-key-0001"))
    assert first.status_code == 201
    again = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(), key="idem-key-0001"))
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert len(db.execute(select(ExperimentRun)).scalars().all()) == 1
    clash = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(wrong=2), key="idem-key-0001"))
    assert clash.status_code == 409 and clash.json()["error_category"] == "validation"
    assert client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(), key="x")).status_code == 422  # key too short


def test_same_idempotency_key_in_another_organization_is_independent(client, tokens, auth_header, b_headers, clf_samples):
    a = auth_header(tokens, "analyst")
    ma = _model(client, a)
    assert client.post(f"{API}/experiments", headers=a, json=_clf_body(ma, clf_samples(), key="shared-key-001")).status_code == 201
    # org B cannot use A's model, and B's own key space is separate
    assert client.post(f"{API}/experiments", headers=b_headers, json=_clf_body(ma, clf_samples(), key="shared-key-001")).status_code == 404


# ---- validation and limits ---------------------------------------------------------------
def test_request_validation(client, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    base = _clf_body(mid, clf_samples())
    both = {**base, "detection": {"sample_count": 3}}
    neither = {k: v for k, v in base.items() if k != "classification"}
    for bad in (both, neither, {**base, "surprise": 1}, _clf_body(mid, []), _clf_body(mid, [{"predicted_label": "a", "positive_probability": 0.5}])):
        assert client.post(f"{API}/experiments", headers=a, json=bad).status_code == 422
    probs = _clf_body(mid, [{"true_label": "a", "predicted_label": "a", "positive_probability": 1.5}], positive_label="a")
    assert client.post(f"{API}/experiments", headers=a, json=probs).status_code == 422
    assert client.post(f"{API}/experiments", headers=a, json=_clf_body("nope", clf_samples())).status_code == 404
    assert client.post(f"{API}/experiments", json=base).status_code == 401
    assert client.post(f"{API}/experiments", headers=auth_header(tokens, "viewer"), json=base).status_code == 403


def test_sample_limit_enforced_with_413(client, tokens, auth_header, monkeypatch):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    monkeypatch.setattr(get_settings(), "MLOPS_MAX_EVAL_SAMPLES", 5)
    r = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, [{"true_label": "a", "predicted_label": "a"}] * 6))
    assert r.status_code == 413 and r.json()["error_category"] == "resource_limit"


def test_detection_task_requires_detection_config_and_matching_model(client, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    det, clf = _model(client, a, "object_detection", name="d"), _model(client, a, name="c")
    assert client.post(f"{API}/experiments", headers=a, json=_clf_body(det, clf_samples())).status_code == 422
    assert client.post(f"{API}/experiments", headers=a, json={"model_record_id": clf, "experiment_name": "x", "detection": {"sample_count": 3}}).status_code == 422


# ---- honest metrics --------------------------------------------------------------------
def test_unlabelled_samples_produce_no_metrics_and_are_not_scored_as_zero(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    r = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, [{"predicted_label": "a"}] * 10))
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        body = r.json()
        assert body["status"] == "failed" or all(m["value"] is None for m in (body["metrics"] or {}).values())


def test_undefined_metrics_are_null_with_a_reason_never_zero(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    samples = [{"true_label": "neg", "predicted_label": "neg"}] * 40  # positive class never occurs
    resp = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, samples, positive_label="pos", labels=["neg", "pos"]))
    body = resp.json()
    assert resp.status_code == 201, resp.text
    assert body["status"] == "succeeded"
    recall = body["metrics"]["recall"]
    assert recall["value"] is None and recall["defined"] is False and recall["reason"]
    assert body["metrics"]["accuracy"]["value"] == 1.0 and body["metrics"]["accuracy"]["ci95"]


def test_ci_only_for_proportion_metrics_and_synthetic_claim_is_labelled(client, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    b = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(wrong=4), synthetic=True, positive_label="pos")).json()
    m = b["metrics"]
    assert m["precision"]["ci95"] and m["recall"]["ci95"] and m["macro_f1"]["ci95"] is None and m["f1"]["ci95"] is None
    assert "SYNTHETIC" in b["performance_claim"]
    assert 0 <= m["recall"]["ci95"][0] <= m["recall"]["value"] <= m["recall"]["ci95"][1] <= 1


def test_probability_metrics_present_only_when_probabilities_supplied(client, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    without = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(), positive_label="pos")).json()
    assert "brier_score" not in without["metrics"] or without["metrics"]["brier_score"]["value"] is None
    withp = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(with_probs=True), positive_label="pos")).json()
    assert withp["metrics"]["brier_score"]["value"] is not None and withp["run_fingerprint"] != without["run_fingerprint"]


def test_detection_run_on_mock_adapter_links_legacy_run_and_never_reports_undefined_as_zero(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a, "object_detection")
    body = client.post(f"{API}/experiments", headers=a, json={"model_record_id": mid, "experiment_name": "det", "detection": {"sample_count": 8}})
    assert body.status_code == 201, body.text
    run = body.json()
    assert run["status"] == "succeeded" and run["is_synthetic"] is True and run["source_run_type"] and run["source_run_id"]
    for name in ("precision", "recall", "f1", "mean_iou"):
        m = run["metrics"][name]
        assert m["defined"] == (m["value"] is not None)
        if not m["defined"]:
            assert m["reason"]
    detail = client.get(f"{API}/experiments/{run['id']}", headers=a).json()
    assert "SYNTHETIC" in detail["performance_claim"] and detail["limitations"]


# ---- failure handling ----------------------------------------------------------------------
def test_failed_run_is_recorded_sanitized_and_does_not_disturb_earlier_results(client, db, tokens, auth_header, clf_samples, monkeypatch):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    ok = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples())).json()
    from app.services import classification_evaluation_service as ces

    def boom(*args, **kw):
        raise RuntimeError("secret /srv/data/path password=hunter2")

    monkeypatch.setattr(ces, "run_classification_evaluation", boom)
    r = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(wrong=1)))
    assert r.status_code == 201
    failed = r.json()
    assert failed["status"] == "failed" and failed["metrics"] is None and failed["error_category"]
    text = str(failed)
    assert "hunter2" not in text and "/srv/data" not in text
    again = client.get(f"{API}/experiments/{ok['id']}", headers=a).json()
    assert again["status"] == "succeeded" and again["metrics"] == ok["metrics"]
    hist = client.get(f"{API}/experiments?status=failed", headers=a).json()
    assert hist["total"] == 1


def test_stale_running_rows_are_reaped_to_failed_interrupted(client, db, org, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    old = datetime.now(timezone.utc) - timedelta(seconds=get_settings().MLOPS_STALE_RUN_SECONDS + 60)
    row = ExperimentRun(organization_id=org.id, model_record_id=mid, model_version="1.0.0", task="classification", experiment_name="x", status="running",
                        execution_mode="synchronous", dataset_name="d", dataset_version="1", is_synthetic=False, started_at=old, run_fingerprint="f" * 64,
                        config_fingerprint="c" * 64, dataset_fingerprint="d" * 64, config={})
    db.add(row)
    db.commit()
    scan = client.post(f"{API}/signals/scan", headers=a)
    assert scan.status_code == 200 and scan.json()["stale_runs_marked_failed"] == 1
    got = client.get(f"{API}/experiments/{row.id}", headers=a).json()
    assert got["status"] == "failed" and got["error_category"] == "interrupted"


# ---- baselines and comparison ---------------------------------------------------------------
def test_baseline_requires_succeeded_run_and_same_org(client, db, org, tokens, auth_header, b_headers, clf_samples):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    run = client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples())).json()
    assert client.put(f"{API}/baselines", headers=b_headers, json={"run_id": run["id"]}).status_code == 404
    assert client.put(f"{API}/baselines", headers=auth_header(tokens, "viewer"), json={"run_id": run["id"]}).status_code == 403
    row = db.get(ExperimentRun, run["id"])
    row.status, row.error_category = "failed", "unknown"
    db.commit()
    assert client.put(f"{API}/baselines", headers=a, json={"run_id": run["id"]}).status_code == 409
    assert client.get(f"{API}/baselines", headers=a).json()["items"] == []


def test_comparison_without_baseline_says_so(client, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    run = client.post(f"{API}/experiments", headers=a, json=_clf_body(_model(client, a), clf_samples())).json()
    c = client.get(f"{API}/experiments/{run['id']}/comparison", headers=a).json()
    assert c["status"] == "no_baseline"


def test_incompatible_runs_are_rejected_with_reasons(client, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    m1, m2 = _model(client, a, version="1.0.0"), _model(client, a, version="1.1.0")
    base = client.post(f"{API}/experiments", headers=a, json=_clf_body(m1, clf_samples(), ds="d1")).json()
    other_ds = client.post(f"{API}/experiments", headers=a, json=_clf_body(m2, clf_samples(), ds="d2")).json()
    r = client.get(f"{API}/experiments/{other_ds['id']}/comparison?baseline_run_id={base['id']}", headers=a)
    assert r.status_code == 422 and any("dataset" in x for x in r.json()["reasons"])
    changed = client.post(f"{API}/experiments", headers=a, json=_clf_body(m2, clf_samples(n_pos=41), ds="d1")).json()
    r = client.get(f"{API}/experiments/{changed['id']}/comparison?baseline_run_id={base['id']}", headers=a)
    assert r.status_code == 422 and any("fingerprint" in x for x in r.json()["reasons"])
    syn = client.post(f"{API}/experiments", headers=a, json=_clf_body(m2, clf_samples(), ds="d1", synthetic=True)).json()
    r = client.get(f"{API}/experiments/{syn['id']}/comparison?baseline_run_id={base['id']}", headers=a)
    assert r.status_code == 422 and any("synthetic" in x for x in r.json()["reasons"])
    det = client.post(f"{API}/experiments", headers=a, json={"model_record_id": _model(client, a, "object_detection", name="dd"), "experiment_name": "d", "detection": {"sample_count": 4}}).json()
    r = client.get(f"{API}/experiments/{det['id']}/comparison?baseline_run_id={base['id']}", headers=a)
    assert r.status_code == 422 and any("tasks" in x for x in r.json()["reasons"])


def test_compatible_comparison_reports_per_metric_with_no_overall_winner(client, tokens, auth_header, clf_samples):
    a = auth_header(tokens, "analyst")
    m1, m2 = _model(client, a, version="1.0.0"), _model(client, a, version="1.1.0")
    base = client.post(f"{API}/experiments", headers=a, json=_clf_body(m1, clf_samples(wrong=0, n_pos=300, n_neg=300), positive_label="pos")).json()
    cand = client.post(f"{API}/experiments", headers=a, json=_clf_body(m2, clf_samples(wrong=0, n_pos=300, n_neg=300), positive_label="pos")).json()
    c = client.get(f"{API}/experiments/{cand['id']}/comparison?baseline_run_id={base['id']}", headers=a).json()
    assert c["status"] == "compared" and c["summary"]["regressed"] == 0 and c["summary"]["review_recommended"] is False
    assert all(r["change"] in ("unchanged", "not_comparable") for r in c["metrics"])
    assert "better" not in c["summary"]["statement"].lower()
    assert c["caveats"]


def test_regression_below_threshold_is_not_flagged_and_ci_distinguishability_is_reported(client, tokens, auth_header, clf_samples, monkeypatch):
    a = auth_header(tokens, "analyst")
    monkeypatch.setattr(get_settings(), "MLOPS_REGRESSION_ABS_THRESHOLD", 0.5)
    m1, m2 = _model(client, a, version="1.0.0"), _model(client, a, version="1.1.0")
    base = client.post(f"{API}/experiments", headers=a, json=_clf_body(m1, clf_samples(wrong=0), positive_label="pos")).json()
    cand = client.post(f"{API}/experiments", headers=a, json=_clf_body(m2, clf_samples(wrong=4), positive_label="pos")).json()
    c = client.get(f"{API}/experiments/{cand['id']}/comparison?baseline_run_id={base['id']}", headers=a).json()
    rec = next(r for r in c["metrics"] if r["metric"] == "recall")
    assert rec["change"] == "regressed" and rec["exceeds_review_threshold"] is False
    assert rec["distinguishable_at_95"] in (True, False)


# ---- history / access ---------------------------------------------------------------------
def test_history_filters_pagination_and_cross_org_isolation(client, tokens, auth_header, b_headers, clf_samples):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    for _ in range(3):
        client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples()))
    assert client.get(f"{API}/experiments?page_size=2", headers=a).json()["total"] == 3
    assert client.get(f"{API}/experiments?page_size=201", headers=a).status_code == 422
    assert client.get(f"{API}/experiments?status=bogus", headers=a).status_code == 422
    assert client.get(f"{API}/experiments", headers=b_headers).json()["total"] == 0
    rid = client.get(f"{API}/experiments", headers=a).json()["items"][0]["id"]
    assert client.get(f"{API}/experiments/{rid}", headers=b_headers).status_code == 404
    assert client.get(f"{API}/experiments/{rid}", headers=auth_header(tokens, "viewer")).status_code == 200
    hist = client.get(f"{API}/experiments/history?metric=accuracy&task=classification&model_record_id={mid}", headers=a)
    assert hist.status_code == 200, hist.text


# ---- unit: compare -----------------------------------------------------------------------
def test_unit_detection_and_classification_metric_math():
    m = compare.detection_metrics(tp=0, fp=0, fn=0, mean_iou_value=None)
    assert all(not m[k]["defined"] and m[k]["value"] is None for k in ("precision", "recall", "f1", "mean_iou"))
    m = compare.detection_metrics(tp=8, fp=2, fn=2, mean_iou_value=0.75)
    assert m["precision"]["value"] == pytest.approx(0.8) and m["recall"]["value"] == pytest.approx(0.8) and m["f1"]["value"] == pytest.approx(0.8)
    assert m["precision"]["ci95"] and m["mean_iou"]["ci95"] is None


def test_unit_thresholds_use_config_overrides_and_ignore_garbage(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "MLOPS_REGRESSION_THRESHOLDS_JSON", '{"classification": {"recall": 0.01}}')
    monkeypatch.setattr(s, "MLOPS_METRIC_FLOORS_JSON", '{"classification": {"recall": 0.9}}')
    assert compare.regression_threshold("classification", "recall") == 0.01
    assert compare.regression_threshold("classification", "precision") == s.MLOPS_REGRESSION_ABS_THRESHOLD
    assert compare.metric_floor("classification", "recall") == 0.9 and compare.metric_floor("classification", "precision") is None
    monkeypatch.setattr(s, "MLOPS_REGRESSION_THRESHOLDS_JSON", "not json")
    assert compare.regression_threshold("classification", "recall") == s.MLOPS_REGRESSION_ABS_THRESHOLD


def test_metric_floor_breach_raises_a_signal(client, tokens, auth_header, clf_samples, monkeypatch):
    a = auth_header(tokens, "analyst")
    monkeypatch.setattr(get_settings(), "MLOPS_METRIC_FLOORS_JSON", '{"classification": {"accuracy": 0.99}}')
    mid = _model(client, a)
    client.post(f"{API}/experiments", headers=a, json=_clf_body(mid, clf_samples(wrong=10)))
    sigs = client.get(f"{API}/signals?category=metric_below_floor", headers=a).json()
    assert sigs["total"] == 1 and sigs["items"][0]["threshold_value"] == 0.99
