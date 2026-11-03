"""MLOps registry, experiments, comparison, monitoring and review signals.
Authorization is the existing RBAC (`require_permission`); every
record is resolved inside the caller's organization (or is a platform-level
model row), and unknown/foreign ids return the same 404."""
from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, audit_denied, has_permission, require_permission
from app.db.session import get_db
from app.models.mlops import ExperimentBaseline
from app.schemas.common import Page, PageParams
from app.schemas.mlops import (
    BaselineSelect, EventOut, ExperimentCreate, FamilyOut, ModelVersionCreate, RunOut, SignalAcknowledge, SignalOut, SignalPage, SignalResolve, SnapshotCreate,
    SnapshotOut, TransitionRequest, VersionOut,
)
from app.services import (
    audit_service, mlops_experiment_service as exp, mlops_monitoring_service as mon, mlops_registry_service as reg, mlops_signal_service as sig,
)

router = APIRouter(prefix="/mlops", tags=["mlops"])


def _page(db: Session, stmt, page_params: PageParams, mapper: Callable) -> dict:
    size = max(1, min(page_params.page_size, get_settings().MAX_PAGE_SIZE))
    page = max(page_params.page, 1)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.limit(size).offset((page - 1) * size)).scalars().all()
    return {"items": mapper(rows), "total": total, "page": page, "page_size": size}


def _rid(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


# ------------------------------------------------------------------ registry ---
@router.get("/families", response_model=Page[FamilyOut])
def list_families(q: Optional[str] = Query(default=None, max_length=100), page_params: PageParams = Depends(),
                  user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    return reg.list_families(db, user.organization_id, q=q, page=page_params.page, page_size=min(page_params.page_size, get_settings().MAX_PAGE_SIZE))


@router.get("/models", response_model=Page[VersionOut])
def list_models(
    q: Optional[str] = Query(default=None, max_length=100), task: Optional[str] = Query(default=None, pattern="^(object_detection|classification)$"),
    lifecycle_state: Optional[str] = Query(default=None, pattern="^(registered|review_required|approved|deprecated|archived)$"),
    family: Optional[str] = Query(default=None, max_length=200), sort: str = Query(default="created_at", pattern="^(created_at|name|version|lifecycle_state)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"), page_params: PageParams = Depends(),
    user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db),
):
    stmt = reg.versions_query(user.organization_id, q=q, task=task, lifecycle_state=lifecycle_state, family=family, sort=sort, order=order)

    def mapper(rows):
        ev = reg.evaluation_status(db, user.organization_id, [r.id for r in rows])
        return [reg.serialize_version(r, ev.get(r.id), viewer_org=user.organization_id) for r in rows]

    return _page(db, stmt, page_params, mapper)


@router.post("/models", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
def register_model(payload: ModelVersionCreate, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_REGISTER)), db: Session = Depends(get_db)):
    model = reg.register_version(db, organization_id=user.organization_id, user_id=user.id, data=payload.model_dump(), request_id=_rid(request))
    db.commit()
    db.refresh(model)
    return reg.serialize_version(model, None, viewer_org=user.organization_id, include_detail=True)


@router.get("/models/{model_id}", response_model=VersionOut)
def get_model(model_id: str, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    model = reg.require_visible(db, user.organization_id, model_id)
    ev = reg.evaluation_status(db, user.organization_id, [model.id]).get(model.id)
    d = reg.serialize_version(model, ev, viewer_org=user.organization_id, include_detail=True)
    events = db.execute(reg.history_query(model.id).limit(20)).scalars().all()
    d["recent_history"] = [reg.serialize_event(e, user.organization_id) for e in events]
    d["approval_evidence"] = reg.approval_evidence(db, user.organization_id, model)
    d["allowed_actions"] = sorted(a for (st, a) in reg.TRANSITIONS if st == model.lifecycle_state and has_permission(user.role, reg.ACTION_PERMISSION[a]) and has_permission(user.role, Permission.MLOPS_REVIEW))
    d["open_signals"] = db.scalar(select(func.count()).select_from(sig.ReviewSignal).where(sig.ReviewSignal.organization_id == user.organization_id,
                                                                                          sig.ReviewSignal.model_record_id == model.id, sig.ReviewSignal.status != "resolved")) or 0
    return d


@router.get("/models/{model_id}/history", response_model=Page[EventOut])
def model_history(model_id: str, page_params: PageParams = Depends(), user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    model = reg.require_visible(db, user.organization_id, model_id)
    return _page(db, reg.history_query(model.id), page_params, lambda rows: [reg.serialize_event(e, user.organization_id) for e in rows])


@router.post("/models/{model_id}/verify-artifact")
def verify_artifact(model_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_REVIEW)), db: Session = Depends(get_db)):
    model = reg.require_visible(db, user.organization_id, model_id)
    result = reg.verify_artifact(db, organization_id=user.organization_id, user_id=user.id, model=model, request_id=_rid(request))
    db.commit()
    return result


