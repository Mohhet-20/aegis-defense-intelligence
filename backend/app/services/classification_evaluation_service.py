"""Labelled-dataset evaluation of a registered model (Phase 10,
Section 3). Wraps the pure functions in app/analytics/metrics.py with
persistence, version checks, and failure handling.

Failure semantics: bad input (MetricInputError / version mismatch) is a
client error and persists NOTHING. An unexpected internal failure rolls
back and persists a `failed` run with no results, so a misleading
success record can never exist.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import metrics
from app.models.classification_evaluation_run import ClassificationEvaluationRun
from app.models.model_evaluation_run import ModelEvaluationRun
from app.models.model_record import ModelRecord
from app.models.tracking_evaluation_run import TrackingEvaluationRun
from app.schemas.analytics import ClassificationEvaluationRequest

log = logging.getLogger("aegis.analytics.evaluation")


class EvaluationInputError(ValueError):
    pass


class EvaluationFailed(RuntimeError):
    def __init__(self, run: ClassificationEvaluationRun):
        super().__init__(run.error_message or "evaluation failed")
        self.run = run


def performance_claim(is_synthetic: bool, dataset_name: str, dataset_version: str) -> str:
    if is_synthetic:
        return (f"SYNTHETIC dataset '{dataset_name}' v{dataset_version}. These numbers describe behaviour on synthetic data only "
                "and are NOT evidence of real-world performance.")
    return (f"Performance on the supplied labelled dataset '{dataset_name}' v{dataset_version} only. It generalizes to other data "
            "only to the extent that dataset is representative of it.")


def run_classification_evaluation(db: Session, *, organization_id: str, req: ClassificationEvaluationRequest, user_id: Optional[str]) -> ClassificationEvaluationRun:
    model = db.get(ModelRecord, req.model_record_id)
    if model is None or model.owner_organization_id not in (None, organization_id):
        raise LookupError("model not found")
    if req.model_version is not None and req.model_version != model.version:
        raise EvaluationInputError(f"model_version '{req.model_version}' does not match the registered version '{model.version}' of this model")

    true_labels = [s.true_label for s in req.samples]
    predicted = [s.predicted_label for s in req.samples]
    probs = [s.positive_probability for s in req.samples]
    has_probs = any(p is not None for p in probs)

    config = {"task": "classification", "metrics_version": metrics.METRICS_VERSION, "labels": req.labels,
              "positive_label": req.positive_label, "probability_metrics": has_probs}
    try:
        label_set = req.labels
        if req.positive_label and label_set and req.positive_label not in label_set:
            raise metrics.MetricInputError("positive_label must be one of the supplied labels")
        report = metrics.classification_report(true_labels, predicted, label_set)
        prob_report = metrics.probability_report(true_labels, probs, req.positive_label) if has_probs else None
        results = {"classification": report, "probability": prob_report}
        defs = {k: metrics.DEFINITIONS[k] for k in ("accuracy", "precision", "recall", "f1", "macro_f1")}
        if has_probs:
            defs.update({k: metrics.DEFINITIONS[k] for k in ("roc_auc", "brier_score", "log_loss")})
        warnings = list(report["warnings"]) + (list(prob_report["warnings"]) if prob_report else [])
        if not has_probs:
            warnings.append("No probabilities were supplied, so Brier score, log loss and ROC-AUC were not computed.")
        run = ClassificationEvaluationRun(
            organization_id=organization_id, model_record_id=model.id, model_version=model.version,
            dataset_name=req.dataset_name, dataset_version=req.dataset_version, dataset_reference=req.dataset_reference,
            is_synthetic=req.is_synthetic, sample_count=len(req.samples), excluded_missing_label=report["excluded_missing_label"],
            evaluation_config=config, metric_definitions=defs, results=results, warnings=warnings,
            status="completed", evaluated_by_user_id=user_id, evaluated_at=datetime.now(timezone.utc),
        )
    except metrics.MetricInputError as exc:
        raise EvaluationInputError(str(exc)) from exc
    except Exception as exc:  # unexpected: record an honest failure, never a partial success
        log.exception("classification evaluation failed unexpectedly")
        db.rollback()
        failed = ClassificationEvaluationRun(
            organization_id=organization_id, model_record_id=model.id, model_version=model.version,
            dataset_name=req.dataset_name, dataset_version=req.dataset_version, dataset_reference=req.dataset_reference,
            is_synthetic=req.is_synthetic, sample_count=len(req.samples), excluded_missing_label=0,
            evaluation_config=config, metric_definitions={}, results=None, warnings=[],
            status="failed", error_message=f"{type(exc).__name__}: evaluation could not be completed", evaluated_by_user_id=user_id,
            evaluated_at=datetime.now(timezone.utc),
        )
        db.add(failed)
        db.commit()
        db.refresh(failed)
        raise EvaluationFailed(failed) from exc
    db.add(run)
    db.flush()
    return run


def get_run(db: Session, organization_id: str, run_id: str) -> Optional[ClassificationEvaluationRun]:
    return db.execute(select(ClassificationEvaluationRun).where(
        ClassificationEvaluationRun.id == run_id, ClassificationEvaluationRun.organization_id == organization_id)).scalar_one_or_none()


def _headline(results: Optional[dict]) -> dict:
    if not results:
        return {}
    c = results["classification"]
    out = {"accuracy": c["accuracy"]["value"], "macro_f1": c["macro_f1"]["value"]}
    if results.get("probability"):
        p = results["probability"]
        out.update(brier_score=p["brier_score"]["value"], log_loss=p["log_loss"]["value"], roc_auc=p["roc_auc"]["value"])
    return out


def overview(db: Session, organization_id: str, *, model_record_id: Optional[str], page: int, page_size: int) -> dict:
    """Unified list across classification, detection and
    tracking evaluation runs, newest first."""
    from sqlalchemy import func
    limit = page * page_size
    rows: list[dict] = []
    total = 0

    def models_for(ids):
        found = {m.id: m for m in db.execute(select(ModelRecord).where(ModelRecord.id.in_(list(ids)))).scalars()} if ids else {}
        return found

    c_stmt = select(ClassificationEvaluationRun).where(ClassificationEvaluationRun.organization_id == organization_id)
    d_stmt = select(ModelEvaluationRun).where(ModelEvaluationRun.organization_id == organization_id)
    if model_record_id:
        c_stmt = c_stmt.where(ClassificationEvaluationRun.model_record_id == model_record_id)
        d_stmt = d_stmt.where(ModelEvaluationRun.model_record_id == model_record_id)
    t_stmt = select(TrackingEvaluationRun).where(TrackingEvaluationRun.organization_id == organization_id)
    for stmt in (c_stmt, d_stmt) + (() if model_record_id else (t_stmt,)):
        total += db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    c_rows = db.execute(c_stmt.order_by(ClassificationEvaluationRun.evaluated_at.desc()).limit(limit)).scalars().all()
    d_rows = db.execute(d_stmt.order_by(ModelEvaluationRun.evaluated_at.desc()).limit(limit)).scalars().all()
    t_rows = [] if model_record_id else db.execute(t_stmt.order_by(TrackingEvaluationRun.evaluated_at.desc()).limit(limit)).scalars().all()
    models = models_for({r.model_record_id for r in c_rows} | {r.model_record_id for r in d_rows})

    for r in c_rows:
        m = models.get(r.model_record_id)
        rows.append({"kind": "classification", "id": r.id, "model_record_id": r.model_record_id, "model_name": m.name if m else None,
                     "model_version": r.model_version, "dataset_name": r.dataset_name, "dataset_version": r.dataset_version,
                     "is_synthetic": r.is_synthetic, "status": r.status, "headline_metrics": _headline(r.results), "evaluated_at": r.evaluated_at})
    for r in d_rows:
        m = models.get(r.model_record_id)
        rows.append({"kind": "detection", "id": r.id, "model_record_id": r.model_record_id, "model_name": m.name if m else None,
                     "model_version": m.version if m else None, "dataset_name": r.dataset_name, "dataset_version": r.dataset_version,
                     "is_synthetic": r.is_synthetic, "status": "completed",
                     "headline_metrics": {"precision": r.precision, "recall": r.recall, "f1_score": r.f1_score, "mean_iou": r.mean_iou}, "evaluated_at": r.evaluated_at})
    for r in t_rows:
        rows.append({"kind": "tracking", "id": r.id, "model_record_id": None, "model_name": r.tracker_key, "model_version": r.tracker_version,
                     "dataset_name": r.dataset_name, "dataset_version": r.dataset_version, "is_synthetic": r.is_synthetic, "status": "completed",
                     "headline_metrics": {"track_precision": r.track_precision, "track_recall": r.track_recall, "identity_switches": r.identity_switches,
                                          "mean_association_iou": r.mean_association_iou}, "evaluated_at": r.evaluated_at})
    def _key(row):
        dt = row["evaluated_at"]
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    rows.sort(key=_key, reverse=True)
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size}
