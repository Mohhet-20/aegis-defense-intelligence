"""Operational summaries and detailed health.

Everything here is MEASURED from the database or from the in-process metrics
registry; nothing is estimated or filled with placeholder data. Items that do
not exist in this deployment are listed under ``unavailable`` with a reason,
never reported as zero.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.obs_metrics import CATALOG, UNAVAILABLE, estimate_quantile, registry
from app.models.inference_job import InferenceJob
from app.models.mlops import ExperimentRun
from app.models.model_record import ModelRecord
from app.services import health_service, mlops_signal_service
from app.services.mlops_registry_service import visible_clause


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).date().isoformat()


def _daily(rows: list[tuple], days: int) -> list[dict]:
    today = _now().date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    table = {d: {} for d in labels}
    for when, status in rows:
        d = _day(when)
        if d in table:
            table[d][status] = table[d].get(status, 0) + 1
    return [{"date": d, "counts": table[d], "total": sum(table[d].values())} for d in labels]


def request_metrics_summary() -> dict:
    snap = registry.snapshot()
    reqs = snap["http_requests_total"]["series"]
    total = sum(s["value"] for s in reqs)
    by_class: dict[str, float] = {}
    for s in reqs:
        by_class[s["labels"]["status_class"]] = by_class.get(s["labels"]["status_class"], 0) + s["value"]
    hist = snap["http_request_duration_seconds"]
    count = sum(s["count"] for s in hist["series"])
    merged = [0] * len(hist["buckets"])
    for s in hist["series"]:
        merged = [a + b for a, b in zip(merged, s["bucket_counts"])]
    return {
        "scope": "this API process only; resets on restart; not aggregated across workers", "since": datetime.fromtimestamp(registry.started_at, tz=timezone.utc),
        "requests_total": total, "by_status_class": by_class,
        "server_error_rate": round(by_class.get("5xx", 0) / total, 4) if total else None,
        "latency_seconds_upper_bound": {"p50": estimate_quantile(hist["buckets"], merged, count, 0.5), "p95": estimate_quantile(hist["buckets"], merged, count, 0.95), "observations": count,
                                        "note": "Upper bound of the histogram bucket containing the quantile (bucketed, not exact)."},
    }


def summary(db: Session, organization_id: str, days: int) -> dict:
    since = _now() - timedelta(days=days)
    jobs = db.execute(select(InferenceJob.created_at, InferenceJob.status).where(InferenceJob.organization_id == organization_id, InferenceJob.created_at >= since).limit(20000)).all()
    runs = db.execute(select(ExperimentRun.started_at, ExperimentRun.status).where(ExperimentRun.organization_id == organization_id, ExperimentRun.started_at >= since).limit(20000)).all()
    finished = [s for _, s in jobs if s in ("completed", "failed")]
    return {
        "window_days": days,
        "requests": request_metrics_summary() if get_settings().METRICS_ENABLED else {"status": "disabled", "reason": "METRICS_ENABLED=false"},
        "inference_jobs": {"daily": _daily(jobs, days), "total": len(jobs), "failure_rate": round(finished.count("failed") / len(finished), 4) if len(finished) >= get_settings().MLOPS_JOB_MIN_SAMPLES else None,
                           "failure_rate_note": None if len(finished) >= get_settings().MLOPS_JOB_MIN_SAMPLES else "too few finished jobs to report a rate"},
        "experiment_runs": {"daily": _daily(runs, days), "total": len(runs)},
        "review_signals": mlops_signal_service.counts(db, organization_id),
        "unavailable": UNAVAILABLE,
    }


def _alembic_status(db: Session) -> dict:
    try:
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001
        return {"status": "unknown", "detail": "alembic_version table not present (database may have been created without migrations)"}
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        import os

        cfg = Config(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "..", "alembic"))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        return {"status": "current" if current == head else "behind", "current": current, "head": head}
    except Exception:  # noqa: BLE001
        return {"status": "unknown", "current": current, "detail": "could not read migration scripts"}


def detailed_health(db: Session, organization_id: str) -> dict:
    """Deeper than /health/ready and AUTHENTICATED. Runs only cheap probes: it
    never performs model inference."""
    from app.cv.adapters.registry import available_adapter_keys
    from app.mlops import artifacts

    checks = {
        "database": health_service.check_database(db), "media_storage": health_service.check_media_storage(),
        "model_runtime": health_service.check_model_runtime(), "tracker_runtime": health_service.check_tracker_runtime(),
        "sensor_analytics_runtime": health_service.check_sensor_analytics_runtime(),
    }
    models = db.execute(select(ModelRecord).where(visible_clause(organization_id), ModelRecord.lifecycle_state.in_(("registered", "review_required", "approved")),
                                                  ModelRecord.task_type.isnot(None)).limit(100)).scalars().all()
    artifact_rows = []
    for m in models:
        st = artifacts.check_artifact(m.artifact_reference, m.adapter_key, m.artifact_digest, verify_digest=False)
        artifact_rows.append({"model_record_id": m.id, "name": m.name, "version": m.version, "kind": st.kind, "available": st.available, "reason": st.reason})
    unavailable = [r for r in artifact_rows if not r["available"]]
    return {
        "checked_at": _now(),
        "dependencies": {k: "ok" if v else "error" for k, v in checks.items()},
        "migrations": _alembic_status(db),
        "ml_capability": {"adapters_registered": available_adapter_keys(), "model_versions_checked": len(artifact_rows), "artifacts_unavailable": len(unavailable),
                          "artifact_details": artifact_rows[:50], "artifact_storage_root_configured": bool(get_settings().MLOPS_ARTIFACT_ROOT),
                          "note": "Availability only. Digest verification is on-demand per version; no inference is run by this check."},
        "job_queue": {"available": False, "reason": UNAVAILABLE["job_queue_depth"]},
        "metrics": {"enabled": get_settings().METRICS_ENABLED, "catalog": sorted(CATALOG), "max_series_per_metric": registry.max_series},
        "logging": {"format": get_settings().LOG_FORMAT, "redaction": "enabled"},
        "probe_semantics": {"liveness": "GET /api/v1/health/live -- the process responds; touches no dependency.",
                            "readiness": "GET /api/v1/health/ready -- required dependencies are reachable (public, boolean per dependency only).",
                            "detail": "GET /api/v1/observability/health -- this report; authenticated."},
    }
