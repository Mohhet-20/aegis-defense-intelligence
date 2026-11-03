"""Model monitoring.

Only bounded SUMMARIES are stored; submitted rows are processed in memory and
discarded. The report keeps four different things apart and never merges them
into a single "health score":

  data drift            the INPUT distribution differs from the reference window
  prediction drift      the model's OUTPUT distribution differs
  performance           measured accuracy on LABELLED samples differs (only when
                        labels exist in both windows -- labels are never invented)
  operational           inference-job failures / latency (measured from job rows)

Drift is a measurable change, not proof of model failure, malicious activity or
any real-world condition. Features are exactly the ones the caller supplies; the
system derives no attributes about people from them.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    MlopsNotFound,
    MlopsValidationError,
    ResourceLimitExceeded,
)
from app.mlops import stats
from app.models.inference_job import InferenceJob
from app.models.mlops import MonitoringSnapshot
from app.models.model_record import ModelRecord
from app.schemas.mlops import SnapshotCreate
from app.services import audit_service, mlops_signal_service
from app.services.timeutil import ensure_utc

MAX_SNAPSHOTS_PER_MODEL = 500
MAX_SUMMARY_BYTES = 64 * 1024
TOP_K = 20
BINS = 10
OTHER = "__other__"
LEVEL_RANK = {"not_assessable": -1, "no_material_change": 0, "moderate_shift": 1, "large_shift": 2}
DRIFT_NOTE = ("Drift means a measured distribution differs from the reference window. It does not by itself show that the model is wrong, that data was "
              "tampered with, or that anything has changed in the real world.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _infer_schema(records) -> dict:
    kinds: dict[str, set] = {}
    for r in records:
        for k, v in r.features.items():
            if v is None:
                continue
            kinds.setdefault(k, set()).add("numeric" if _is_num(v) else "categorical")
    return {k: ("numeric" if kinds[k] == {"numeric"} else "categorical") for k in kinds}


def _level(value: Optional[float]) -> str:
    s = get_settings()
    if value is None:
        return "not_assessable"
    if value >= s.MLOPS_PSI_ALERT:
        return "large_shift"
    if value >= s.MLOPS_PSI_WARN:
        return "moderate_shift"
    return "no_material_change"


# --------------------------------------------------------------- snapshot ---
def create_snapshot(db: Session, *, organization_id: str, user_id: str, model: ModelRecord, payload: SnapshotCreate, request_id: Optional[str]) -> tuple[MonitoringSnapshot, dict]:
    s = get_settings()
    if len(payload.records) > s.MLOPS_MONITOR_MAX_ROWS:
        raise ResourceLimitExceeded(f"at most {s.MLOPS_MONITOR_MAX_ROWS} records are accepted per snapshot")
    now = _now()
    ws, we = ensure_utc(payload.window_start), ensure_utc(payload.window_end)
    if we > now + timedelta(days=1):
        raise MlopsValidationError("window_end cannot be in the future")
    if we - ws > timedelta(days=366):
        raise MlopsValidationError("a monitoring window may span at most 366 days")
    if db.scalar(select(func.count()).select_from(MonitoringSnapshot).where(MonitoringSnapshot.organization_id == organization_id, MonitoringSnapshot.model_record_id == model.id)) >= MAX_SNAPSHOTS_PER_MODEL:
        raise ResourceLimitExceeded(f"at most {MAX_SNAPSHOTS_PER_MODEL} snapshots are kept per model version")

    ref: Optional[MonitoringSnapshot] = None
    if payload.reference_snapshot_id:
        ref = get_snapshot(db, organization_id, payload.reference_snapshot_id)
        if ref.model_record_id != model.id or ref.kind != "reference":
            raise MlopsValidationError("reference_snapshot_id must be a reference snapshot of the same model version")
    schema = payload.expected_schema or (ref.summary.get("schema") if ref else None) or _infer_schema(payload.records)
    schema_declared = bool(payload.expected_schema or ref)
    if len(schema) > s.MLOPS_MONITOR_MAX_FEATURES:
        raise ResourceLimitExceeded(f"at most {s.MLOPS_MONITOR_MAX_FEATURES} features are monitored per snapshot")
    ref_feats = (ref.summary.get("features") if ref else {}) or {}

    n = len(payload.records)
    violation_rows = 0
    features_out: dict[str, dict] = {}
    for name, kind in schema.items():
        present: list = []
        missing = violations = 0
        for r in payload.records:
            v = r.features.get(name)
            if v is None:
                missing += 1
            elif kind == "numeric":
                if _is_num(v):
                    present.append(float(v))
                else:
                    violations += 1
            else:
                if isinstance(v, float):
                    violations += 1
                else:
                    present.append(str(v))
        entry: dict = {"type": kind, "present": len(present), "missing": missing, "violations": violations}
        if kind == "numeric":
            mean, std = stats.mean_std(present)
            entry.update(mean=mean, std=std, min=min(present) if present else None, max=max(present) if present else None)
            if present:
                rf = ref_feats.get(name)
                edges = rf["edges"] if rf and rf.get("type") == "numeric" and rf.get("edges") else stats.equal_width_edges(min(present), max(present), BINS)
                counts, under, over = stats.bin_counts(present, edges)
                entry.update(edges=[round(e, 10) for e in edges], counts=counts, below_reference_range=under if rf else None, above_reference_range=over if rf else None)
        else:
            c = Counter(present)
            top = c.most_common(TOP_K)
            other = sum(c.values()) - sum(v for _, v in top)
            counts_map = {k: v for k, v in top}
            if other:
                counts_map[OTHER] = other
            entry.update(distinct=len(c), counts=counts_map)
        features_out[name] = entry
    unknown_names = {k for r in payload.records for k in r.features if k not in schema}
    for r in payload.records:
        bad = False
        for k, v in r.features.items():
            if k not in schema and schema_declared:
                bad = True
            elif k in schema and v is not None:
                kind = schema[k]
                if (kind == "numeric" and not _is_num(v)) or (kind == "categorical" and isinstance(v, float)):
                    bad = True
        violation_rows += int(bad)
    unknown_features = sorted(unknown_names)[:20] if schema_declared else []

    labels = [r.predicted_label for r in payload.records if r.predicted_label is not None]
    confs = [r.confidence for r in payload.records if r.confidence is not None]
    pred: dict = {"n_predicted": len(labels), "n_with_confidence": len(confs)}
    if labels:
        c = Counter(labels)
        top = c.most_common(TOP_K)
        counts_map = {k: v for k, v in top}
        other = sum(c.values()) - sum(v for _, v in top)
        if other:
            counts_map[OTHER] = other
        pred["label_counts"] = counts_map
    if confs:
        m, sd = stats.mean_std(confs)
        counts, _, _ = stats.bin_counts(confs, [i / BINS for i in range(BINS + 1)])
        pred["confidence"] = {"mean": m, "std": sd, "min": min(confs), "max": max(confs), "bin_counts": counts}
    both = [(r.true_label, r.predicted_label) for r in payload.records if r.true_label is not None and r.predicted_label is not None]
    labelled = {"n_labelled": len(both), "n_correct": sum(1 for t, p in both if t == p)}

    summary = {"schema": schema, "features": features_out, "prediction": pred, "labelled": labelled, "unknown_features": unknown_features,
               "binned_on_reference": bool(ref), "schema_declared": schema_declared}
    if len(json.dumps(summary, default=str)) > MAX_SUMMARY_BYTES:
        raise ResourceLimitExceeded("the computed summary is too large; reduce the number of features or categories")
    snap = MonitoringSnapshot(
        organization_id=organization_id, model_record_id=model.id, kind=payload.kind, reference_snapshot_id=ref.id if ref else None, window_start=ws, window_end=we,
        sample_count=n, labelled_count=len(both), schema_violation_count=violation_rows, summary=summary, note=payload.note, created_by_user_id=user_id)
    db.add(snap)
    db.flush()
    audit_service.record(db, action="mlops.monitoring.snapshot", actor_user_id=user_id, organization_id=organization_id, target_type="monitoring_snapshot",
                         target_id=snap.id, request_id=request_id,
                         context_metadata={"model_record_id": model.id, "kind": payload.kind, "sample_count": n, "reference_snapshot_id": ref.id if ref else None})
    if n < s.MLOPS_MONITOR_MIN_SAMPLES:
        mlops_signal_service.raise_signal(
            db, organization_id=organization_id, category="insufficient_data", severity="info", dedup_key=f"insufficient_data:{model.id}",
            title=f"Monitoring window has too few samples: {model.name} {model.version}",
            summary=f"A monitoring snapshot contains {n} records; at least {s.MLOPS_MONITOR_MIN_SAMPLES} are needed for a reliable comparison.",
            model_record_id=model.id, snapshot_id=snap.id, subsystem="monitoring", observed_value=float(n), threshold_value=float(s.MLOPS_MONITOR_MIN_SAMPLES),
            evidence={"sample_count": n}, limitations="Drift and performance comparisons are suppressed for small windows.", request_id=request_id)
    report: dict = {}
    if payload.kind == "current" and ref is not None:
        report = evaluate(db, organization_id, snap, model, raise_signals=True, request_id=request_id)
    return snap, report


def get_snapshot(db: Session, organization_id: str, snapshot_id: str) -> MonitoringSnapshot:
    snap = db.execute(select(MonitoringSnapshot).where(MonitoringSnapshot.id == snapshot_id, MonitoringSnapshot.organization_id == organization_id)).scalar_one_or_none()
    if snap is None:
        raise MlopsNotFound("Monitoring snapshot not found")
    return snap


def list_query(organization_id: str, *, model_record_id: Optional[str] = None, kind: Optional[str] = None):
    stmt = select(MonitoringSnapshot).where(MonitoringSnapshot.organization_id == organization_id)
    if model_record_id:
        stmt = stmt.where(MonitoringSnapshot.model_record_id == model_record_id)
    if kind:
        stmt = stmt.where(MonitoringSnapshot.kind == kind)
    return stmt.order_by(MonitoringSnapshot.window_end.desc())


def serialize_snapshot(snap: MonitoringSnapshot, *, detail: bool) -> dict:
    d = {"id": snap.id, "model_record_id": snap.model_record_id, "kind": snap.kind, "reference_snapshot_id": snap.reference_snapshot_id,
         "window_start": snap.window_start, "window_end": snap.window_end, "sample_count": snap.sample_count, "labelled_count": snap.labelled_count,
         "schema_violation_count": snap.schema_violation_count, "note": snap.note, "created_at": snap.created_at}
    if detail:
        d["summary"] = snap.summary
    return d


# ------------------------------------------------------------ operational ---
def job_stats(db: Session, organization_id: str, model_record_id: str, since: datetime, until: datetime) -> dict:
    s = get_settings()
    rows = dict(db.execute(select(InferenceJob.status, func.count()).where(
        InferenceJob.organization_id == organization_id, InferenceJob.model_record_id == model_record_id,
        InferenceJob.created_at >= since, InferenceJob.created_at <= until).group_by(InferenceJob.status)).all())
    finished = rows.get("completed", 0) + rows.get("failed", 0)
    durations = []
    for st, fin in db.execute(select(InferenceJob.started_at, InferenceJob.finished_at).where(
            InferenceJob.organization_id == organization_id, InferenceJob.model_record_id == model_record_id, InferenceJob.status == "completed",
            InferenceJob.started_at.isnot(None), InferenceJob.finished_at.isnot(None), InferenceJob.created_at >= since, InferenceJob.created_at <= until).limit(1000)).all():
        durations.append((ensure_utc(fin) - ensure_utc(st)).total_seconds())
    durations.sort()

    def q(p: float) -> Optional[float]:
        return round(durations[min(len(durations) - 1, int(p * len(durations)))], 4) if durations else None

    return {
        "jobs_by_status": rows, "finished_jobs": finished,
        "failure_rate": round(rows.get("failed", 0) / finished, 4) if finished >= s.MLOPS_JOB_MIN_SAMPLES else None,
        "failure_rate_reason": None if finished >= s.MLOPS_JOB_MIN_SAMPLES else f"fewer than {s.MLOPS_JOB_MIN_SAMPLES} finished jobs in the window; rate not reported",
        "duration_seconds": {"p50": q(0.5), "p95": q(0.95), "sample": len(durations)} if durations else None,
    }


# ---------------------------------------------------------------- report ---
def _counts_psi(ref: dict, cur: dict) -> Optional[float]:
    keys = sorted(set(ref) | set(cur))
    return stats.psi([ref.get(k, 0) for k in keys], [cur.get(k, 0) for k in keys])


def drift_report(db: Session, organization_id: str, snap: MonitoringSnapshot) -> dict:
    s = get_settings()
    now = _now()
    ref = db.get(MonitoringSnapshot, snap.reference_snapshot_id) if snap.reference_snapshot_id else None
    if ref is not None and ref.organization_id != organization_id:
        ref = None
    age_days = (now - ensure_utc(snap.window_end)).total_seconds() / 86400
    out: dict = {
        "snapshot_id": snap.id, "reference_snapshot_id": ref.id if ref else None, "model_record_id": snap.model_record_id,
        "window": {"start": snap.window_start, "end": snap.window_end},
        "freshness": {"age_days": round(age_days, 2), "stale": age_days > s.MLOPS_MONITOR_FRESHNESS_DAYS, "stale_after_days": s.MLOPS_MONITOR_FRESHNESS_DAYS},
        "sample_counts": {"current": snap.sample_count, "reference": ref.sample_count if ref else None,
                          "current_labelled": snap.labelled_count, "reference_labelled": ref.labelled_count if ref else None},
        "thresholds": {"psi_warn": s.MLOPS_PSI_WARN, "psi_alert": s.MLOPS_PSI_ALERT, "min_samples": s.MLOPS_MONITOR_MIN_SAMPLES, "min_labelled": s.MLOPS_MONITOR_MIN_LABELLED},
        "interpretation": [DRIFT_NOTE, "Performance degradation is reported only from labelled samples; without labels it cannot be established."],
    }
    enough = ref is not None and snap.sample_count >= s.MLOPS_MONITOR_MIN_SAMPLES and ref.sample_count >= s.MLOPS_MONITOR_MIN_SAMPLES
    why = ("no reference snapshot is linked" if ref is None else
           f"fewer than {s.MLOPS_MONITOR_MIN_SAMPLES} samples in a window (current {snap.sample_count}, reference {ref.sample_count})")
    # ---- data drift
    dd: dict = {"status": "not_assessable", "reason": None if enough else why, "features": []}
    if enough:
        worst = "no_material_change"
        for name, cur in snap.summary.get("features", {}).items():
            rf = ref.summary.get("features", {}).get(name)
            row: dict = {"feature": name, "type": cur["type"]}
            if rf is None or rf["type"] != cur["type"]:
                row.update(level="not_assessable", reason="feature missing from the reference or its type differs")
            else:
                rm = rf["missing"] / ref.sample_count
                cm = cur["missing"] / snap.sample_count
                row.update(missing_rate_reference=round(rm, 4), missing_rate_current=round(cm, 4), missing_rate_delta=round(cm - rm, 4))
                if cur["type"] == "numeric":
                    value = stats.psi(rf.get("counts", []), cur.get("counts", [])) if rf.get("counts") and cur.get("counts") else None
                else:
                    value = _counts_psi(rf.get("counts", {}), cur.get("counts", {}))
                row.update(psi=round(value, 4) if value is not None else None, level=_level(value))
                if cur["type"] == "numeric":
                    row.update(reference_mean=rf.get("mean"), current_mean=cur.get("mean"),
                               below_reference_range=cur.get("below_reference_range"), above_reference_range=cur.get("above_reference_range"))
                    if not snap.summary.get("binned_on_reference"):
                        row.update(level="not_assessable", psi=None, reason="current snapshot was not binned on the reference's bin edges")
            dd["features"].append(row)
            if LEVEL_RANK[row["level"]] > LEVEL_RANK[worst]:
                worst = row["level"]
        dd["status"] = worst if dd["features"] else "not_assessable"
        if not dd["features"]:
            dd["reason"] = "no features were monitored"
    cur_rate = snap.schema_violation_count / snap.sample_count if snap.sample_count else 0.0
    ref_rate = (ref.schema_violation_count / ref.sample_count) if ref and ref.sample_count else None
    dd["schema_violations"] = {"current_rate": round(cur_rate, 4), "reference_rate": round(ref_rate, 4) if ref_rate is not None else None,
                               "warn_rate": s.MLOPS_SCHEMA_VIOLATION_RATE_WARN,
                               "elevated": cur_rate > s.MLOPS_SCHEMA_VIOLATION_RATE_WARN and (ref_rate is None or cur_rate > ref_rate),
                               "unknown_features": snap.summary.get("unknown_features", [])}
    out["data_drift"] = dd
    # ---- prediction drift
    pd: dict = {"status": "not_assessable", "reason": None if enough else why}
    cp, rp = snap.summary.get("prediction", {}), (ref.summary.get("prediction", {}) if ref else {})
    if enough:
        if not cp.get("label_counts") or not rp.get("label_counts"):
            pd["reason"] = "predictions were not supplied in one of the windows"
        else:
            lp = _counts_psi(rp["label_counts"], cp["label_counts"])
            cpsi = stats.psi(rp["confidence"]["bin_counts"], cp["confidence"]["bin_counts"]) if rp.get("confidence") and cp.get("confidence") else None
            shift = None
            if rp.get("confidence") and cp.get("confidence") and rp["confidence"]["std"]:
                shift = (cp["confidence"]["mean"] - rp["confidence"]["mean"]) / rp["confidence"]["std"]
            levels = [_level(lp)] + ([_level(cpsi)] if cpsi is not None else [])
            pd.update(status=max(levels, key=lambda l: LEVEL_RANK[l]), reason=None, label_psi=round(lp, 4) if lp is not None else None,
                      confidence_psi=round(cpsi, 4) if cpsi is not None else None, confidence_mean_shift_in_reference_sd=round(shift, 3) if shift is not None else None,
                      label_distribution={"reference": rp["label_counts"], "current": cp["label_counts"]})
    out["prediction_drift"] = pd
    # ---- performance on labelled samples
    perf: dict = {"status": "not_assessable"}
    if ref is None:
        perf["reason"] = why
    elif snap.labelled_count < s.MLOPS_MONITOR_MIN_LABELLED or ref.labelled_count < s.MLOPS_MONITOR_MIN_LABELLED:
        perf["reason"] = (f"labelled samples are missing or too few (current {snap.labelled_count}, reference {ref.labelled_count}; need {s.MLOPS_MONITOR_MIN_LABELLED}). "
                          "Performance degradation cannot currently be established.")
    else:
        rl, cl = ref.summary["labelled"], snap.summary["labelled"]
        ra, ca = rl["n_correct"] / rl["n_labelled"], cl["n_correct"] / cl["n_labelled"]
        ri, ci = stats.wilson_interval(rl["n_correct"], rl["n_labelled"]), stats.wilson_interval(cl["n_correct"], cl["n_labelled"])
        status = "no_detectable_change"
        if ri and ci and not stats.intervals_overlap(ri, ci):
            status = "lower" if ca < ra else "higher"
        perf.update(status=status, metric="accuracy", reference={"value": round(ra, 4), "n": rl["n_labelled"], "ci95": [round(x, 4) for x in ri]},
                    current={"value": round(ca, 4), "n": cl["n_labelled"], "ci95": [round(x, 4) for x in ci]},
                    note="Accuracy on labelled samples only; labels may be delayed or unrepresentative. Intervals assume independent samples.")
    out["performance"] = perf
    # ---- operational
    model = db.get(ModelRecord, snap.model_record_id)
    if model is not None and model.task_type == "object_detection":
        out["operational"] = {"status": "measured", **job_stats(db, organization_id, snap.model_record_id, ensure_utc(snap.window_start), ensure_utc(snap.window_end))}
    else:
        out["operational"] = {"status": "not_applicable", "reason": "AEGIS runs inference jobs only for object_detection models, so there are no job measurements for this version."}
    return out


def evaluate(db: Session, organization_id: str, snap: MonitoringSnapshot, model: ModelRecord, *, raise_signals: bool, request_id: Optional[str]) -> dict:
    rep = drift_report(db, organization_id, snap)
    if not raise_signals:
        return rep
    s = get_settings()
    label = f"{model.name} {model.version}"
    lim = "Distribution change only; " + DRIFT_NOTE
    dd, pd, perf, op = rep["data_drift"], rep["prediction_drift"], rep["performance"], rep["operational"]
    if dd["status"] == "large_shift":
        worst = max((f for f in dd["features"] if f.get("psi") is not None), key=lambda f: f["psi"])
        mlops_signal_service.raise_signal(
            db, organization_id=organization_id, category="data_drift", severity="warning", dedup_key=f"data_drift:{model.id}", title=f"Input distribution shift: {label}",
            summary=f"Feature '{worst['feature']}' has PSI {worst['psi']} against the reference window (alert threshold {s.MLOPS_PSI_ALERT}).",
            model_record_id=model.id, snapshot_id=snap.id, subsystem="monitoring", observed_value=worst["psi"], threshold_value=s.MLOPS_PSI_ALERT,
            evidence={"features": [f for f in dd["features"] if f.get("level") == "large_shift"][:10], "sample_counts": rep["sample_counts"]}, limitations=lim, request_id=request_id)
    if pd["status"] == "large_shift":
        v = max(x for x in (pd.get("label_psi"), pd.get("confidence_psi")) if x is not None)
        mlops_signal_service.raise_signal(
            db, organization_id=organization_id, category="prediction_drift", severity="warning", dedup_key=f"prediction_drift:{model.id}", title=f"Prediction distribution shift: {label}",
            summary=f"Output distribution PSI {v} against the reference window (alert threshold {s.MLOPS_PSI_ALERT}).", model_record_id=model.id, snapshot_id=snap.id,
            subsystem="monitoring", observed_value=v, threshold_value=s.MLOPS_PSI_ALERT, evidence={k: pd.get(k) for k in ("label_psi", "confidence_psi", "label_distribution")},
            limitations=lim, request_id=request_id)
    if perf["status"] == "lower":
        mlops_signal_service.raise_signal(
            db, organization_id=organization_id, category="performance_degradation", severity="serious", dedup_key=f"performance_degradation:{model.id}",
            title=f"Measured accuracy lower than reference: {label}",
            summary=f"Accuracy {perf['current']['value']} (n={perf['current']['n']}) vs reference {perf['reference']['value']} (n={perf['reference']['n']}); the 95% intervals do not overlap.",
            model_record_id=model.id, snapshot_id=snap.id, subsystem="monitoring", observed_value=perf["current"]["value"], threshold_value=perf["reference"]["value"],
            evidence=perf, limitations="Measured on labelled samples only; labels may be unrepresentative. Review before drawing conclusions.", request_id=request_id)
    if dd["schema_violations"]["elevated"]:
        mlops_signal_service.raise_signal(
            db, organization_id=organization_id, category="input_schema_violations", severity="warning", dedup_key=f"input_schema_violations:{model.id}",
            title=f"Input schema violations elevated: {label}", summary=f"{dd['schema_violations']['current_rate']:.1%} of records violated the expected schema (warn at {s.MLOPS_SCHEMA_VIOLATION_RATE_WARN:.0%}).",
            model_record_id=model.id, snapshot_id=snap.id, subsystem="monitoring", observed_value=dd["schema_violations"]["current_rate"],
            threshold_value=s.MLOPS_SCHEMA_VIOLATION_RATE_WARN, evidence=dd["schema_violations"], limitations="Counts records that do not match the declared or reference schema.", request_id=request_id)
    if op.get("status") == "measured" and op.get("failure_rate") is not None and op["failure_rate"] >= s.MLOPS_JOB_FAILURE_RATE_THRESHOLD:
        _failure_signal(db, organization_id, model, op, request_id)
    return rep


def _failure_signal(db: Session, organization_id: str, model: ModelRecord, op: dict, request_id: Optional[str]) -> None:
    s = get_settings()
    mlops_signal_service.raise_signal(
        db, organization_id=organization_id, category="job_failure_rate", severity="warning", dedup_key=f"job_failure_rate:{model.id}",
        title=f"Inference job failure rate high: {model.name} {model.version}",
        summary=f"{op['failure_rate']:.0%} of {op['finished_jobs']} finished inference jobs failed (threshold {s.MLOPS_JOB_FAILURE_RATE_THRESHOLD:.0%}).",
        model_record_id=model.id, subsystem="inference", observed_value=op["failure_rate"], threshold_value=s.MLOPS_JOB_FAILURE_RATE_THRESHOLD,
        evidence={"jobs_by_status": op["jobs_by_status"]}, limitations="Operational measurement from job rows; failures may come from bad media rather than the model.", request_id=request_id)


def scan_job_failures(db: Session, organization_id: str, request_id: Optional[str] = None) -> dict:
    s = get_settings()
    until = _now()
    since = until - timedelta(hours=s.MLOPS_JOB_WINDOW_HOURS)
    ids = [mid for (mid,) in db.execute(select(InferenceJob.model_record_id).where(InferenceJob.organization_id == organization_id, InferenceJob.created_at >= since).distinct().limit(200)).all()]
    raised = 0
    for mid in ids:
        model = db.get(ModelRecord, mid)
        if model is None:
            continue
        op = job_stats(db, organization_id, mid, since, until)
        if op["failure_rate"] is not None and op["failure_rate"] >= s.MLOPS_JOB_FAILURE_RATE_THRESHOLD:
            _failure_signal(db, organization_id, model, op, request_id)
            raised += 1
    return {"models_checked": len(ids), "models_over_threshold": raised, "window_hours": s.MLOPS_JOB_WINDOW_HOURS}


def coverage_summary(db: Session, organization_id: str) -> dict:
    from app.services.mlops_registry_service import visible_clause

    s = get_settings()
    models = db.execute(select(ModelRecord).where(visible_clause(organization_id), ModelRecord.lifecycle_state.in_(("registered", "review_required", "approved")),
                                                  ModelRecord.task_type.isnot(None)).order_by(ModelRecord.created_at.desc()).limit(200)).scalars().all()
    ids = [m.id for m in models] or [""]
    latest: dict[tuple, MonitoringSnapshot] = {}
    for sn in db.execute(select(MonitoringSnapshot).where(MonitoringSnapshot.organization_id == organization_id, MonitoringSnapshot.model_record_id.in_(ids))
                         .order_by(MonitoringSnapshot.window_end.desc()).limit(2000)).scalars():
        latest.setdefault((sn.model_record_id, sn.kind), sn)
    items = []
    for m in models:
        cur, ref = latest.get((m.id, "current")), latest.get((m.id, "reference"))
        age = (_now() - ensure_utc(cur.window_end)).total_seconds() / 86400 if cur else None
        status = "no_monitoring" if cur is None else ("stale" if age > s.MLOPS_MONITOR_FRESHNESS_DAYS else "current")
        items.append({"model_record_id": m.id, "name": m.name, "version": m.version, "lifecycle_state": m.lifecycle_state, "coverage": status,
                      "latest_current_snapshot_id": cur.id if cur else None, "latest_current_window_end": cur.window_end if cur else None, "age_days": round(age, 2) if age is not None else None,
                      "has_reference": ref is not None, "latest_sample_count": cur.sample_count if cur else None})
    covered = sum(1 for i in items if i["coverage"] == "current")
    return {"models": items, "models_total": len(items), "models_with_current_monitoring": covered, "freshness_days": s.MLOPS_MONITOR_FRESHNESS_DAYS}
