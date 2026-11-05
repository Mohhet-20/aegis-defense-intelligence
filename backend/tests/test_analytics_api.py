"""API-level tests: model evaluation, model outputs +
explanations, assessment scoring, human review. Covers permissions,
validation/error responses, version tracking, history preservation,
audit events and organization isolation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analytics import metrics as metrics_mod
from app.core.security import hash_password
from app.models.assessment import Assessment
from app.models.audit import AuditRecord
from app.models.classification_evaluation_run import ClassificationEvaluationRun
from app.models.conflict import Conflict
from app.models.data_source import DataSource
from app.models.detection_result import DetectionResult
from app.models.event import Event
from app.models.evidence import Evidence
from app.models.organization import Organization
from app.models.risk_assessment import RiskAssessment
from app.models.user import User
from app.services import assessment_service

API = "/api/v1"
PW = "TestPassword123!"


# ------------------------------- helpers --------------------------------
@pytest.fixture()
def H(tokens, auth_header):
    return lambda role: auth_header(tokens, role)


@pytest.fixture()
def other_org_headers(db, client):
    other = Organization(name="Other Org", status="active")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(User(organization_id=other.id, username="other_admin", email="oa@other.example.com", display_name="OA",
                password_hash=hash_password(PW), role="administrator", is_active=True))
    db.commit()
    r = client.post(f"{API}/auth/login", json={"username_or_email": "other_admin", "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, other


def eval_payload(model, **over):
    samples = [
        {"sample_ref": "s1", "true_label": "pos", "predicted_label": "pos", "positive_probability": 0.9},
        {"sample_ref": "s2", "true_label": "pos", "predicted_label": "neg", "positive_probability": 0.4},
        {"sample_ref": "s3", "true_label": "neg", "predicted_label": "neg", "positive_probability": 0.2},
        {"sample_ref": "s4", "true_label": "neg", "predicted_label": "pos", "positive_probability": 0.6},
        {"sample_ref": "s5", "true_label": None, "predicted_label": "pos", "positive_probability": 0.7},
    ]
    p = {"model_record_id": model.id, "dataset_name": "unit-ds", "dataset_version": "2", "is_synthetic": True,
         "positive_label": "pos", "samples": samples}
    p.update(over)
    return p


# ---------------------------- model evaluation --------------------------
def test_evaluation_run_computes_real_metrics_and_records_versions(client, H, cv_mock_model):
    r = client.post(f"{API}/model-evaluations", json=eval_payload(cv_mock_model, model_version="v1"), headers=H("analyst"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "completed" and body["model_version"] == "v1"
    assert body["dataset_name"] == "unit-ds" and body["dataset_version"] == "2"
    c = body["results"]["classification"]
    assert c["labelled_sample_count"] == 4 and c["excluded_missing_label"] == 1
    assert c["accuracy"]["value"] == 0.5 and c["confusion_matrix"] == [[1, 1], [1, 1]]
    p = body["results"]["probability"]
    assert p["roc_auc"]["value"] == 0.75 and p["scored_sample_count"] == 4
    assert p["brier_score"]["value"] == pytest.approx(((0.1) ** 2 + (0.6) ** 2 + (0.2) ** 2 + (0.6) ** 2) / 4, abs=1e-6)
    assert "roc_auc" in body["metric_definitions"] and body["evaluation_config"]["positive_label"] == "pos"
    assert "NOT evidence of real-world performance" in body["performance_claim"]
    again = client.get(f"{API}/model-evaluations/{body['id']}", headers=H("viewer"))
    assert again.status_code == 200 and again.json()["results"] == body["results"]


def test_non_synthetic_claim_is_scoped_to_the_dataset(client, H, cv_mock_model):
    r = client.post(f"{API}/model-evaluations", json=eval_payload(cv_mock_model, is_synthetic=False), headers=H("analyst"))
    claim = r.json()["performance_claim"]
    assert "supplied labelled dataset" in claim and "SYNTHETIC" not in claim


def test_undefined_metrics_are_reported_not_zeroed(client, H, cv_mock_model):
    payload = eval_payload(cv_mock_model, samples=[
        {"true_label": "pos", "predicted_label": "pos", "positive_probability": 0.9},
        {"true_label": "pos", "predicted_label": "pos", "positive_probability": 0.8}])
    body = client.post(f"{API}/model-evaluations", json=payload, headers=H("analyst")).json()
    auc = body["results"]["probability"]["roc_auc"]
    assert auc["value"] is None and auc["defined"] is False and auc["reason"]


def test_empty_dataset_completes_with_everything_undefined(client, H, cv_mock_model):
    r = client.post(f"{API}/model-evaluations", json=eval_payload(cv_mock_model, samples=[], positive_label=None), headers=H("analyst"))
    assert r.status_code == 201
    assert r.json()["results"]["classification"]["accuracy"]["defined"] is False
    assert any("every metric is undefined" in w for w in r.json()["warnings"])


def test_evaluation_requires_evaluate_permission(client, H, cv_mock_model):
    for role in ("viewer", "investigator"):
        assert client.post(f"{API}/model-evaluations", json=eval_payload(cv_mock_model), headers=H(role)).status_code == 403
    assert client.post(f"{API}/model-evaluations", json=eval_payload(cv_mock_model)).status_code in (401, 403)
    assert client.get(f"{API}/model-evaluations", headers=H("viewer")).status_code == 200


def test_validation_and_error_responses(client, H, cv_mock_model, db):
    post = lambda payload: client.post(f"{API}/model-evaluations", json=payload, headers=H("analyst"))
    assert post(eval_payload(cv_mock_model, model_version="v999")).status_code == 422  # incompatible version
    assert post(eval_payload(cv_mock_model, model_record_id="nope")).status_code == 404
    bad_prob = eval_payload(cv_mock_model)
    bad_prob["samples"][0]["positive_probability"] = 1.5
    assert post(bad_prob).status_code == 422
    assert post(eval_payload(cv_mock_model, positive_label=None)).status_code == 422  # probabilities need positive_label
    assert post(eval_payload(cv_mock_model, labels=["pos"], positive_label="pos")).status_code == 422  # 'neg' outside label set
    missing = eval_payload(cv_mock_model)
    del missing["is_synthetic"]
    assert post(missing).status_code == 422  # must declare synthetic-ness
    assert db.query(ClassificationEvaluationRun).count() == 0  # client errors persist nothing


def test_internal_failure_is_recorded_as_failed_with_no_results(client, H, cv_mock_model, db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(metrics_mod, "classification_report", boom)
    r = client.post(f"{API}/model-evaluations", json=eval_payload(cv_mock_model), headers=H("analyst"))
    assert r.status_code == 500 and "no metrics were stored" in r.json()["detail"]
    runs = db.query(ClassificationEvaluationRun).all()
    assert len(runs) == 1 and runs[0].status == "failed" and runs[0].results is None and "kaboom" not in (runs[0].error_message or "")
    rows = client.get(f"{API}/model-evaluations", headers=H("analyst")).json()["items"]
    assert rows[0]["status"] == "failed" and rows[0]["headline_metrics"] == {}
    assert db.query(AuditRecord).filter_by(action="model_evaluation.failed").count() == 1


def test_overview_unifies_runs_paginates_and_audits(client, H, cv_mock_model, db):
    for _ in range(2):
        client.post(f"{API}/model-evaluations", json=eval_payload(cv_mock_model), headers=H("analyst"))
    det = client.post(f"{API}/evaluation/runs", json={"model_record_id": cv_mock_model.id, "sample_count": 5}, headers=H("analyst"))
    assert det.status_code == 201, det.text
    page = client.get(f"{API}/model-evaluations?page_size=2", headers=H("viewer")).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    kinds = {r["kind"] for r in client.get(f"{API}/model-evaluations", headers=H("viewer")).json()["items"]}
    assert kinds == {"classification", "detection"}
    assert db.query(AuditRecord).filter_by(action="model_evaluation.run").count() == 2


def test_evaluation_org_isolation(client, H, cv_mock_model, other_org_headers):
    hdr, _ = other_org_headers
    run = client.post(f"{API}/model-evaluations", json=eval_payload(cv_mock_model), headers=H("analyst")).json()
    assert client.get(f"{API}/model-evaluations/{run['id']}", headers=hdr).status_code == 404
    assert client.get(f"{API}/model-evaluations", headers=hdr).json()["total"] == 0


# ------------------------- model outputs + explanation ------------------
def _risk(db, org, **kw):
    d = dict(organization_id=org.id, subject_type="asset", subject_id="asset-1", assessed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
             method="rule_v1", score=40.0, confidence=None, contributing_factors=[{"name": "recent_events", "weight": 0.4}],
             evidence_refs=[], data_origin="user_upload")
    d.update(kw)
    r = RiskAssessment(**d)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_risk_output_is_normalized_without_manufacturing_confidence(client, H, db, org):
    r = _risk(db, org)
    out = client.get(f"{API}/model-outputs/risk_assessment/{r.id}", headers=H("viewer")).json()
    assert out["confidence"] is None and out["confidence_provided"] is False
    assert out["prediction"]["value"] == 40.0 and out["model"]["version"] == "unversioned"
    codes = {i["code"] for i in out["data_quality"]}
    assert {"no_model_version", "confidence_not_provided", "no_evidence_refs"} <= codes
    assert out["execution_status"] == "completed" and out["processed_at"]


def test_risk_explanation_is_rule_based_and_restates_recorded_factors(client, H, db, org):
    r = _risk(db, org)
    e = client.get(f"{API}/model-outputs/risk_assessment/{r.id}/explanation", headers=H("viewer")).json()
    assert e["supported"] and e["method_key"] == "rule_based_factors" and e["explanation_kind"] == "rule_based"
    assert [i["name"] for i in e["items"]] == ["recent_events"] and "not causal" in e["interpretation_note"]
    shap = next(m for m in e["available_methods"] if m["method_key"] == "shap")
    assert shap["supported"] is False and shap["limitation"]
    assert e["data_quality"]


def test_explanation_unsupported_is_shown_not_faked(client, H, db, org):
    r = _risk(db, org, contributing_factors=[])
    e = client.get(f"{API}/model-outputs/risk_assessment/{r.id}/explanation", headers=H("viewer")).json()
    assert e["supported"] is False and e["items"] == [] and "No registered explanation method applies" in e["limitation"]
    rule = next(m for m in e["available_methods"] if m["method_key"] == "rule_based_factors")
    assert "no contributing factors" in rule["limitation"]
    explicit = client.get(f"{API}/model-outputs/risk_assessment/{r.id}/explanation?method=rule_based_factors", headers=H("viewer")).json()
    assert explicit["supported"] is False and "no contributing factors" in explicit["limitation"]
    forced = client.get(f"{API}/model-outputs/risk_assessment/{r.id}/explanation?method=detection_confidence_metadata", headers=H("viewer")).json()
    assert forced["supported"] is False
    assert client.get(f"{API}/model-outputs/risk_assessment/{r.id}/explanation?method=magic", headers=H("viewer")).status_code == 422


def test_detection_output_and_explanation(client, H, tracking_source_factory, db):
    _, job = tracking_source_factory(pattern="single", num_frames=3, confidence=0.3)
    det = db.query(DetectionResult).filter_by(inference_job_id=job.id).first()
    out = client.get(f"{API}/model-outputs/detection_result/{det.id}", headers=H("viewer")).json()
    codes = {i["code"] for i in out["data_quality"]}
    assert out["confidence"] == 0.3 and out["confidence_provided"] and {"low_confidence", "mock_model_output", "unreviewed"} <= codes
    assert out["model"]["name"] == "test-mock-detector" and out["model"]["version"] == "v1"
    assert {"type": "inference_job", "id": job.id, "label": None} in out["supporting_records"]
    e = client.get(f"{API}/model-outputs/detection_result/{det.id}/explanation", headers=H("viewer")).json()
    assert e["supported"] and e["method_key"] == "detection_confidence_metadata"
    listing = client.get(f"{API}/model-outputs?output_type=detection_result&page_size=2", headers=H("viewer")).json()
    assert listing["total"] == 3 and len(listing["items"]) == 2 and listing["skipped_invalid"] == 0


def test_output_validation_errors_and_isolation(client, H, db, org, other_org_headers):
    hdr, _ = other_org_headers
    r = _risk(db, org)
    assert client.get(f"{API}/model-outputs?output_type=bogus", headers=H("viewer")).status_code == 422
    assert client.get(f"{API}/model-outputs/bogus/{r.id}", headers=H("viewer")).status_code == 422
    assert client.get(f"{API}/model-outputs/risk_assessment/missing", headers=H("viewer")).status_code == 404
    assert client.get(f"{API}/model-outputs/risk_assessment/{r.id}", headers=hdr).status_code == 404
    assert client.get(f"{API}/model-outputs/risk_assessment/{r.id}/explanation", headers=hdr).status_code == 404
    assert client.get(f"{API}/model-outputs?output_type=risk_assessment", headers=hdr).json()["total"] == 0
    assert client.get(f"{API}/model-outputs?output_type=risk_assessment").status_code in (401, 403)


def test_future_timestamp_output_is_skipped_in_lists_and_422_on_fetch(client, H, db, org):
    bad = _risk(db, org, assessed_at=datetime.now(timezone.utc) + timedelta(days=30))
    good = _risk(db, org)
    page = client.get(f"{API}/model-outputs?output_type=risk_assessment", headers=H("viewer")).json()
    assert page["skipped_invalid"] == 1 and [i["output_id"] for i in page["items"]] == [good.id]
    assert client.get(f"{API}/model-outputs/risk_assessment/{bad.id}", headers=H("viewer")).status_code == 422


# --------------------------- scoring and review -------------------------
@pytest.fixture()
def assessment(db, org, seeded_users):
    return assessment_service.create_assessment(
        db, organization_id=org.id, title="Perimeter pattern", question="Is the pattern anomalous?",
        author_user_id=seeded_users["analyst"].id, information_gaps=["no camera coverage", "sensor offline"], confidence_level="low")


def _event(db, org, source, **kw):
    d = dict(organization_id=org.id, source_id=source.id, event_type="perimeter_motion", title="E",
             observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc), data_origin="user_upload")
    d.update(kw)
    e = Event(**d)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def test_score_exposes_factors_distinct_concepts_and_limitations(client, H, db, org, source, assessment):
    low = DataSource(organization_id=org.id, name="Weak", source_type="synthetic_generator", status="active", reliability_weight=0.3, config_metadata={})
    db.add(low)
    db.commit()
    e1, e2 = _event(db, org, source, data_origin="synthetic_demo"), _event(db, org, low)
    db.add(Conflict(organization_id=org.id, event_a_id=e1.id, event_b_id=e2.id, conflicting_fields=["event_type"], conflict_rule_version="1", review_status="unresolved"))
    note = Evidence(organization_id=org.id, evidence_type="analyst_note", title="note", content="x")
    db.add(note)
    db.commit()
    assessment_service.link_evidence(db, organization_id=org.id, assessment=assessment, role="supporting", event_id=e1.id)
    assessment_service.link_evidence(db, organization_id=org.id, assessment=assessment, role="contradicting", event_id=e2.id)
    assessment_service.link_evidence(db, organization_id=org.id, assessment=assessment, role="contradicting", evidence_id=note.id)

    r = client.post(f"{API}/assessments/{assessment.id}/score", json={}, headers=H("analyst"))
    assert r.status_code == 201, r.text
    s = r.json()
    pts = {f["key"]: f["points"] for f in s["factors"]}
    assert pts == {"contradicting_evidence": 20, "unresolved_conflicts": 12, "information_gaps": 8, "no_supporting_evidence": 0, "analyst_confidence": 10}
    assert s["score"] == 50 and s["priority_band"] == "high" and "0-100" in s["score_scale"]
    assert s["rule_key"] == "review_priority_v1" and s["rule_version"] == "1" and s["assessment_version"] == 1
    assert len(s["evidence_considered"]) == 3 and s["conflicts"][0]["conflicting_fields"] == ["event_type"]
    codes = {l["code"] for l in s["data_quality_limitations"]}
    assert {"synthetic_demo_events", "low_reliability_sources", "evidence_without_integrity_hash"} <= codes
    dc = s["distinct_concepts"]
    assert set(dc) == {"model_confidence", "evidence_quality", "source_reliability", "uncertainty", "assessment_priority"}
    assert dc["model_confidence"]["available"] is False
    assert dc["source_reliability"]["min"] == 0.3 and dc["assessment_priority"]["score"] == 50
    assert any(m["description"] == "no camera coverage" for m in s["missing_information"])
    assert "Advisory only" in s["advisory_notice"]


def test_no_evidence_scores_missing_support_and_re_scoring_appends(client, H, db, assessment):
    first = client.post(f"{API}/assessments/{assessment.id}/score", json={}, headers=H("investigator")).json()
    assert {f["key"]: f["points"] for f in first["factors"]}["no_supporting_evidence"] == 15
    assert any(l["code"] == "no_evidence_linked" for l in first["data_quality_limitations"])
    second = client.post(f"{API}/assessments/{assessment.id}/score", json={"config_overrides": {"gap_points_each": 1}}, headers=H("analyst")).json()
    assert second["id"] != first["id"] and second["rule_config"]["gap_points_each"] == 1.0
    history = client.get(f"{API}/assessments/{assessment.id}/scores", headers=H("viewer")).json()
    assert {h["id"] for h in history} == {first["id"], second["id"]}
    assert first["rule_config"]["gap_points_each"] == 4.0  # earlier snapshot untouched


def test_scoring_permissions_validation_and_audit(client, H, db, assessment):
    assert client.post(f"{API}/assessments/{assessment.id}/score", json={}, headers=H("viewer")).status_code == 403
    assert client.post(f"{API}/assessments/{assessment.id}/score", json={"rule_key": "threat_v9"}, headers=H("analyst")).status_code == 422
    assert client.post(f"{API}/assessments/{assessment.id}/score", json={"config_overrides": {"gap_points_each": 999}}, headers=H("analyst")).status_code == 422
    assert client.post(f"{API}/assessments/nope/score", json={}, headers=H("analyst")).status_code == 404
    client.post(f"{API}/assessments/{assessment.id}/score", json={}, headers=H("analyst"))
    assert db.query(AuditRecord).filter_by(action="assessment.score", target_id=assessment.id).count() == 1
    rules = client.get(f"{API}/assessment-scoring-rules", headers=H("viewer")).json()
    assert "review_priority_v1" in rules["rules"] and "analyst_confidence_level" in rules["allowed_inputs"]


def test_review_flow_history_comparison_and_audit(client, H, db, assessment):
    snap = client.post(f"{API}/assessments/{assessment.id}/score", json={}, headers=H("analyst")).json()  # score 4+4... band computed
    r1 = client.post(f"{API}/assessments/{assessment.id}/reviews", headers=H("investigator"), json={
        "decision": "further_review_requested", "notes": "Needs camera logs", "information_flags": ["insufficient_information", "insufficient_information"]})
    assert r1.status_code == 201, r1.text
    v1 = r1.json()
    assert v1["information_flags"] == ["insufficient_information"] and v1["supersedes_review_id"] is None
    assert v1["score_snapshot_id"] == snap["id"] and v1["advisory_score_at_review"] == snap["score"]

    no_reason = client.post(f"{API}/assessments/{assessment.id}/reviews", headers=H("analyst"), json={"decision": "accepted", "notes": "ok"})
    assert no_reason.status_code == 400 and "change_reason" in no_reason.json()["detail"]
    v2 = client.post(f"{API}/assessments/{assessment.id}/reviews", headers=H("analyst"), json={
        "decision": "rejected", "notes": "Logs show maintenance", "change_reason": "New logs received", "information_flags": ["conflicting_information"]}).json()
    assert v2["supersedes_review_id"] == v1["id"]
    same = client.post(f"{API}/assessments/{assessment.id}/reviews", headers=H("analyst"), json={"decision": "rejected", "notes": "Confirmed again"})
    assert same.status_code == 201  # unchanged decision needs no reason

    summary = client.get(f"{API}/assessments/{assessment.id}/reviews", headers=H("viewer")).json()
    assert summary["review_status"] == "rejected" and len(summary["history"]) == 3
    assert [h["decision"] for h in summary["history"]] == ["further_review_requested", "rejected", "rejected"]
    cmp = summary["comparison"]
    assert cmp["available"] and cmp["human_decision"] == "rejected" and cmp["advisory_band_at_review"] == snap["priority_band"]
    assert cmp["review_is_for_current_version"] is True and cmp["note"]
    assert summary["latest_score"]["id"] == snap["id"]
    assert db.query(AuditRecord).filter_by(action="assessment.review", target_id=assessment.id).count() == 3
    assert db.get(Assessment, assessment.id).status == "draft"  # a decision never changes workflow state


def test_comparison_flags_disagreement_between_model_and_human(client, H, db, assessment):
    client.post(f"{API}/assessments/{assessment.id}/score", json={"config_overrides": {"confidence_points": {"low": 50}, "gap_points_each": 10}}, headers=H("analyst"))
    client.post(f"{API}/assessments/{assessment.id}/reviews", headers=H("analyst"), json={"decision": "accepted", "notes": "Looks fine to me"})
    cmp = client.get(f"{API}/assessments/{assessment.id}/reviews", headers=H("viewer")).json()["comparison"]
    assert cmp["advisory_band_at_review"] == "high" and cmp["expected_by_band"] == "further_review_requested"
    assert cmp["agreement"] is False and "human decision governs" in cmp["note"]


def test_review_before_any_score_and_after_assessment_changes(client, H, db, assessment, seeded_users):
    r = client.post(f"{API}/assessments/{assessment.id}/reviews", headers=H("analyst"), json={"decision": "accepted", "notes": "fine"}).json()
    assert r["advisory_score_at_review"] is None and r["score_snapshot_id"] is None
    assessment_service.update_assessment(db, assessment, actor_user_id=seeded_users["analyst"].id, summary="new text")
    summary = client.get(f"{API}/assessments/{assessment.id}/reviews", headers=H("viewer")).json()
    assert summary["current_assessment_version"] == 2 and summary["latest_review"]["assessment_version"] == 1
    assert summary["comparison"]["review_is_for_current_version"] is False
    assert summary["comparison"]["agreement"] is None and "No advisory score" in summary["comparison"]["note"]


def test_review_permissions_validation_and_archived(client, H, db, assessment, seeded_users):
    body = {"decision": "accepted", "notes": "ok"}
    assert client.post(f"{API}/assessments/{assessment.id}/reviews", json=body, headers=H("viewer")).status_code == 403
    assert client.post(f"{API}/assessments/{assessment.id}/reviews", json=body).status_code in (401, 403)
    for bad in ({"decision": "maybe", "notes": "x"}, {"decision": "accepted", "notes": "   "}, {"decision": "accepted"},
                {"decision": "accepted", "notes": "x", "information_flags": ["suspicious"]}):
        assert client.post(f"{API}/assessments/{assessment.id}/reviews", json=bad, headers=H("analyst")).status_code == 422
    assert client.post(f"{API}/assessments/{assessment.id}/reviews", json={**body, "score_snapshot_id": "nope"}, headers=H("analyst")).status_code == 400
    assert client.post(f"{API}/assessments/nope/reviews", json=body, headers=H("analyst")).status_code == 404
    uid = seeded_users["analyst"].id
    for st in ("in_review", "published", "archived"):
        assessment_service.update_assessment(db, assessment, actor_user_id=uid, status=st)
    arch = client.post(f"{API}/assessments/{assessment.id}/reviews", json=body, headers=H("analyst"))
    assert arch.status_code == 400 and "archived" in arch.json()["detail"]


def test_snapshot_from_another_assessment_is_rejected(client, H, db, org, assessment, seeded_users):
    other = assessment_service.create_assessment(db, organization_id=org.id, title="Other", question="Q?", author_user_id=seeded_users["analyst"].id)
    snap = client.post(f"{API}/assessments/{other.id}/score", json={}, headers=H("analyst")).json()
    r = client.post(f"{API}/assessments/{assessment.id}/reviews", json={"decision": "accepted", "notes": "x", "score_snapshot_id": snap["id"]}, headers=H("analyst"))
    assert r.status_code == 400


def test_scoring_and_review_org_isolation(client, H, assessment, other_org_headers):
    hdr, _ = other_org_headers
    assert client.post(f"{API}/assessments/{assessment.id}/score", json={}, headers=hdr).status_code == 404
    assert client.post(f"{API}/assessments/{assessment.id}/reviews", json={"decision": "accepted", "notes": "x"}, headers=hdr).status_code == 404
    assert client.get(f"{API}/assessments/{assessment.id}/reviews", headers=hdr).status_code == 404
    assert client.get(f"{API}/assessments/{assessment.id}/scores", headers=hdr).status_code == 404