@router.post("/models/{model_id}/transition", response_model=VersionOut)
def transition_model(model_id: str, payload: TransitionRequest, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_REVIEW)), db: Session = Depends(get_db)):
    model = reg.require_visible(db, user.organization_id, model_id)
    needed = reg.ACTION_PERMISSION[payload.action]
    if not has_permission(user.role, needed):
        audit_denied(db, request, user, needed)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {needed.value}")
    reg.transition(db, organization_id=user.organization_id, user_id=user.id, model=model, action=payload.action, reason=payload.reason, request_id=_rid(request))
    db.commit()
    db.refresh(model)
    ev = reg.evaluation_status(db, user.organization_id, [model.id]).get(model.id)
    return reg.serialize_version(model, ev, viewer_org=user.organization_id, include_detail=True)


# --------------------------------------------------------------- experiments ---
@router.post("/experiments", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def create_experiment(payload: ExperimentCreate, request: Request, response: Response, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_RUN)), db: Session = Depends(get_db)):
    model = reg.require_visible(db, user.organization_id, payload.model_record_id)
    run, replayed = exp.create_run(db, organization_id=user.organization_id, user_id=user.id, model=model, payload=payload, request_id=_rid(request))
    if replayed:
        response.status_code = status.HTTP_200_OK
    d = exp.serialize_run(run, detail=True)
    d["replayed"] = replayed
    return d


@router.get("/experiments", response_model=Page[RunOut])
def list_experiments(
    model_record_id: Optional[str] = Query(default=None, max_length=36), task: Optional[str] = Query(default=None, pattern="^(object_detection|classification)$"),
    run_status: Optional[str] = Query(default=None, alias="status", pattern="^(running|succeeded|failed)$"), dataset_name: Optional[str] = Query(default=None, max_length=200),
    page_params: PageParams = Depends(), user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db),
):
    stmt = exp.list_query(user.organization_id, model_record_id=model_record_id, task=task, status=run_status, dataset_name=dataset_name)
    return _page(db, stmt, page_params, lambda rows: [exp.serialize_run(r, detail=False) for r in rows])


@router.get("/experiments/history")
def experiment_history(
    metric: str = Query(max_length=40, pattern="^[a-z0-9_]+$"), task: str = Query(pattern="^(object_detection|classification)$"),
    dataset_name: Optional[str] = Query(default=None, max_length=200), dataset_version: Optional[str] = Query(default=None, max_length=50),
    model_record_id: Optional[str] = Query(default=None, max_length=36), days: int = Query(default=90, ge=1, le=730),
    user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db),
):
    return exp.history(db, user.organization_id, metric=metric, task=task, dataset_name=dataset_name, dataset_version=dataset_version, model_record_id=model_record_id, days=days)


@router.get("/experiments/{run_id}", response_model=RunOut)
def get_experiment(run_id: str, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    return exp.serialize_run(exp.get_run(db, user.organization_id, run_id), detail=True)


@router.get("/experiments/{run_id}/comparison")
def experiment_comparison(run_id: str, baseline_run_id: Optional[str] = Query(default=None, max_length=36),
                          user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    return exp.comparison(db, user.organization_id, run_id, baseline_run_id)


@router.get("/baselines")
def list_baselines(user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    rows = db.execute(select(ExperimentBaseline).where(ExperimentBaseline.organization_id == user.organization_id).order_by(ExperimentBaseline.selected_at.desc()).limit(200)).scalars().all()
    return {"items": [{"id": b.id, "task": b.task, "dataset_name": b.dataset_name, "dataset_version": b.dataset_version, "run_id": b.run_id,
                       "selected_by_user_id": b.selected_by_user_id, "selected_at": b.selected_at, "reason": b.reason} for b in rows]}


@router.put("/baselines")
def select_baseline(payload: BaselineSelect, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_REVIEW)), db: Session = Depends(get_db)):
    b = exp.set_baseline(db, organization_id=user.organization_id, user_id=user.id, run_id=payload.run_id, reason=payload.reason, request_id=_rid(request))
    db.commit()
    return {"id": b.id, "task": b.task, "dataset_name": b.dataset_name, "dataset_version": b.dataset_version, "run_id": b.run_id, "selected_at": b.selected_at}


# ---------------------------------------------------------------- monitoring ---
@router.post("/monitoring/snapshots", status_code=status.HTTP_201_CREATED)
def create_snapshot(payload: SnapshotCreate, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_MONITOR)), db: Session = Depends(get_db)):
    model = reg.require_visible(db, user.organization_id, payload.model_record_id)
    snap, report = mon.create_snapshot(db, organization_id=user.organization_id, user_id=user.id, model=model, payload=payload, request_id=_rid(request))
    db.commit()
    db.refresh(snap)
    return {"snapshot": mon.serialize_snapshot(snap, detail=True), "report": report or None}


