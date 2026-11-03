"""Experiment tracking, baselines and comparison.

Execution model (stated honestly): evaluations run SYNCHRONOUSLY inside the API
process, exactly like the existing Phase 4/10 evaluations they reuse. Therefore
only three run states exist -- running, succeeded, failed. There is no queue, so
no "queued"; a synchronous call cannot be pre-empted, so no "cancelled" or
"timed_out". Cost is bounded instead by hard caps on sample counts. A run left
in "running" because the process died is marked failed ("interrupted") by
``reap_stale_runs``.

Reuse, not duplication: detection runs call the Phase 4 evaluation service and
classification runs call the Phase 10 evaluation service, so those tables and
views stay populated. The ExperimentRun is the unified ledger that adds
fingerprints, reproducibility metadata, idempotency, status and comparison.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analytics import metrics as analytics_metrics
from app.core.config import get_settings
from app.core.errors import (
    ArtifactUnavailable,
    IncompatibleComparison,
    MlopsConflict,
    MlopsNotFound,
    MlopsValidationError,
    ResourceLimitExceeded,
    classify_exception,
    scrub,
)
from app.core.logging_config import job_id_var
from app.core.obs_metrics import registry as metrics_registry
from app.cv import coco_eval, synthetic_eval_fixture
from app.mlops import artifacts, compare, fingerprint
from app.models.mlops import ExperimentBaseline, ExperimentRun
from app.models.model_record import ModelRecord
from app.schemas.analytics import ClassificationEvaluationRequest, EvaluationSample
from app.schemas.mlops import ExperimentCreate
from app.services import (
    audit_service,
    classification_evaluation_service,
    evaluation_service,
    mlops_signal_service,
)
from app.services.timeutil import ensure_utc

log = logging.getLogger("aegis.mlops.experiments")
DETECTION_FIXTURE = "synthetic_single_rectangle_fixture@1.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------ preparation ---
def _prepare(model: ModelRecord, payload: ExperimentCreate) -> dict:
    s = get_settings()
    if payload.detection is not None:
        if model.task_type != "object_detection":
            raise MlopsValidationError("This model version is not an object_detection model")
        d = payload.detection
        if d.fixture == evaluation_service.REAL_DATASET_NAME:
            return _prepare_real_detection(d)
        if d.sample_count > s.MLOPS_MAX_DETECTION_FIXTURE_SAMPLES:
            raise ResourceLimitExceeded(f"sample_count is limited to {s.MLOPS_MAX_DETECTION_FIXTURE_SAMPLES} for the synthetic detection fixture")
        config = {"task": "object_detection", "fixture": d.fixture, "sample_count": d.sample_count, "iou_match_threshold": d.iou_match_threshold}
        dataset_fp = fingerprint.fingerprint({"fixture": d.fixture, "sample_count": d.sample_count, "image_size": synthetic_eval_fixture.IMAGE_SIZE,
                                              "generator": "numpy RandomState(seed=sample_index)"})
        return {
            "task": "object_detection", "mode": "adapter_inference_on_fixture", "config": config, "dataset_fp": dataset_fp,
            "dataset_name": evaluation_service.SYNTHETIC_DATASET_NAME, "dataset_version": evaluation_service.SYNTHETIC_DATASET_VERSION,
            "is_synthetic": True, "sample_count": d.sample_count, "seed": "fixed: numpy RandomState(seed=sample_index) per sample",
            "fixture_version": d.fixture,
            "methodology": ("The registered adapter is run on a deterministic SYNTHETIC fixture (one filled rectangle per image). Predictions are matched "
                            "to ground truth by class and IoU >= the configured threshold; precision/recall/F1 are computed from the matched/unmatched counts."),
            "limitations": ["Synthetic geometric fixture: results describe pipeline correctness, NOT real-world detection accuracy.",
                            "One ground-truth object per image; extra predictions on the same image count as false positives.",
                            "Intervals assume independent samples."],
        }
    c = payload.classification
    assert c is not None
    if model.task_type != "classification":
        raise MlopsValidationError("This model version is not a classification model")
    if len(c.samples) > s.MLOPS_MAX_EVAL_SAMPLES:
        raise ResourceLimitExceeded(f"at most {s.MLOPS_MAX_EVAL_SAMPLES} samples are accepted per experiment")
    true_labels = [x.true_label for x in c.samples]
    preds = [x.predicted_label for x in c.samples]
    probs = [x.positive_probability for x in c.samples]
    try:  # validate scoring inputs BEFORE any record is created, so bad input never leaves a run behind
        report = analytics_metrics.classification_report(true_labels, preds, c.labels)
        if c.positive_label and c.positive_label not in report["labels"]:
            raise analytics_metrics.MetricInputError("positive_label must be one of the labels")
        if any(p is not None for p in probs):
            analytics_metrics.probability_report(true_labels, probs, c.positive_label)
    except analytics_metrics.MetricInputError as exc:
        raise MlopsValidationError(str(exc)) from exc
    labels = report["labels"]
    config = {"task": "classification", "labels": labels, "positive_label": c.positive_label, "sample_count": len(c.samples),
              "probabilities_supplied": any(p is not None for p in probs),
              "predictions_fingerprint": fingerprint.fingerprint([[x.sample_ref, x.predicted_label, x.positive_probability] for x in c.samples])}
    return {
        "task": "classification", "mode": "scored_submitted_predictions", "config": config,
        "dataset_fp": fingerprint.fingerprint({"name": c.dataset_name, "version": c.dataset_version, "labelled": [[x.sample_ref, x.true_label] for x in c.samples]}),
        "dataset_name": c.dataset_name, "dataset_version": c.dataset_version, "is_synthetic": c.is_synthetic, "sample_count": len(c.samples),
        "seed": "not applicable (no random component)", "fixture_version": f"{c.dataset_name}@{c.dataset_version}",
        "methodology": ("AEGIS scores the PREDICTIONS the caller submitted against the submitted ground-truth labels; it does not execute the classifier. "
                        "Metrics come from the shared analytics metric implementation; undefined metrics are reported as undefined, never 0."),
        "limitations": ["The system cannot verify that the submitted predictions were produced by the registered model version.",
                        "Intervals assume independent samples and a representative dataset."]
                       + (["The dataset is declared SYNTHETIC; results are not evidence of real-world performance."] if c.is_synthetic else []),
        "legacy_request": c,
    }


def _prepare_real_detection(d) -> dict:
    try:
        manifest = coco_eval.load_manifest()
    except coco_eval.DatasetUnavailable as exc:
        raise MlopsValidationError(str(exc)) from exc
    images = manifest["images"][: d.sample_count]
    config = {"task": "object_detection", "fixture": d.fixture, "sample_count": len(images), "iou_match_threshold": d.iou_match_threshold}
    return {
        "task": "object_detection", "mode": "adapter_inference_on_real_images", "config": config,
        "dataset_fp": fingerprint.fingerprint({"dataset": manifest["dataset_version"], "images": [im["sha256"] for im in images]}),
        "dataset_name": manifest["dataset_name"], "dataset_version": manifest["dataset_version"],
        "is_synthetic": False, "sample_count": len(images), "seed": manifest.get("sampling"), "fixture_version": f"{manifest['dataset_name']}@{manifest['dataset_version']}",
        "methodology": ("The registered adapter is run on REAL COCO val2017 photographs (each verified against its recorded SHA-256); predictions "
                        "pass through production postprocessing and are matched per class (person, vehicle) at the IoU threshold; crowd regions "
                        "are ignored; AP is 101-point interpolated."),
        "limitations": ["A small public benchmark sample (COCO photographs), not data from any operational setting.",
                        "Only the person and vehicle classes are scored.",
                        "Intervals assume independent samples."],
    }


# -------------------------------------------------------------- execution ---
def reap_stale_runs(db: Session, organization_id: str) -> int:
    cutoff = _now() - timedelta(seconds=get_settings().MLOPS_STALE_RUN_SECONDS)
    stale = db.execute(select(ExperimentRun).where(ExperimentRun.organization_id == organization_id, ExperimentRun.status == "running", ExperimentRun.started_at < cutoff)).scalars().all()
    for r in stale:
        r.status, r.error_category = "failed", "interrupted"
        r.error_message = "The run did not finish (the process may have restarted) and was marked failed."
        r.completed_at = _now()
        r.duration_ms = (r.completed_at - ensure_utc(r.started_at)).total_seconds() * 1000
        mlops_signal_service.raise_signal(
            db, organization_id=organization_id, category="evaluation_failed", severity="warning", dedup_key=f"evaluation_failed:{r.model_record_id}",
            title="Evaluation run interrupted", summary="An evaluation run was left in 'running' and was marked failed.", model_record_id=r.model_record_id,
            experiment_run_id=r.id, subsystem="experiments", evidence={"error_category": "interrupted"})
    if stale:
        db.flush()
    return len(stale)


def _find_by_key(db: Session, organization_id: str, key: str) -> Optional[ExperimentRun]:
    return db.execute(select(ExperimentRun).where(ExperimentRun.organization_id == organization_id, ExperimentRun.idempotency_key == key)).scalar_one_or_none()


def create_run(db: Session, *, organization_id: str, user_id: str, model: ModelRecord, payload: ExperimentCreate, request_id: Optional[str]) -> tuple[ExperimentRun, bool]:
    """Returns (run, replayed). `replayed` means an earlier run with the same
    idempotency key and identical inputs was returned and nothing new ran."""
    if model.lifecycle_state == "archived":
        raise MlopsConflict("Archived model versions cannot be evaluated")
    reap_stale_runs(db, organization_id)
    prep = _prepare(model, payload)
    config_fp = fingerprint.fingerprint(prep["config"])
    run_fp = fingerprint.fingerprint({"model": model.id, "artifact_digest": model.artifact_digest, "config": config_fp, "dataset": prep["dataset_fp"], "metrics": compare.METRIC_IMPL_VERSION})
    if payload.idempotency_key:
        prior = _find_by_key(db, organization_id, payload.idempotency_key)
        if prior is not None:
            if prior.run_fingerprint != run_fp:
                raise MlopsConflict("This idempotency key was already used with a different request")
            return prior, True

    started = _now()
    run = ExperimentRun(
        organization_id=organization_id, model_record_id=model.id, model_version=model.version, task=prep["task"], experiment_name=payload.experiment_name.strip(),
        purpose=payload.purpose, status="running", execution_mode=prep["mode"], idempotency_key=payload.idempotency_key, dataset_name=prep["dataset_name"],
        dataset_version=prep["dataset_version"], is_synthetic=prep["is_synthetic"], dataset_fingerprint=prep["dataset_fp"], config_fingerprint=config_fp,
        run_fingerprint=run_fp, config=prep["config"], methodology=prep["methodology"], limitations=prep["limitations"], sample_count=prep["sample_count"],
        reproducibility=fingerprint.reproducibility_info(seed_description=prep["seed"], fixture_version=prep["fixture_version"], metrics_version=compare.METRIC_IMPL_VERSION,
                                                         artifact_digest=model.artifact_digest),
        initiated_by_user_id=user_id, started_at=started,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = _find_by_key(db, organization_id, payload.idempotency_key) if payload.idempotency_key else None
        if prior is not None and prior.run_fingerprint == run_fp:
            return prior, True
        raise MlopsConflict("This idempotency key was already used with a different request")
    db.refresh(run)
    run_id = run.id
    token = job_id_var.set(run_id)
    t0 = time.monotonic()
    try:
        _execute(db, run, model, prep, user_id)
        run.status = "succeeded"
        run.error_category = run.error_message = None
    except Exception as exc:  # noqa: BLE001 -- every failure becomes a recorded, sanitised failed run
        db.rollback()
        run = db.get(ExperimentRun, run_id)
        category, message = classify_exception(exc)
        log.exception("experiment run failed", extra={"operation": "experiment_run", "job_id": run_id, "error_category": category, "outcome": "failure"})
        run.status, run.error_category, run.error_message = "failed", category, scrub(message, 500)
        run.metrics = None
    finally:
        job_id_var.reset(token)
    run.completed_at = _now()
    run.duration_ms = round((time.monotonic() - t0) * 1000, 3)
    model_obj = db.get(ModelRecord, model.id)
    _signals_after_run(db, run, model_obj, request_id)
    audit_service.record(
        db, action="mlops.experiment.run" if run.status == "succeeded" else "mlops.experiment.failed", actor_user_id=user_id, organization_id=organization_id,
        target_type="experiment_run", target_id=run.id, outcome="success" if run.status == "succeeded" else "failure", request_id=request_id,
        context_metadata={"model_record_id": model.id, "model_version": model.version, "task": run.task, "dataset": f"{run.dataset_name}@{run.dataset_version}",
                          "is_synthetic": run.is_synthetic, "config_fingerprint": run.config_fingerprint, "error_category": run.error_category},
    )
    db.commit()
    db.refresh(run)
    outcome = "succeeded" if run.status == "succeeded" else "failed"
    metrics_registry.inc("mlops_experiment_runs_total", {"task": run.task, "outcome": outcome})
    metrics_registry.observe("mlops_experiment_duration_seconds", {"task": run.task}, (run.duration_ms or 0) / 1000)
    return run, False


def _execute(db: Session, run: ExperimentRun, model: ModelRecord, prep: dict, user_id: str) -> None:
    st = artifacts.check_artifact(model.artifact_reference, model.adapter_key, model.artifact_digest, verify_digest=bool(model.artifact_digest))
    run.reproducibility = {**(run.reproducibility or {}), "artifact_check": st.as_dict()}
    if prep["task"] == "classification":
        # Classification versions may have no artifact at all (AEGIS only scores submitted predictions).
        if model.artifact_reference and not st.available:
            raise ArtifactUnavailable(f"Registered model artifact is unavailable: {st.reason or 'unavailable'}")
    elif not st.available:
        raise ArtifactUnavailable(f"Registered model artifact is unavailable: {st.reason or 'unavailable'}")

    if prep["task"] == "object_detection":
        d = prep["config"]
        legacy = evaluation_service.run_evaluation(
            db, organization_id=run.organization_id, model_record=model, sample_count=d["sample_count"],
            iou_match_threshold=d["iou_match_threshold"], evaluated_by_user_id=user_id,
            dataset=evaluation_service.REAL_DATASET_NAME if d["fixture"] == evaluation_service.REAL_DATASET_NAME else evaluation_service.SYNTHETIC_DATASET_NAME)
        detail = legacy.metrics_detail or {}
        tp, fp, fn = int(detail["true_positives"]), int(detail["false_positives"]), int(detail["false_negatives"])
        run.metrics = compare.detection_metrics(tp, fp, fn, legacy.mean_iou)
        run.source_run_type, run.source_run_id = "model_evaluation_run", legacy.id
        return
    c = prep["legacy_request"]
    req = ClassificationEvaluationRequest(
        model_record_id=model.id, model_version=model.version, dataset_name=c.dataset_name, dataset_version=c.dataset_version, is_synthetic=c.is_synthetic,
        labels=prep["config"]["labels"], positive_label=c.positive_label,
        samples=[EvaluationSample(sample_ref=x.sample_ref, true_label=x.true_label, predicted_label=x.predicted_label, positive_probability=x.positive_probability) for x in c.samples])
    legacy = classification_evaluation_service.run_classification_evaluation(db, organization_id=run.organization_id, req=req, user_id=user_id)
    results = legacy.results
    run.metrics = compare.classification_metrics(results["classification"], results.get("probability"), c.positive_label)
    run.source_run_type, run.source_run_id = "classification_evaluation_run", legacy.id


# ------------------------------------------------------- baselines/compare ---
def get_run(db: Session, organization_id: str, run_id: str) -> ExperimentRun:
    run = db.execute(select(ExperimentRun).where(ExperimentRun.id == run_id, ExperimentRun.organization_id == organization_id)).scalar_one_or_none()
    if run is None:
        raise MlopsNotFound("Experiment run not found")
    return run


def set_baseline(db: Session, *, organization_id: str, user_id: str, run_id: str, reason: Optional[str], request_id: Optional[str]) -> ExperimentBaseline:
    run = get_run(db, organization_id, run_id)
    if run.status != "succeeded":
        raise MlopsConflict("Only a succeeded run can be selected as a baseline")
    row = db.execute(select(ExperimentBaseline).where(
        ExperimentBaseline.organization_id == organization_id, ExperimentBaseline.task == run.task,
        ExperimentBaseline.dataset_name == run.dataset_name, ExperimentBaseline.dataset_version == run.dataset_version)).scalar_one_or_none()
    previous = row.run_id if row else None
    if row is None:
        row = ExperimentBaseline(organization_id=organization_id, task=run.task, dataset_name=run.dataset_name, dataset_version=run.dataset_version,
                                 run_id=run.id, selected_by_user_id=user_id, reason=reason, selected_at=_now())
        db.add(row)
    else:
        row.run_id, row.selected_by_user_id, row.reason, row.selected_at = run.id, user_id, reason, _now()
    audit_service.record(db, action="mlops.baseline.select", actor_user_id=user_id, organization_id=organization_id, target_type="experiment_run",
                         target_id=run.id, request_id=request_id,
                         context_metadata={"task": run.task, "dataset": f"{run.dataset_name}@{run.dataset_version}", "previous_run_id": previous, "reason": reason})
    db.flush()
    return row


def baseline_for(db: Session, organization_id: str, run: ExperimentRun) -> Optional[ExperimentBaseline]:
    return db.execute(select(ExperimentBaseline).where(
        ExperimentBaseline.organization_id == organization_id, ExperimentBaseline.task == run.task,
        ExperimentBaseline.dataset_name == run.dataset_name, ExperimentBaseline.dataset_version == run.dataset_version)).scalar_one_or_none()


def comparison(db: Session, organization_id: str, run_id: str, baseline_run_id: Optional[str]) -> dict:
    run = get_run(db, organization_id, run_id)
    if baseline_run_id:
        base = get_run(db, organization_id, baseline_run_id)
        source = "explicit"
    else:
        b = baseline_for(db, organization_id, run)
        if b is None:
            return {"status": "no_baseline", "candidate_run_id": run.id, "message": "No baseline has been selected for this task and dataset."}
        base, source = get_run(db, organization_id, b.run_id), "selected_baseline"
    if base.id == run.id:
        return {"status": "is_baseline", "candidate_run_id": run.id, "baseline_run_id": base.id, "message": "This run is the selected baseline."}
    result = compare.compare_runs(base, run)  # raises IncompatibleComparison
    sc = min(x for x in (base.sample_count, run.sample_count) if x is not None) if (base.sample_count is not None and run.sample_count is not None) else None
    result.update(status="compared", candidate_run_id=run.id, baseline_run_id=base.id, baseline_source=source,
                  sample_counts={"baseline": base.sample_count, "candidate": run.sample_count},
                  small_sample_warning=(sc is not None and sc < get_settings().MLOPS_MONITOR_MIN_SAMPLES))
    return result


# ------------------------------------------------------------------ signals ---
def _signals_after_run(db: Session, run: ExperimentRun, model: ModelRecord, request_id: Optional[str]) -> None:
    org = run.organization_id
    label = f"{model.name} {model.version}"
    if run.status == "failed":
        mlops_signal_service.raise_signal(
            db, organization_id=org, category="evaluation_failed", severity="warning", dedup_key=f"evaluation_failed:{model.id}",
            title=f"Evaluation failed: {label}", summary=f"An evaluation run failed ({run.error_category}). No metrics were recorded.",
            model_record_id=model.id, experiment_run_id=run.id, subsystem="experiments", evidence={"error_category": run.error_category, "error_message": run.error_message},
            limitations="The failure category is coarse; consult the protected application log (job_id = run id) for detail.", request_id=request_id)
        if run.error_category == "missing_artifact":
            mlops_signal_service.raise_signal(
                db, organization_id=org, category="artifact_unavailable", severity="serious", dedup_key=f"artifact_unavailable:{model.id}",
                title=f"Model artifact unavailable: {label}", summary="An evaluation could not start because the registered artifact is unavailable.",
                model_record_id=model.id, experiment_run_id=run.id, subsystem="model_registry", evidence=(run.reproducibility or {}).get("artifact_check", {}), request_id=request_id)
        return
    ds = f"{run.dataset_name}@{run.dataset_version}"
    for name, m in (run.metrics or {}).items():
        floor = compare.metric_floor(run.task, name)
        if floor is not None and m["defined"] and m["value"] < floor:
            mlops_signal_service.raise_signal(
                db, organization_id=org, category="metric_below_floor", severity="warning", dedup_key=f"metric_below_floor:{model.id}:{ds}:{name}",
                title=f"{name} below configured floor: {label}", summary=f"{name} = {m['value']} is below the configured minimum {floor} on {ds}.",
                model_record_id=model.id, experiment_run_id=run.id, subsystem="experiments", observed_value=m["value"], threshold_value=floor,
                evidence={"metric": name, "n": m.get("n"), "ci95": m.get("ci95"), "dataset": ds, "is_synthetic": run.is_synthetic},
                limitations="Measured on the stated dataset only." + (" The dataset is synthetic." if run.is_synthetic else ""), request_id=request_id)
    b = baseline_for(db, org, run)
    if b is None or b.run_id == run.id:
        return
    base = db.get(ExperimentRun, b.run_id)
    if base is None:
        return
    try:
        result = compare.compare_runs(base, run)
    except IncompatibleComparison:
        return
    for row in result["metrics"]:
        if row["exceeds_review_threshold"]:
            drop = abs(row["absolute_difference"])
            mlops_signal_service.raise_signal(
                db, organization_id=org, category="metric_regression", severity="serious" if drop > 2 * row["review_threshold"] else "warning",
                dedup_key=f"metric_regression:{model.id}:{ds}:{row['metric']}", title=f"{row['metric']} fell versus baseline: {label}",
                summary=(f"{row['metric']} changed by {row['absolute_difference']:+.4f} versus the selected baseline on {ds} "
                         f"(review threshold {row['review_threshold']}). This flags the measurement for review; it does not establish that the model is worse overall."),
                model_record_id=model.id, experiment_run_id=run.id, subsystem="experiments", observed_value=row["candidate"]["value"],
                threshold_value=row["baseline"]["value"] - row["review_threshold"] if row["direction"] == "higher_is_better" else row["baseline"]["value"] + row["review_threshold"],
                evidence={"baseline_run_id": base.id, "row": row, "sample_counts": {"baseline": base.sample_count, "candidate": run.sample_count}},
                limitations="Compared on identical dataset fingerprints; differences smaller than the sampling interval may be noise.", request_id=request_id)


def scan_staleness(db: Session, organization_id: str, request_id: Optional[str] = None) -> dict:
    """Explicit, idempotent scan (no scheduler exists): raises evaluation_stale
    for approved/registered versions whose newest succeeded run is old or absent."""
    from app.services.mlops_registry_service import visible_clause

    s = get_settings()
    cutoff = _now() - timedelta(days=s.MLOPS_EVALUATION_STALE_DAYS)
    models = db.execute(select(ModelRecord).where(visible_clause(organization_id), ModelRecord.lifecycle_state.in_(("registered", "review_required", "approved")),
                                                  ModelRecord.task_type.isnot(None)).order_by(ModelRecord.created_at.desc()).limit(500)).scalars().all()
    latest = dict(db.execute(select(ExperimentRun.model_record_id, func.max(ExperimentRun.completed_at)).where(
        ExperimentRun.organization_id == organization_id, ExperimentRun.status == "succeeded",
        ExperimentRun.model_record_id.in_([m.id for m in models] or [""])).group_by(ExperimentRun.model_record_id)).all())
    raised = 0
    for m in models:
        ts = latest.get(m.id)
        if ts is None and m.lifecycle_state != "approved":
            continue  # only an APPROVED version with no evaluation at all is a gap worth flagging
        if ts is None or ensure_utc(ts) < cutoff:
            _, created = mlops_signal_service.raise_signal(
                db, organization_id=organization_id, category="evaluation_stale", severity="warning" if m.lifecycle_state == "approved" else "info",
                dedup_key=f"evaluation_stale:{m.id}", title=f"Evaluation is stale or missing: {m.name} {m.version}",
                summary=("No succeeded evaluation exists for this version." if ts is None else f"The newest succeeded evaluation is older than {s.MLOPS_EVALUATION_STALE_DAYS} days."),
                model_record_id=m.id, subsystem="model_registry", observed_value=None if ts is None else (_now() - ensure_utc(ts)).days,
                threshold_value=float(s.MLOPS_EVALUATION_STALE_DAYS), evidence={"lifecycle_state": m.lifecycle_state, "latest_succeeded_at": ts.isoformat() if ts else None},
                limitations="Staleness is based on run timestamps only.", request_id=request_id)
            raised += int(created)
    return {"models_checked": len(models), "signals_created": raised}


# ------------------------------------------------------------------ queries ---
def list_query(organization_id: str, *, model_record_id: Optional[str] = None, task: Optional[str] = None, status: Optional[str] = None,
               dataset_name: Optional[str] = None):
    stmt = select(ExperimentRun).where(ExperimentRun.organization_id == organization_id)
    if model_record_id:
        stmt = stmt.where(ExperimentRun.model_record_id == model_record_id)
    if task:
        stmt = stmt.where(ExperimentRun.task == task)
    if status:
        stmt = stmt.where(ExperimentRun.status == status)
    if dataset_name:
        stmt = stmt.where(ExperimentRun.dataset_name == dataset_name)
    return stmt.order_by(ExperimentRun.started_at.desc())


def history(db: Session, organization_id: str, *, metric: str, task: str, dataset_name: Optional[str], dataset_version: Optional[str],
            model_record_id: Optional[str], days: int, limit: int = 200) -> dict:
    since = _now() - timedelta(days=days)
    stmt = select(ExperimentRun).where(ExperimentRun.organization_id == organization_id, ExperimentRun.status == "succeeded", ExperimentRun.task == task,
                                       ExperimentRun.started_at >= since)
    if dataset_name:
        stmt = stmt.where(ExperimentRun.dataset_name == dataset_name)
    if dataset_version:
        stmt = stmt.where(ExperimentRun.dataset_version == dataset_version)
    if model_record_id:
        stmt = stmt.where(ExperimentRun.model_record_id == model_record_id)
    runs = db.execute(stmt.order_by(ExperimentRun.started_at.asc()).limit(limit)).scalars().all()
    points, undefined = [], 0
    datasets = set()
    for r in runs:
        m = (r.metrics or {}).get(metric)
        if m is None or not m["defined"]:
            undefined += 1
            continue
        datasets.add((r.dataset_name, r.dataset_version, r.dataset_fingerprint))
        points.append({"run_id": r.id, "at": r.completed_at or r.started_at, "model_record_id": r.model_record_id, "model_version": r.model_version,
                       "value": m["value"], "n": m.get("n"), "ci95": m.get("ci95"), "is_synthetic": r.is_synthetic,
                       "dataset": f"{r.dataset_name}@{r.dataset_version}", "dataset_fingerprint": r.dataset_fingerprint})
    return {"metric": metric, "task": task, "window_days": days, "points": points, "runs_without_this_metric_defined": undefined,
            "comparable_datasets": len(datasets) <= 1,
            "note": "Points from different dataset fingerprints are not directly comparable." if len(datasets) > 1 else None}


def serialize_run(run: ExperimentRun, *, detail: bool) -> dict:
    d = {
        "id": run.id, "model_record_id": run.model_record_id, "model_version": run.model_version, "task": run.task, "experiment_name": run.experiment_name,
        "purpose": run.purpose, "status": run.status, "execution_mode": run.execution_mode, "dataset_name": run.dataset_name, "dataset_version": run.dataset_version,
        "is_synthetic": run.is_synthetic, "dataset_fingerprint": run.dataset_fingerprint, "config_fingerprint": run.config_fingerprint, "run_fingerprint": run.run_fingerprint,
        "started_at": run.started_at, "completed_at": run.completed_at, "duration_ms": run.duration_ms, "metrics": run.metrics, "sample_count": run.sample_count,
        "error_category": run.error_category, "error_message": run.error_message, "initiated_by_user_id": run.initiated_by_user_id,
        "source_run_type": run.source_run_type, "source_run_id": run.source_run_id,
    }
    if detail:
        d.update(config=run.config, methodology=run.methodology, limitations=run.limitations, reproducibility=run.reproducibility, idempotency_key=run.idempotency_key,
                 performance_claim=("SYNTHETIC dataset: these numbers describe behaviour on synthetic data only and are NOT evidence of real-world performance."
                                    if run.is_synthetic else "Performance on the supplied labelled dataset only."))
    return d
