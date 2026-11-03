"""Phase 13 routes: scenarios, simulation runs, comparison, sensitivity,
synthetic datasets and exports. Everything returned is SIMULATED.

RBAC at the route; organization isolation + investigation access in the
service. Missing, other-org and unauthorized records all return 404."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.scenario import (
    CompareRequest, DatasetRequest, DatasetSummary, RunDetail, RunRequest, RunSummary, ScenarioCreate, ScenarioDuplicate,
    ScenarioOut, ScenarioUpdate, SensitivityRequest, ValidateRequest,
)
from app.services import audit_service
from app.services import scenario_service as svc
from app.simulation import analysis, generator
from app.simulation import simulators as S
from app.simulation import templates as T

READ, WRITE, RUN = Permission.SCENARIO_READ, Permission.SCENARIO_WRITE, Permission.SCENARIO_RUN
router = APIRouter(tags=["scenarios"])


def _audit(db: Session, request: Request, user: AuthenticatedUser, action: str, target_type: str, target_id: Optional[str],
           outcome: str = "success", **meta) -> None:
    audit_service.record(db, action=action, actor_user_id=user.id, organization_id=user.organization_id, target_type=target_type,
                         target_id=target_id, outcome=outcome, request_id=getattr(request.state, "request_id", None), context_metadata=meta)


def _run_detail(run, replay: bool = False) -> RunDetail:
    d = RunDetail.model_validate(run)
    d.idempotent_replay = replay
    return d


# ------------------------------------------------------------- discovery

@router.get("/simulation/simulators")
def simulators(user: AuthenticatedUser = Depends(require_permission(READ))):
    return {"synthetic": True, "simulators": [s.doc() for s in S.REGISTRY.values()], "generator": generator.generator_docs(),
            "limits": {"max_sweep_params": analysis.MAX_SWEEP_PARAMS, "max_sweep_values": analysis.MAX_VALUES,
                       "max_repetitions": analysis.MAX_REPS, "max_total_runs": analysis.MAX_TOTAL_RUNS,
                       "max_generated_records": generator.MAX_RECORDS},
            "not_implemented": ["model-evaluation comparisons", "assessment-parameter what-ifs", "run cancellation", "background execution"]}


@router.get("/simulation/templates")
def templates(user: AuthenticatedUser = Depends(require_permission(READ))):
    return {"templates": T.list_templates()}


# ------------------------------------------------------------- scenarios

@router.post("/scenarios/validate")
def validate(payload: ValidateRequest, user: AuthenticatedUser = Depends(require_permission(WRITE))):
    return svc.validate_config(payload.simulator_id, payload.params, payload.execution_config)


@router.post("/scenarios", response_model=ScenarioOut, status_code=201)
def create(payload: ScenarioCreate, request: Request, user: AuthenticatedUser = Depends(require_permission(WRITE)),
           db: Session = Depends(get_db)):
    sc = svc.create_scenario(db, user, payload.model_dump())
    _audit(db, request, user, "scenario.create", "scenario", sc.id, simulator_id=sc.simulator_id, template_id=sc.template_id)
    db.commit()
    return sc


@router.get("/scenarios", response_model=Page[ScenarioOut])
def list_scenarios(status: Optional[str] = Query(None, pattern="^(draft|ready|archived)$"), category: Optional[str] = Query(None, max_length=60),
                   simulator_id: Optional[str] = Query(None, max_length=60), q: Optional[str] = Query(None, max_length=100),
                   latest_only: bool = False, investigation_id: Optional[str] = Query(None, max_length=36),
                   page: int = Query(1, ge=1, le=1000), page_size: int = Query(20, ge=1, le=100),
                   user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    stmt = svc.list_query(db, user, status=status, category=category, simulator_id=simulator_id, q=q, latest_only=latest_only,
                          investigation_id=investigation_id)
    return paginate(db, stmt, page, page_size, ScenarioOut)


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
def get_one(scenario_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return svc.get_scenario(db, user, scenario_id)


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioOut)
def update(scenario_id: str, payload: ScenarioUpdate, request: Request, user: AuthenticatedUser = Depends(require_permission(WRITE)),
           db: Session = Depends(get_db)):
    sc = svc.get_scenario(db, user, scenario_id)
    svc.update_scenario(db, user, sc, payload.model_dump(exclude_unset=True))
    _audit(db, request, user, "scenario.update", "scenario", sc.id, fields=sorted(payload.model_dump(exclude_unset=True)))
    db.commit()
    return sc


@router.post("/scenarios/{scenario_id}/ready", response_model=ScenarioOut)
def ready(scenario_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(WRITE)), db: Session = Depends(get_db)):
    sc = svc.mark_ready(db, user, svc.get_scenario(db, user, scenario_id))
    _audit(db, request, user, "scenario.ready", "scenario", sc.id, version=sc.version)
    db.commit()
    return sc


@router.post("/scenarios/{scenario_id}/duplicate", response_model=ScenarioOut, status_code=201)
def duplicate(scenario_id: str, payload: ScenarioDuplicate, request: Request, user: AuthenticatedUser = Depends(require_permission(WRITE)),
              db: Session = Depends(get_db)):
    src = svc.get_scenario(db, user, scenario_id)
    new = svc.duplicate_scenario(db, user, src, payload.model_dump(exclude_unset=True))
    _audit(db, request, user, "scenario.duplicate", "scenario", new.id, parent=src.id, version=new.version)
    db.commit()
    return new


@router.post("/scenarios/{scenario_id}/archive", response_model=ScenarioOut)
def archive(scenario_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(WRITE)), db: Session = Depends(get_db)):
    sc = svc.archive_scenario(db, svc.get_scenario(db, user, scenario_id))
    _audit(db, request, user, "scenario.archive", "scenario", sc.id)
    db.commit()
    return sc


@router.get("/scenarios/{scenario_id}/versions", response_model=list[ScenarioOut])
def versions(scenario_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return svc.versions(db, user, svc.get_scenario(db, user, scenario_id))


# ------------------------------------------------------------------ runs

@router.get("/scenarios/{scenario_id}/runs", response_model=Page[RunSummary])
def runs(scenario_id: str, status: Optional[str] = Query(None, pattern="^(running|completed|failed)$"),
         kind: Optional[str] = Query(None, pattern="^(simulation|sensitivity)$"), page: int = Query(1, ge=1, le=1000),
         page_size: int = Query(20, ge=1, le=100), user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    sc = svc.get_scenario(db, user, scenario_id)
    return paginate(db, svc.runs_query(db, user, sc, status, kind), page, page_size, RunSummary)


def _execute(db: Session, request: Request, user: AuthenticatedUser, sc, *, kind: str, seed, idem, retry_of=None, extra=None, action: str):
    run, replay = svc.begin_run(db, user, sc, kind=kind, seed=seed, idempotency_key=idem, retry_of=retry_of, extra=extra)
    if replay:
        return run, True
    db.commit()  # persist the 'running' row before doing the work
    svc.execute_run(db, run, sc)
    _audit(db, request, user, action, "scenario_run", run.id, scenario_id=sc.id, status=run.status, error_code=run.error_code,
           runtime_ms=run.runtime_ms)
    db.commit()
    return run, False


@router.post("/scenarios/{scenario_id}/runs", response_model=RunDetail, status_code=201)
def run(scenario_id: str, payload: RunRequest, request: Request, response: Response,
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=100),
        user: AuthenticatedUser = Depends(require_permission(RUN)), db: Session = Depends(get_db)):
    sc = svc.get_scenario(db, user, scenario_id)
    r, replay = _execute(db, request, user, sc, kind="simulation", seed=payload.seed, idem=idempotency_key, action="scenario.run")
    if replay:
        response.status_code = 200
    return _run_detail(r, replay)


@router.post("/scenarios/{scenario_id}/sensitivity", response_model=RunDetail, status_code=201)
def sensitivity(scenario_id: str, payload: SensitivityRequest, request: Request, response: Response,
                idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=100),
                user: AuthenticatedUser = Depends(require_permission(RUN)), db: Session = Depends(get_db)):
    sc = svc.get_scenario(db, user, scenario_id)
    sweep = [e.model_dump(exclude_none=True) for e in payload.sweep]
    plan = svc.plan_sensitivity(sc, sweep, payload.repetitions, payload.metric)  # 422 before any run row exists
    extra = {"sensitivity": {"sweep": plan["sweep"], "repetitions": plan["repetitions"], "metric": plan["metric"],
                             "planned_runs": plan["total_runs"]}}
    r, replay = _execute(db, request, user, sc, kind="sensitivity", seed=payload.seed, idem=idempotency_key, extra=extra,
                         action="scenario.sensitivity")
    if replay:
        response.status_code = 200
    return _run_detail(r, replay)


@router.get("/scenario-runs/{run_id}", response_model=RunDetail)
def run_detail(run_id: str, user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    return _run_detail(svc.get_run(db, user, run_id))


@router.post("/scenario-runs/{run_id}/retry", response_model=RunDetail, status_code=201)
def retry(run_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(RUN)), db: Session = Depends(get_db)):
    failed = svc.get_run(db, user, run_id)
    sc = svc.get_scenario(db, user, failed.scenario_id)
    run, _ = svc.retry_run(db, user, sc, failed)
    db.commit()
    svc.execute_run(db, run, sc)
    _audit(db, request, user, "scenario.run", "scenario_run", run.id, scenario_id=sc.id, status=run.status, retry_of=failed.id,
           error_code=run.error_code, runtime_ms=run.runtime_ms)
    db.commit()
    return _run_detail(run)


# ------------------------------------------------------------ comparison

@router.post("/scenario-comparisons")
def comparison(payload: CompareRequest, request: Request, user: AuthenticatedUser = Depends(require_permission(READ)),
               db: Session = Depends(get_db)):
    out = svc.compare(db, user, payload.baseline_run_id, payload.alternative_run_ids)
    _audit(db, request, user, "scenario.compare", "scenario_run", payload.baseline_run_id, alternatives=len(payload.alternative_run_ids))
    db.commit()
    return out


# ---------------------------------------------------------------- export

@router.get("/scenarios/{scenario_id}/export")
def export(scenario_id: str, request: Request, format: str = Query("json", pattern="^(json|markdown)$"),
           user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    sc = svc.get_scenario(db, user, scenario_id)
    body, media, filename = svc.build_export(db, user, sc, "json" if format == "json" else "markdown")
    _audit(db, request, user, "scenario.export", "scenario", sc.id, format=format, bytes=len(body))
    db.commit()
    return Response(content=body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                                            "X-Content-Type-Options": "nosniff", "X-AEGIS-Synthetic": "true"})


# ------------------------------------------------------ synthetic datasets

@router.post("/synthetic-datasets", response_model=DatasetSummary, status_code=201)
def create_dataset(payload: DatasetRequest, request: Request, user: AuthenticatedUser = Depends(require_permission(WRITE)),
                   db: Session = Depends(get_db)):
    ds = svc.generate_dataset(db, user, payload.name, payload.params, payload.seed)
    _audit(db, request, user, "dataset.generate", "synthetic_dataset", ds.id, records=ds.record_count, seed=ds.seed)
    db.commit()
    return ds


@router.get("/synthetic-datasets", response_model=Page[DatasetSummary])
def list_datasets(page: int = Query(1, ge=1, le=1000), page_size: int = Query(20, ge=1, le=100),
                  user: AuthenticatedUser = Depends(require_permission(READ)), db: Session = Depends(get_db)):
    from sqlalchemy import select
    from app.models.scenario import SyntheticDataset
    stmt = select(SyntheticDataset).where(SyntheticDataset.organization_id == user.organization_id).order_by(
        SyntheticDataset.created_at.desc(), SyntheticDataset.id)
    return paginate(db, stmt, page, page_size, DatasetSummary)


@router.get("/synthetic-datasets/{dataset_id}")
def get_dataset(dataset_id: str, limit: int = Query(100, ge=0, le=500), user: AuthenticatedUser = Depends(require_permission(READ)),
                db: Session = Depends(get_db)):
    ds = svc.get_dataset(db, user, dataset_id)
    out = DatasetSummary.model_validate(ds).model_dump(mode="json")
    out.update(header=ds.header, records=ds.records[:limit], records_returned=min(limit, len(ds.records)))
    return out