@router.get("/monitoring/snapshots", response_model=Page[SnapshotOut])
def list_snapshots(model_record_id: Optional[str] = Query(default=None, max_length=36), kind: Optional[str] = Query(default=None, pattern="^(reference|current)$"),
                   page_params: PageParams = Depends(), user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    return _page(db, mon.list_query(user.organization_id, model_record_id=model_record_id, kind=kind), page_params, lambda rows: [mon.serialize_snapshot(r, detail=False) for r in rows])


@router.get("/monitoring/coverage")
def monitoring_coverage(user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    return mon.coverage_summary(db, user.organization_id)


@router.get("/monitoring/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    return mon.serialize_snapshot(mon.get_snapshot(db, user.organization_id, snapshot_id), detail=True)


@router.get("/monitoring/snapshots/{snapshot_id}/drift")
def snapshot_drift(snapshot_id: str, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    return mon.drift_report(db, user.organization_id, mon.get_snapshot(db, user.organization_id, snapshot_id))


# ------------------------------------------------------------------- signals ---
@router.get("/signals", response_model=SignalPage)
def list_signals(
    sig_status: Optional[str] = Query(default=None, alias="status", pattern="^(open|acknowledged|resolved)$"), category: Optional[str] = Query(default=None, max_length=40),
    severity: Optional[str] = Query(default=None, pattern="^(info|warning|serious|critical)$"), model_record_id: Optional[str] = Query(default=None, max_length=36),
    experiment_run_id: Optional[str] = Query(default=None, max_length=36), page_params: PageParams = Depends(),
    user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db),
):
    stmt = sig.list_query(user.organization_id, status=sig_status, category=category, severity=severity, model_record_id=model_record_id, experiment_run_id=experiment_run_id)
    out = _page(db, stmt, page_params, lambda rows: [sig.serialize(db, r) for r in rows])
    out["counts"] = sig.counts(db, user.organization_id)
    return out


@router.post("/signals/scan")
def scan_signals(request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_MONITOR)), db: Session = Depends(get_db)):
    reaped = exp.reap_stale_runs(db, user.organization_id)
    stale = exp.scan_staleness(db, user.organization_id, _rid(request))
    jobs = mon.scan_job_failures(db, user.organization_id, _rid(request))
    audit_service.record(db, action="mlops.signal.scan", actor_user_id=user.id, organization_id=user.organization_id, request_id=_rid(request),
                         context_metadata={"stale_runs_marked_failed": reaped, **stale, **{f"jobs_{k}": v for k, v in jobs.items()}})
    db.commit()
    return {"stale_runs_marked_failed": reaped, "staleness": stale, "job_failures": jobs}


@router.get("/signals/{signal_id}", response_model=SignalOut)
def get_signal(signal_id: str, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    return sig.serialize(db, sig.get_signal(db, user.organization_id, signal_id))


@router.post("/signals/{signal_id}/acknowledge", response_model=SignalOut)
def acknowledge_signal(signal_id: str, payload: SignalAcknowledge, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_REVIEW)), db: Session = Depends(get_db)):
    s = sig.acknowledge(db, organization_id=user.organization_id, signal_id=signal_id, user_id=user.id, assignee_user_id=payload.assignee_user_id, request_id=_rid(request))
    db.commit()
    return sig.serialize(db, s)


@router.post("/signals/{signal_id}/resolve", response_model=SignalOut)
def resolve_signal(signal_id: str, payload: SignalResolve, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_REVIEW)), db: Session = Depends(get_db)):
    s = sig.resolve(db, organization_id=user.organization_id, signal_id=signal_id, user_id=user.id, notes=payload.notes, request_id=_rid(request))
    db.commit()
    return sig.serialize(db, s)
