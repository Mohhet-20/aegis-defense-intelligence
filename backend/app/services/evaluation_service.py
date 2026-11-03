"""Model evaluation. Computes real precision/
recall/F1/mean-IoU for one registered model's adapter against a
dataset -- today, always the synthetic fixture in
app/cv/synthetic_eval_fixture.py, because no real labelled operational
dataset exists in this repository yet. Every `ModelEvaluationRun` row
this produces carries `is_synthetic=True` and the exact dataset name/
version/model_record_id+version that produced it, so a metric here is
never mistaken for a real-world accuracy claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cv import coco_eval, synthetic_eval_fixture
from app.cv.adapters.registry import get_adapter
from app.models.model_evaluation_run import ModelEvaluationRun
from app.models.model_record import ModelRecord

SYNTHETIC_DATASET_NAME = "synthetic_single_rectangle_fixture"
SYNTHETIC_DATASET_VERSION = "1.0"
REAL_DATASET_NAME = coco_eval.DATASET_NAME
DATASETS = (SYNTHETIC_DATASET_NAME, REAL_DATASET_NAME)
DEFAULT_IOU_MATCH_THRESHOLD = 0.5


def _iou(a, b) -> float:
    x_min = max(a.x_min, b.x_min)
    y_min = max(a.y_min, b.y_min)
    x_max = min(a.x_max, b.x_max)
    y_max = min(a.y_max, b.y_max)
    inter_w, inter_h = max(0.0, x_max - x_min), max(0.0, y_max - y_min)
    intersection = inter_w * inter_h
    area_a = (a.x_max - a.x_min) * (a.y_max - a.y_min)
    area_b = (b.x_max - b.x_min) * (b.y_max - b.y_min)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


class _PredBox:
    __slots__ = ("class_label", "confidence", "x_min", "y_min", "x_max", "y_max")

    def __init__(self, class_label, confidence, x_min, y_min, x_max, y_max):
        self.class_label, self.confidence = class_label, confidence
        self.x_min, self.y_min, self.x_max, self.y_max = x_min, y_min, x_max, y_max


def run_evaluation(
    db: Session,
    *,
    organization_id: str,
    model_record: ModelRecord,
    sample_count: int = 20,
    iou_match_threshold: float = DEFAULT_IOU_MATCH_THRESHOLD,
    evaluated_by_user_id: Optional[str],
    dataset: str = SYNTHETIC_DATASET_NAME,
) -> ModelEvaluationRun:
    if dataset not in DATASETS:
        raise ValueError(f"dataset must be one of {DATASETS}")
    adapter = get_adapter(model_record.adapter_key)
    if dataset == REAL_DATASET_NAME:
        return _run_real_image_evaluation(db, organization_id=organization_id, model_record=model_record, adapter=adapter,
                                          sample_count=sample_count, iou_match_threshold=iou_match_threshold,
                                          evaluated_by_user_id=evaluated_by_user_id)
    samples = synthetic_eval_fixture.generate(sample_count)

    true_positives = false_positives = false_negatives = 0
    matched_ious: list[float] = []
    per_sample_detail = []

    for sample in samples:
        raw = adapter.predict(sample.image_bgr)
        predictions = sorted(
            [_PredBox(d.class_label, d.confidence, d.x_min, d.y_min, d.x_max, d.y_max) for d in raw],
            key=lambda p: p.confidence, reverse=True,
        )

        gt_matched = False
        best_iou_for_sample = 0.0
        for pred in predictions:
            if pred.class_label != sample.ground_truth.class_label:
                continue
            iou = _iou(pred, sample.ground_truth)
            best_iou_for_sample = max(best_iou_for_sample, iou)
            if not gt_matched and iou >= iou_match_threshold:
                gt_matched = True
                true_positives += 1
                matched_ious.append(iou)
            else:
                false_positives += 1

        if not gt_matched:
            false_negatives += 1

        per_sample_detail.append({"sample_index": sample.index, "best_iou": round(best_iou_for_sample, 4), "ground_truth_matched": gt_matched})

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    mean_iou = sum(matched_ious) / len(matched_ious) if matched_ious else 0.0

    run = ModelEvaluationRun(
        organization_id=organization_id,
        model_record_id=model_record.id,
        dataset_name=SYNTHETIC_DATASET_NAME,
        dataset_version=SYNTHETIC_DATASET_VERSION,
        is_synthetic=True,
        sample_count=sample_count,
        iou_match_threshold=iou_match_threshold,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1, 4),
        mean_iou=round(mean_iou, 4),
        metrics_detail={"per_sample": per_sample_detail, "true_positives": true_positives, "false_positives": false_positives, "false_negatives": false_negatives},
        notes=(
            f"Evaluated model '{model_record.name}' v{model_record.version} (adapter={model_record.adapter_key}) "
            f"against a SYNTHETIC fixture -- not a real-world accuracy measurement. See docs/ml/MODEL_EVALUATION.md."
        ),
        evaluated_by_user_id=evaluated_by_user_id,
        evaluated_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _run_real_image_evaluation(db: Session, *, organization_id: str, model_record: ModelRecord, adapter, sample_count: int,
                               iou_match_threshold: float, evaluated_by_user_id: Optional[str]) -> ModelEvaluationRun:
    """COCO val2017 subset (real photographs). Raises coco_eval.DatasetUnavailable if not installed."""
    result = coco_eval.evaluate(adapter, sample_count=sample_count, iou_threshold=iou_match_threshold)
    overall = result["overall"]
    run = ModelEvaluationRun(
        organization_id=organization_id,
        model_record_id=model_record.id,
        dataset_name=result["dataset_name"],
        dataset_version=result["dataset_version"],
        is_synthetic=False,
        sample_count=result["sample_count"],
        iou_match_threshold=iou_match_threshold,
        # The columns are non-null; an undefined rate (no predictions / no ground truth)
        # is stored as 0.0 here and as null in metrics_detail, which is authoritative.
        precision=round(overall["precision"] or 0.0, 4),
        recall=round(overall["recall"] or 0.0, 4),
        f1_score=round(overall["f1"] or 0.0, 4),
        mean_iou=round(overall["mean_iou_of_matches"] or 0.0, 4),
        metrics_detail={
            "true_positives": overall["tp"], "false_positives": overall["fp"], "false_negatives": overall["fn"],
            "map50": overall["map50"], "per_class": result["per_class"],
            "operating_confidence_threshold": result["operating_confidence_threshold"],
            "mean_inference_ms_per_image": result["mean_inference_ms_per_image"],
            "undefined_rates": [k for k in ("precision", "recall", "f1") if overall[k] is None],
            "protocol": result["protocol"], "source": result["source"],
        },
        notes=(
            f"Evaluated model '{model_record.name}' v{model_record.version} (adapter={model_record.adapter_key}) on "
            f"{result['sample_count']} REAL COCO val2017 photographs ({result['dataset_version']}); classes person and vehicle. "
            "A small public benchmark sample -- not a measurement of performance in any operational setting."
        ),
        evaluated_by_user_id=evaluated_by_user_id,
        evaluated_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, organization_id: str, run_id: str) -> Optional[ModelEvaluationRun]:
    stmt = select(ModelEvaluationRun).where(ModelEvaluationRun.id == run_id, ModelEvaluationRun.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_runs_query(organization_id: str, *, model_record_id: Optional[str] = None):
    stmt = select(ModelEvaluationRun).where(ModelEvaluationRun.organization_id == organization_id)
    if model_record_id:
        stmt = stmt.where(ModelEvaluationRun.model_record_id == model_record_id)
    return stmt.order_by(ModelEvaluationRun.evaluated_at.desc())
