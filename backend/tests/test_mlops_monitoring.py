"""Monitoring snapshots, drift vs prediction drift vs performance vs
operational, honest 'not assessable', bounded storage, job-failure signals."""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.mlops import stats
from app.models.inference_job import InferenceJob
from app.models.mlops import MonitoringSnapshot, ReviewSignal

API = "/api/v1/mlops"


def _model(client, h, task="classification", name="mon", version="1.0.0"):
    body = {"name": name, "version": version, "task_type": task}
    if task == "object_detection":
        body.update(adapter_key="mock_detector_v1", supported_media_types=["image"])
    return client.post(f"{API}/models", headers=h, json=body).json()["id"]


def _window(days_ago_end=0.5, span_days=1):
    end = datetime.now(timezone.utc) - timedelta(days=days_ago_end)
    return (end - timedelta(days=span_days)).isoformat(), end.isoformat()


def _records(n, mean=50.0, labels=("pos", "neg"), cat="a", label_weights=(0.5, 0.5), seed=1, truth=False, accuracy=1.0, conf=0.9):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        pred = rnd.choices(labels, weights=label_weights)[0]
        r = {"features": {"score": rnd.gauss(mean, 5), "kind": cat if rnd.random() < 0.8 else "b"}, "predicted_label": pred, "confidence": min(1.0, max(0.0, rnd.gauss(conf, 0.05)))}
        if truth:
            r["true_label"] = pred if rnd.random() < accuracy else next(l for l in labels if l != pred)
        out.append(r)
    return out


def _snap(client, h, mid, kind, records, ref=None, **kw):
    ws, we = _window()
    body = {"model_record_id": mid, "kind": kind, "window_start": ws, "window_end": we, "records": records, **kw}
    if ref:
        body["reference_snapshot_id"] = ref
    return client.post(f"{API}/monitoring/snapshots", headers=h, json=body)


