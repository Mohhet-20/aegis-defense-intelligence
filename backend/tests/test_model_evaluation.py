"""Phase 4, Section 10/17: model evaluation against a clearly-labelled
SYNTHETIC fixture (no real labelled operational dataset exists yet --
see app/cv/synthetic_eval_fixture.py). Every assertion here is about the
evaluation PIPELINE being correct (real IoU matching, real precision/
recall/F1 arithmetic, full traceability) -- never about the mock
adapter's "accuracy," which is not a claim this phase makes.
"""
from __future__ import annotations

from app.services import evaluation_service


def test_evaluation_run_is_traceable_and_flagged_synthetic(db, org, cv_mock_model):
    run = evaluation_service.run_evaluation(db, organization_id=org.id, model_record=cv_mock_model, sample_count=10, evaluated_by_user_id=None)

    assert run.is_synthetic is True
    assert run.dataset_name == evaluation_service.SYNTHETIC_DATASET_NAME
    assert run.dataset_version == evaluation_service.SYNTHETIC_DATASET_VERSION
    assert run.model_record_id == cv_mock_model.id
    assert run.sample_count == 10


def test_evaluation_metrics_are_all_within_0_1(db, org, cv_mock_model):
    run = evaluation_service.run_evaluation(db, organization_id=org.id, model_record=cv_mock_model, sample_count=15, evaluated_by_user_id=None)

    for value in (run.precision, run.recall, run.f1_score, run.mean_iou):
        assert 0.0 <= value <= 1.0


def test_evaluation_is_deterministic_across_runs(db, org, cv_mock_model):
    run1 = evaluation_service.run_evaluation(db, organization_id=org.id, model_record=cv_mock_model, sample_count=8, evaluated_by_user_id=None)
    run2 = evaluation_service.run_evaluation(db, organization_id=org.id, model_record=cv_mock_model, sample_count=8, evaluated_by_user_id=None)

    # Same fixture (deterministic), same deterministic mock adapter ->
    # byte-identical metrics across two separate runs.
    assert (run1.precision, run1.recall, run1.f1_score, run1.mean_iou) == (run2.precision, run2.recall, run2.f1_score, run2.mean_iou)


def test_evaluation_f1_is_the_real_harmonic_mean_of_precision_and_recall(db, org, cv_mock_model):
    run = evaluation_service.run_evaluation(db, organization_id=org.id, model_record=cv_mock_model, sample_count=12, evaluated_by_user_id=None)
    if run.precision + run.recall > 0:
        expected_f1 = round(2 * run.precision * run.recall / (run.precision + run.recall), 4)
        assert run.f1_score == expected_f1
    else:
        assert run.f1_score == 0.0


def test_metrics_detail_carries_per_sample_breakdown(db, org, cv_mock_model):
    run = evaluation_service.run_evaluation(db, organization_id=org.id, model_record=cv_mock_model, sample_count=5, evaluated_by_user_id=None)
    assert len(run.metrics_detail["per_sample"]) == 5
    assert "true_positives" in run.metrics_detail


def test_evaluation_api_requires_evaluation_run_permission(client, tokens, auth_header, cv_mock_model):
    viewer_headers = auth_header(tokens, "viewer")
    response = client.post("/api/v1/evaluation/runs", headers=viewer_headers, json={"model_record_id": cv_mock_model.id, "sample_count": 5})
    assert response.status_code == 403


def test_evaluation_run_and_list_via_api(client, tokens, auth_header, cv_mock_model):
    headers = auth_header(tokens, "analyst")
    response = client.post("/api/v1/evaluation/runs", headers=headers, json={"model_record_id": cv_mock_model.id, "sample_count": 6})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["is_synthetic"] is True

    listing = client.get("/api/v1/evaluation/runs", headers=headers)
    assert listing.status_code == 200
    assert any(r["id"] == run["id"] for r in listing.json()["items"])