def test_unshifted_current_window_raises_no_drift_signal(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    ref = _snap(client, a, mid, "reference", _records(200, seed=1)).json()["snapshot"]
    cur = _snap(client, a, mid, "current", _records(200, seed=2), ref=ref["id"])
    assert cur.status_code == 201, cur.text
    rep = cur.json()["report"]
    assert rep["data_drift"]["status"] in ("no_material_change", "moderate_shift")
    cats = {s["category"] for s in client.get(f"{API}/signals", headers=a).json()["items"]}
    assert "data_drift" not in cats and "prediction_drift" not in cats


def test_shifted_current_window_flags_data_and_prediction_drift_separately(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    ref = _snap(client, a, mid, "reference", _records(200, seed=1)).json()["snapshot"]
    cur = _snap(client, a, mid, "current", _records(200, mean=80.0, label_weights=(0.95, 0.05), conf=0.5, seed=3), ref=ref["id"])
    rep = cur.json()["report"]
    assert rep["data_drift"]["status"] == "large_shift" and rep["prediction_drift"]["status"] == "large_shift"
    assert rep["performance"]["status"] == "not_assessable" and "labelled" in rep["performance"]["reason"]  # drift is not performance degradation
    sigs = client.get(f"{API}/signals", headers=a).json()["items"]
    cats = {s["category"] for s in sigs}
    assert {"data_drift", "prediction_drift"} <= cats and "performance_degradation" not in cats
    d = next(s for s in sigs if s["category"] == "data_drift")
    assert d["observed_value"] > get_settings().MLOPS_PSI_ALERT and "does not by itself" in json.dumps(d).lower() or d["limitations"]
    # re-evaluating the same condition deduplicates
    _snap(client, a, mid, "current", _records(200, mean=80.0, label_weights=(0.95, 0.05), conf=0.5, seed=4), ref=ref["id"])
    again = [s for s in client.get(f"{API}/signals?category=data_drift", headers=a).json()["items"]]
    assert len(again) == 1 and again[0]["occurrence_count"] == 2


def test_performance_degradation_requires_labels_and_non_overlapping_intervals(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    ref = _snap(client, a, mid, "reference", _records(300, seed=1, truth=True, accuracy=0.97)).json()["snapshot"]
    cur = _snap(client, a, mid, "current", _records(300, seed=2, truth=True, accuracy=0.70), ref=ref["id"]).json()
    perf = cur["report"]["performance"]
    assert perf["status"] == "lower" and perf["metric"] == "accuracy" and perf["current"]["ci95"] and perf["reference"]["n"] == 300
    sig = client.get(f"{API}/signals?category=performance_degradation", headers=a).json()["items"]
    assert len(sig) == 1 and sig[0]["severity"] == "serious"
    same = _snap(client, a, mid, "current", _records(300, seed=5, truth=True, accuracy=0.96), ref=ref["id"]).json()["report"]["performance"]
    assert same["status"] == "no_detectable_change"


def test_small_windows_are_not_assessed_and_raise_insufficient_data(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    ref = _snap(client, a, mid, "reference", _records(200)).json()["snapshot"]
    cur = _snap(client, a, mid, "current", _records(10, mean=90.0), ref=ref["id"]).json()
    rep = cur["report"]
    assert rep["data_drift"]["status"] == "not_assessable" and rep["prediction_drift"]["status"] == "not_assessable" and "fewer than" in rep["data_drift"]["reason"]
    assert [s["category"] for s in client.get(f"{API}/signals", headers=a).json()["items"]] == ["insufficient_data"]


def test_current_without_reference_is_stored_but_not_assessable(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    snap = _snap(client, a, mid, "current", _records(100)).json()
    assert snap["report"] is None
    drift = client.get(f"{API}/monitoring/snapshots/{snap['snapshot']['id']}/drift", headers=a).json()
    assert drift["data_drift"]["status"] == "not_assessable" and drift["performance"]["status"] == "not_assessable"
    assert drift["operational"]["status"] == "not_applicable"  # classification models run no AEGIS inference jobs


def test_stored_summary_is_bounded_and_holds_no_raw_values(client, db, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    recs = _records(300)
    recs[0]["features"]["kind"] = "SENTINEL-RAW-VALUE-XYZ"
    snap = _snap(client, a, mid, "reference", recs).json()["snapshot"]
    row = db.get(MonitoringSnapshot, snap["id"])
    blob = json.dumps(row.summary)
    assert len(blob) < 20000
    assert str(recs[1]["features"]["score"]) not in blob  # numeric features are binned, never stored row-wise
    assert row.summary["features"]["score"]["counts"] and sum(row.summary["features"]["score"]["counts"]) == 300


def test_schema_violations_and_non_finite_values(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    ref = _snap(client, a, mid, "reference", _records(100), expected_schema={"score": "numeric", "kind": "categorical"}).json()["snapshot"]
    bad = _records(100, seed=9)
    for r in bad[:30]:
        r["features"]["score"] = "not-a-number"
    cur = _snap(client, a, mid, "current", bad, ref=ref["id"]).json()
    assert cur["snapshot"]["schema_violation_count"] == 30
    assert cur["report"]["data_drift"]["schema_violations"]["elevated"] is True
    assert "input_schema_violations" in {s["category"] for s in client.get(f"{API}/signals", headers=a).json()["items"]}
    h = {**a, "Content-Type": "application/json"}
    raw = json.dumps({"model_record_id": mid, "kind": "reference", "window_start": _window()[0], "window_end": _window()[1], "records": [{"features": {"score": 1}}]}).replace('"score": 1', '"score": NaN')
    assert client.post(f"{API}/monitoring/snapshots", headers=h, content=raw).status_code == 422
    inf = _records(5)
    inf[0]["confidence"] = 1.5
    assert _snap(client, a, mid, "reference", inf).status_code == 422


def test_request_validation_limits_and_windows(client, tokens, auth_header, monkeypatch):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    ws, we = _window()
    base = {"model_record_id": mid, "kind": "reference", "window_start": ws, "window_end": we, "records": _records(5)}
    post = lambda **kw: client.post(f"{API}/monitoring/snapshots", headers=a, json={**base, **kw})
    assert post(window_start=we, window_end=ws).status_code == 422
    assert post(kind="other").status_code == 422
    assert post(records=[]).status_code == 422
    assert post(window_end=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat()).status_code == 422
    assert post(window_start=(datetime.now(timezone.utc) - timedelta(days=500)).isoformat()).status_code == 422
    assert post(unknown=1).status_code == 422
    assert post(model_record_id="missing").status_code == 404
    assert post(records=[{"features": {"bad name!": 1}}]).status_code == 422
    monkeypatch.setattr(get_settings(), "MLOPS_MONITOR_MAX_ROWS", 3)
    r = post()
    assert r.status_code == 413
    monkeypatch.setattr(get_settings(), "MLOPS_MONITOR_MAX_ROWS", 2000)
    monkeypatch.setattr(get_settings(), "MLOPS_MONITOR_MAX_FEATURES", 1)
    assert post(records=_records(5)).status_code == 413
    assert client.post(f"{API}/monitoring/snapshots", headers=auth_header(tokens, "viewer"), json=base).status_code == 403


def test_reference_must_be_same_model_reference_kind_and_same_org(client, tokens, auth_header, b_headers):
    a = auth_header(tokens, "analyst")
    m1, m2 = _model(client, a, version="1.0.0"), _model(client, a, version="1.1.0")
    ref1 = _snap(client, a, m1, "reference", _records(40)).json()["snapshot"]
    cur1 = _snap(client, a, m1, "current", _records(40)).json()["snapshot"]
    assert _snap(client, a, m2, "current", _records(40), ref=ref1["id"]).status_code == 422
    assert _snap(client, a, m1, "current", _records(40), ref=cur1["id"]).status_code == 422
    assert _snap(client, a, m1, "current", _records(40), ref="does-not-exist").status_code == 404
    assert client.get(f"{API}/monitoring/snapshots/{ref1['id']}", headers=b_headers).status_code == 404
    assert client.get(f"{API}/monitoring/snapshots/{ref1['id']}/drift", headers=b_headers).status_code == 404
    assert client.get(f"{API}/monitoring/snapshots", headers=b_headers).json()["total"] == 0
    assert _snap(client, b_headers, m1, "current", _records(40), ref=ref1["id"]).status_code == 404  # B cannot even see A's model


def test_listing_and_coverage_report_unmonitored_models_honestly(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    m1, m2 = _model(client, a, name="x", version="1.0.0"), _model(client, a, name="y", version="1.0.0")
    _snap(client, a, m1, "current", _records(40))
    cov = client.get(f"{API}/monitoring/coverage", headers=a).json()
    by = {i["model_record_id"]: i for i in cov["models"]}
    assert by[m1]["coverage"] == "current" and by[m2]["coverage"] == "no_monitoring" and by[m2]["latest_current_snapshot_id"] is None
    assert cov["models_with_current_monitoring"] == 1 and cov["models_total"] == 2
    assert client.get(f"{API}/monitoring/snapshots?kind=current&model_record_id={m1}", headers=a).json()["total"] == 1
    assert client.get(f"{API}/monitoring/snapshots?kind=bogus", headers=a).status_code == 422


def test_stale_monitoring_is_reported_as_stale_not_current(client, tokens, auth_header):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a)
    ws, we = _window(days_ago_end=20)
    client.post(f"{API}/monitoring/snapshots", headers=a, json={"model_record_id": mid, "kind": "current", "window_start": ws, "window_end": we, "records": _records(40)})
    cov = client.get(f"{API}/monitoring/coverage", headers=a).json()
    assert cov["models"][0]["coverage"] == "stale" and cov["models_with_current_monitoring"] == 0


# ---- operational (real InferenceJob rows) ---------------------------------------------------
def _jobs(db, org, model_id, media_id, failed, completed):
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=0.75)  # inside the default snapshot window
    for i in range(failed + completed):
        ok = i >= failed
        db.add(InferenceJob(organization_id=org.id, media_asset_id=media_id, model_record_id=model_id, job_type="image_detection", status="completed" if ok else "failed", created_at=created,
                            parameters={}, started_at=now - timedelta(seconds=2), finished_at=now - timedelta(seconds=1), error_message=None if ok else "x"))
    db.commit()


def test_job_failure_scan_uses_real_job_rows_and_respects_min_samples(client, db, org, tokens, auth_header, png_bytes):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a, "object_detection")
    media = client.post("/api/v1/media", headers=a, files={"file": ("x.png", png_bytes(), "image/png")}).json()["id"]
    _jobs(db, org, mid, media, failed=3, completed=2)  # 5 finished: below MLOPS_JOB_MIN_SAMPLES
    assert client.post(f"{API}/signals/scan", headers=a).json()["job_failures"]["models_over_threshold"] == 0
    _jobs(db, org, mid, media, failed=6, completed=4)  # 15 finished, 9 failed = 60%
    scan = client.post(f"{API}/signals/scan", headers=a).json()
    assert scan["job_failures"]["models_over_threshold"] == 1
    sig = client.get(f"{API}/signals?category=job_failure_rate", headers=a).json()["items"]
    assert len(sig) == 1 and sig[0]["observed_value"] == pytest.approx(0.6)
    client.post(f"{API}/signals/scan", headers=a)  # idempotent
    sig = client.get(f"{API}/signals?category=job_failure_rate", headers=a).json()["items"]
    assert len(sig) == 1 and sig[0]["occurrence_count"] == 2
    assert client.post(f"{API}/signals/scan", headers=auth_header(tokens, "viewer")).status_code == 403


def test_operational_section_present_for_detection_models(client, db, org, tokens, auth_header, png_bytes):
    a = auth_header(tokens, "analyst")
    mid = _model(client, a, "object_detection")
    media = client.post("/api/v1/media", headers=a, files={"file": ("x.png", png_bytes(), "image/png")}).json()["id"]
    _jobs(db, org, mid, media, failed=0, completed=12)
    ref = _snap(client, a, mid, "reference", _records(40)).json()["snapshot"]
    cur = _snap(client, a, mid, "current", _records(40, seed=2), ref=ref["id"]).json()
    op = cur["report"]["operational"]
    assert op["status"] == "measured" and op["finished_jobs"] == 12 and op["failure_rate"] == 0.0 and op["duration_seconds"]["sample"] == 12


# ---- unit: stats -----------------------------------------------------------------------------
def test_unit_psi_and_wilson_and_binning():
    assert stats.psi([10, 10, 10], [10, 10, 10]) == pytest.approx(0.0, abs=1e-9)
    assert stats.psi([100, 0, 0], [0, 0, 100]) > 1.0
    lo, hi = stats.wilson_interval(8, 10)
    assert 0.4 < lo < 0.8 < hi <= 1.0
    assert stats.wilson_interval(0, 0) is None
    assert stats.intervals_overlap((0.1, 0.5), (0.4, 0.9)) and not stats.intervals_overlap((0.1, 0.3), (0.4, 0.9))
    edges = stats.equal_width_edges(0.0, 10.0, 5)
    counts, under, over = stats.bin_counts([-1, 0, 3, 9.9, 10, 11], edges)
    assert sum(counts) == 6 and under == 1 and over == 1  # out-of-range values are clamped into the edge bins and also counted separately
    assert stats.mean_std([]) == (None, None)
