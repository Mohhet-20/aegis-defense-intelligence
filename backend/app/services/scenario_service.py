"""Scenario definitions, bounded synchronous runs, comparison,
sensitivity analysis and synthetic datasets.

Rules enforced here:
* Every read/write is organization-scoped; other-org, missing and
  unauthorized (restricted-investigation) scenarios all yield the same 404.
* Only simulators in `app.simulation.simulators.REGISTRY` can run, selected by
  id; nothing named by a row or request is imported or executed.
* Ready/archived scenarios are immutable; changes require a new version.
* A run stores an immutable config snapshot. Runs are never overwritten.
* Runtime is measured with a monotonic clock; a run is `completed` only when
  the simulator returned normally and the stored result passed size limits.
Services flush only; HTTP handlers commit."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser
from app.db.base import new_uuid, utcnow
from app.models.scenario import Scenario, ScenarioRun, SyntheticDataset
from app.services import investigation_service
from app.services.workspace_errors import conflict, invalid, not_found
from app.simulation import analysis, generator
from app.simulation import simulators as S
from app.simulation import templates as T
from app.simulation.errors import ResourceLimitError, SimulationError

settings = get_settings()
SIM_LABEL = "SIMULATED - synthetic data, hypothetical results. Not an observation of the real world and not evidence."
ALLOWED_EXEC_KEYS = {"max_seconds"}


# ------------------------------------------------------------------ helpers

def _json_size(obj) -> int:
    return len(json.dumps(obj, default=str, separators=(",", ":")))


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _check_execution_config(cfg) -> dict:
    cfg = {} if cfg is None else cfg
    if not isinstance(cfg, dict):
        raise invalid("execution_config must be an object")
    extra = set(cfg) - ALLOWED_EXEC_KEYS
    if extra:
        raise invalid("unsupported execution_config keys: " + ", ".join(sorted(str(k)[:30] for k in extra)[:5]))
    out = {}
    if "max_seconds" in cfg:
        v = cfg["max_seconds"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0.1 <= v <= settings.SCENARIO_MAX_RUN_SECONDS):
            raise invalid(f"max_seconds must be between 0.1 and {settings.SCENARIO_MAX_RUN_SECONDS:g}")
        out["max_seconds"] = float(v)
    return out


def _validated(simulator_id: str, params) -> dict:
    try:
        clean, errs = S.validate(simulator_id, params)
    except SimulationError as exc:
        raise invalid(str(exc))
    if errs:
        raise invalid("invalid parameters: " + "; ".join(f"{e['param']}: {e['message']}" for e in errs[:8]))
    return clean


def validate_config(simulator_id: str, params, execution_config=None) -> dict:
    """Non-raising validation used by POST /scenarios/validate."""
    out = {"valid": True, "errors": [], "params": None}
    try:
        sim = S.get(simulator_id)
    except SimulationError as exc:
        return {"valid": False, "errors": [{"param": "simulator_id", "message": str(exc)}], "params": None}
    clean, errs = S.validate(simulator_id, params)
    if errs:
        out["valid"], out["errors"] = False, errs
    else:
        out["params"] = clean
    try:
        _check_execution_config(execution_config)
    except Exception as exc:  # noqa: BLE001 - HTTPException detail only
        out["valid"] = False
        out["errors"].append({"param": "execution_config", "message": getattr(exc, "detail", "invalid")})
    out["assumptions"], out["limitations"] = list(sim.assumptions), list(sim.limitations)
    return out


def _assert_investigation(db: Session, user: AuthenticatedUser, investigation_id: Optional[str]) -> None:
    if investigation_id:
        investigation_service.get_accessible(db, user, investigation_id)


def get_scenario(db: Session, user: AuthenticatedUser, scenario_id: str) -> Scenario:
    sc = db.scalar(select(Scenario).where(Scenario.id == scenario_id, Scenario.organization_id == user.organization_id))
    if sc is None or not _visible(db, user, sc):
        raise not_found("Scenario")
    return sc


def _visible(db: Session, user: AuthenticatedUser, sc: Scenario) -> bool:
    """A scenario linked to an investigation follows that investigation's access."""
    if sc.organization_id != user.organization_id:
        return False
    if not sc.investigation_id:
        return True
    inv = investigation_service.get_investigation(db, user.organization_id, sc.investigation_id)
    return inv is not None and investigation_service.user_can_access(db, user, inv)


def _hidden_investigation_ids(db: Session, user: AuthenticatedUser) -> set[str]:
    ids = set(db.scalars(select(Scenario.investigation_id).where(Scenario.organization_id == user.organization_id,
                                                                  Scenario.investigation_id.is_not(None)).distinct()))
    hidden = set()
    for iid in ids:
        inv = investigation_service.get_investigation(db, user.organization_id, iid)
        if inv is None or not investigation_service.user_can_access(db, user, inv):
            hidden.add(iid)
    return hidden


def list_query(db: Session, user: AuthenticatedUser, *, status=None, category=None, simulator_id=None, q=None,
               latest_only=False, investigation_id=None):
    stmt = select(Scenario).where(Scenario.organization_id == user.organization_id)
    hidden = _hidden_investigation_ids(db, user)
    if hidden:
        stmt = stmt.where((Scenario.investigation_id.is_(None)) | (Scenario.investigation_id.not_in(hidden)))
    if status:
        stmt = stmt.where(Scenario.status == status)
    if category:
        stmt = stmt.where(Scenario.category == category)
    if simulator_id:
        stmt = stmt.where(Scenario.simulator_id == simulator_id)
    if investigation_id:
        stmt = stmt.where(Scenario.investigation_id == investigation_id)
    if q:
        stmt = stmt.where(Scenario.title.ilike(f"%{q.replace('%', '').replace('_', ' ')[:100]}%"))
    if latest_only:
        sub = select(Scenario.lineage_id, func.max(Scenario.version).label("v")).where(
            Scenario.organization_id == user.organization_id).group_by(Scenario.lineage_id).subquery()
        stmt = stmt.join(sub, (Scenario.lineage_id == sub.c.lineage_id) & (Scenario.version == sub.c.v))
    return stmt.order_by(Scenario.updated_at.desc(), Scenario.id)


# ------------------------------------------------------------- definitions

def create_scenario(db: Session, user: AuthenticatedUser, data: dict) -> Scenario:
    count = db.scalar(select(func.count()).select_from(Scenario).where(Scenario.organization_id == user.organization_id)) or 0
    if count >= settings.SCENARIO_MAX_SCENARIOS_PER_ORG:
        raise conflict("Scenario limit reached for this organization")
    tpl = None
    if data.get("template_id"):
        tpl = T.get_template(data["template_id"])
        if tpl is None:
            raise invalid("unknown template")
    simulator_id = data.get("simulator_id") or (tpl or {}).get("simulator_id")
    if not simulator_id:
        raise invalid("simulator_id or template_id is required")
    if tpl and tpl["simulator_id"] != simulator_id:
        raise invalid("template does not match simulator_id")
    try:
        sim = S.get(simulator_id)
    except SimulationError as exc:
        raise invalid(str(exc))
    raw = dict(tpl["params"]) if tpl else {}
    raw.update(data.get("params") or {})
    params = _validated(simulator_id, raw)
    exec_cfg = _check_execution_config(data.get("execution_config"))
    _assert_investigation(db, user, data.get("investigation_id"))
    lineage = new_uuid()
    sc = Scenario(
        organization_id=user.organization_id, lineage_id=lineage, version=1, title=data["title"].strip(),
        description=data.get("description"), question=data.get("question") or (tpl or {}).get("question"),
        category=data.get("category") or (tpl or {}).get("category") or "general", template_id=data.get("template_id"),
        simulator_id=simulator_id, simulator_version=sim.version, params=params,
        assumptions=list(data.get("assumptions") or (tpl or {}).get("assumptions") or []),
        limitations=list(data.get("limitations") or sim.limitations), seed=data.get("seed", 1), execution_config=exec_cfg,
        status="draft", investigation_id=data.get("investigation_id"), owner_user_id=user.id)
    db.add(sc)
    db.flush()
    return sc


def update_scenario(db: Session, user: AuthenticatedUser, sc: Scenario, data: dict) -> Scenario:
    if sc.status != "draft":
        raise conflict("Only draft scenarios can be edited; duplicate it to create a new version")
    for f in ("title", "description", "question", "category", "seed"):
        if f in data and data[f] is not None:
            setattr(sc, f, data[f].strip() if isinstance(data[f], str) else data[f])
    if "params" in data and data["params"] is not None:
        merged = {**sc.params, **data["params"]}
        sc.params = _validated(sc.simulator_id, merged)
    if "assumptions" in data and data["assumptions"] is not None:
        sc.assumptions = list(data["assumptions"])
    if "limitations" in data and data["limitations"] is not None:
        sc.limitations = list(data["limitations"])
    if "execution_config" in data and data["execution_config"] is not None:
        sc.execution_config = _check_execution_config(data["execution_config"])
    if "investigation_id" in data:
        _assert_investigation(db, user, data["investigation_id"])
        sc.investigation_id = data["investigation_id"]
    db.flush()
    return sc


def mark_ready(db: Session, user: AuthenticatedUser, sc: Scenario) -> Scenario:
    if sc.status != "draft":
        raise conflict("Only draft scenarios can be marked ready")
    sc.params = _validated(sc.simulator_id, sc.params)
    if not sc.assumptions:
        raise invalid("Review and record at least one assumption before marking the scenario ready")
    sc.status = "ready"
    db.flush()
    return sc


def duplicate_scenario(db: Session, user: AuthenticatedUser, sc: Scenario, overrides: dict) -> Scenario:
    top = db.scalar(select(func.max(Scenario.version)).where(Scenario.organization_id == sc.organization_id,
                                                              Scenario.lineage_id == sc.lineage_id)) or sc.version
    params = _validated(sc.simulator_id, {**sc.params, **(overrides.get("params") or {})})
    new = Scenario(
        organization_id=sc.organization_id, lineage_id=sc.lineage_id, version=top + 1, parent_scenario_id=sc.id,
        title=(overrides.get("title") or sc.title).strip(), description=overrides.get("description", sc.description),
        question=sc.question, category=sc.category, template_id=sc.template_id, simulator_id=sc.simulator_id,
        simulator_version=S.get(sc.simulator_id).version, params=params, assumptions=list(sc.assumptions),
        limitations=list(sc.limitations), seed=overrides.get("seed", sc.seed), execution_config=dict(sc.execution_config),
        status="draft", investigation_id=sc.investigation_id, owner_user_id=user.id)
    db.add(new)
    db.flush()
    return new


def archive_scenario(db: Session, sc: Scenario) -> Scenario:
    sc.status = "archived"
    db.flush()
    return sc


def versions(db: Session, user: AuthenticatedUser, sc: Scenario) -> list[Scenario]:
    return list(db.scalars(select(Scenario).where(Scenario.organization_id == sc.organization_id, Scenario.lineage_id == sc.lineage_id)
                           .order_by(Scenario.version)))


# --------------------------------------------------------------------- runs

def get_run(db: Session, user: AuthenticatedUser, run_id: str) -> ScenarioRun:
    run = db.scalar(select(ScenarioRun).where(ScenarioRun.id == run_id, ScenarioRun.organization_id == user.organization_id))
    if run is None:
        raise not_found("Run")
    sc = db.get(Scenario, run.scenario_id)
    if sc is None or not _visible(db, user, sc):
        raise not_found("Run")
    return run


def runs_query(db: Session, user: AuthenticatedUser, sc: Scenario, status: Optional[str] = None, kind: Optional[str] = None):
    stmt = select(ScenarioRun).where(ScenarioRun.organization_id == sc.organization_id, ScenarioRun.scenario_id == sc.id)
    if status:
        stmt = stmt.where(ScenarioRun.status == status)
    if kind:
        stmt = stmt.where(ScenarioRun.run_kind == kind)
    return stmt.order_by(ScenarioRun.created_at.desc(), ScenarioRun.id)


def _expire_stale(db: Session, sc: Scenario) -> None:
    cutoff = utcnow() - timedelta(seconds=settings.SCENARIO_STALE_RUN_SECONDS)
    for r in db.scalars(select(ScenarioRun).where(ScenarioRun.scenario_id == sc.id, ScenarioRun.status == "running")):
        started = r.started_at if r.started_at.tzinfo else r.started_at.replace(tzinfo=cutoff.tzinfo)
        if started < cutoff:
            r.status, r.error_code = "failed", "stale_run"
            r.error_message = "The run did not finish (interrupted); it was marked failed and can be retried."
            r.completed_at = utcnow()
    db.flush()  # sessions here do not autoflush; later counts must see the change


def _snapshot(sc: Scenario, seed: int, kind: str, extra: Optional[dict] = None) -> dict:
    snap = {"scenario_id": sc.id, "scenario_version": sc.version, "lineage_id": sc.lineage_id, "simulator_id": sc.simulator_id,
            "simulator_version": sc.simulator_version, "params": dict(sc.params), "seed": seed, "assumptions": list(sc.assumptions),
            "limitations": list(sc.limitations), "execution_config": dict(sc.execution_config), "run_kind": kind,
            "investigation_id": sc.investigation_id, "synthetic": True}
    if extra:
        snap.update(extra)
    return snap


def begin_run(db: Session, user: AuthenticatedUser, sc: Scenario, *, kind: str = "simulation", seed: Optional[int] = None,
              idempotency_key: Optional[str] = None, retry_of: Optional[str] = None, extra: Optional[dict] = None) -> tuple[ScenarioRun, bool]:
    """Create a `running` row. Returns (run, replayed). Caller commits, then calls finish_*."""
    if sc.status == "archived":
        raise conflict("Archived scenarios cannot be run")
    if sc.status != "ready":
        raise conflict("Mark the scenario ready (after reviewing its assumptions) before running it")
    if idempotency_key:
        prev = db.scalar(select(ScenarioRun).where(ScenarioRun.organization_id == sc.organization_id, ScenarioRun.scenario_id == sc.id,
                                                   ScenarioRun.idempotency_key == idempotency_key))
        if prev is not None:
            return prev, True
    _expire_stale(db, sc)
    if db.scalar(select(func.count()).select_from(ScenarioRun).where(ScenarioRun.scenario_id == sc.id, ScenarioRun.status == "running")):
        raise conflict("A run of this scenario is already in progress")
    total = db.scalar(select(func.count()).select_from(ScenarioRun).where(ScenarioRun.scenario_id == sc.id)) or 0
    if total >= settings.SCENARIO_MAX_RUNS_PER_SCENARIO:
        raise conflict("Run history limit reached for this scenario; duplicate it to continue")
    use_seed = sc.seed if seed is None else seed
    run = ScenarioRun(organization_id=sc.organization_id, scenario_id=sc.id, scenario_version=sc.version, run_kind=kind,
                      status="running", config_snapshot=_snapshot(sc, use_seed, kind, extra), simulator_id=sc.simulator_id,
                      simulator_version=sc.simulator_version, seed=use_seed, idempotency_key=idempotency_key,
                      retry_of_run_id=retry_of, started_at=utcnow(), requested_by_user_id=user.id)
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("Duplicate idempotency key")
    return run, False


def _fail(run: ScenarioRun, code: str, message: str, t0: float) -> None:
    run.status, run.error_code, run.error_message = "failed", code, message[:500]
    run.results, run.result_sha256 = None, None
    run.completed_at = utcnow()
    run.runtime_ms = int((time.perf_counter() - t0) * 1000)


def _finish(run: ScenarioRun, sc: Scenario, results: dict, t0: float, dataset_ref: Optional[dict] = None) -> None:
    if _json_size(results) > settings.SCENARIO_MAX_RESULT_BYTES:
        _fail(run, "resource_limit", "Result exceeded the maximum stored size and was discarded.", t0)
        return
    run.results, run.result_sha256, run.dataset_ref = results, _sha(results), dataset_ref
    run.status, run.completed_at = "completed", utcnow()
    run.runtime_ms = int((time.perf_counter() - t0) * 1000)


def execute_run(db: Session, run: ScenarioRun, sc: Scenario) -> ScenarioRun:
    """Run the registered simulator synchronously inside the time budget."""
    t0 = time.perf_counter()
    snap = run.config_snapshot
    budget = min(float(snap.get("execution_config", {}).get("max_seconds", settings.SCENARIO_MAX_RUN_SECONDS)), settings.SCENARIO_MAX_RUN_SECONDS)
    try:
        if run.run_kind == "sensitivity":
            sw = snap["sensitivity"]
            res = analysis.run_sensitivity(run.simulator_id, snap["params"], run.seed, sw["sweep"], sw["repetitions"], sw["metric"],
                                           max_seconds=min(settings.SCENARIO_MAX_SWEEP_SECONDS, sw.get("max_seconds", settings.SCENARIO_MAX_SWEEP_SECONDS)))
            res["label"] = SIM_LABEL
            _finish(run, sc, res, t0)
        else:
            out = S.execute(run.simulator_id, snap["params"], run.seed, max_seconds=budget)
            header = out.dataset_header
            results = {"label": SIM_LABEL, "synthetic": True, "metrics": out.metrics, "preview": out.preview, "notes": out.notes,
                       "dataset_header": header}
            ref = {"synthetic": True, "generator": header.get("generator"), "generator_version": header.get("generator_version"),
                   "seed": header.get("seed"), "content_sha256": header.get("content_sha256"),
                   "record_count": header.get("record_count")} if header else None
            _finish(run, sc, results, t0, ref)
            if run.status == "completed":
                sc.latest_summary = {"run_id": run.id, "completed_at": run.completed_at.isoformat(), "seed": run.seed,
                                     "metrics": out.metrics, "synthetic": True}
    except (SimulationError, ResourceLimitError) as exc:
        _fail(run, getattr(exc, "code", "simulation_error"), str(exc), t0)
    except Exception:  # noqa: BLE001 - never leak internals
        _fail(run, "internal_error", "The simulation failed unexpectedly.", t0)
    db.flush()
    return run


def retry_run(db: Session, user: AuthenticatedUser, sc: Scenario, failed: ScenarioRun) -> tuple[ScenarioRun, bool]:
    if failed.status != "failed":
        raise conflict("Only failed runs can be retried")
    extra = {"sensitivity": failed.config_snapshot.get("sensitivity")} if failed.run_kind == "sensitivity" else None
    return begin_run(db, user, sc, kind=failed.run_kind, seed=failed.seed, retry_of=failed.id, extra=extra)


# -------------------------------------------------------------- sensitivity

def plan_sensitivity(sc: Scenario, sweep, reps, metric) -> dict:
    try:
        return analysis.plan_sensitivity(sc.simulator_id, sc.params, sweep, reps, metric)
    except ResourceLimitError as exc:
        raise invalid(str(exc))
    except SimulationError as exc:
        raise invalid(str(exc))


# --------------------------------------------------------------- comparison

def _run_view(run: ScenarioRun, label: Optional[str] = None) -> dict:
    return {"run_id": run.id, "label": label or f"{run.config_snapshot.get('scenario_id', '')[:8]} v{run.scenario_version}",
            "config_snapshot": run.config_snapshot, "metrics": (run.results or {}).get("metrics", {})}


def compare(db: Session, user: AuthenticatedUser, baseline_run_id: str, alternative_run_ids: list[str]) -> dict:
    if len(set([baseline_run_id, *alternative_run_ids])) != 1 + len(alternative_run_ids):
        raise invalid("runs to compare must be distinct")
    runs = []
    for rid in [baseline_run_id, *alternative_run_ids]:
        r = get_run(db, user, rid)
        if r.run_kind != "simulation" or r.status != "completed":
            raise invalid("only completed simulation runs can be compared")
        runs.append(r)
    try:
        out = analysis.compare_runs(_run_view(runs[0]), [_run_view(r) for r in runs[1:]])
    except SimulationError as exc:
        raise invalid(str(exc))
    out["label"] = SIM_LABEL
    return out


# ----------------------------------------------------------------- datasets

def generate_dataset(db: Session, user: AuthenticatedUser, name: str, params, seed: int) -> SyntheticDataset:
    count = db.scalar(select(func.count()).select_from(SyntheticDataset).where(SyntheticDataset.organization_id == user.organization_id)) or 0
    if count >= settings.SCENARIO_MAX_DATASETS_PER_ORG:
        raise conflict("Synthetic dataset limit reached for this organization")
    clean, errs = generator.validate_params(generator.GENERATOR_SPECS, params)
    if errs:
        raise invalid("invalid parameters: " + "; ".join(f"{e['param']}: {e['message']}" for e in errs[:8]))
    try:
        generator.check_limits(clean)
        out = generator.generate(clean, seed, deadline=time.monotonic() + settings.SCENARIO_MAX_RUN_SECONDS)
    except (ResourceLimitError, SimulationError) as exc:
        raise invalid(str(exc))
    header = generator.stamp(out["header"])
    recs = out["records"]
    stored = recs[:generator.MAX_STORED_RECORDS]
    ds = SyntheticDataset(
        organization_id=user.organization_id, name=name.strip(), generator=header["generator"], generator_version=header["generator_version"],
        params=clean, seed=seed, record_count=len(recs), stored_record_count=len(stored), records_truncated=len(stored) < len(recs),
        records=stored, header=header, content_sha256=header["content_sha256"], is_synthetic=True,
        generated_at=utcnow(), created_by_user_id=user.id)
    db.add(ds)
    db.flush()
    return ds


def get_dataset(db: Session, user: AuthenticatedUser, dataset_id: str) -> SyntheticDataset:
    ds = db.scalar(select(SyntheticDataset).where(SyntheticDataset.id == dataset_id, SyntheticDataset.organization_id == user.organization_id))
    if ds is None:
        raise not_found("Synthetic dataset")
    return ds


# ------------------------------------------------------------------- export

def build_export(db: Session, user: AuthenticatedUser, sc: Scenario, fmt: str) -> tuple[str, str, str]:
    """Returns (body, media_type, filename). No filesystem paths are involved;
    the filename is derived from the scenario id only."""
    runs = list(db.scalars(runs_query(db, user, sc).limit(25)))
    doc = {
        "label": SIM_LABEL, "synthetic": True, "exported_at": utcnow().isoformat(),
        "scenario": {"id": sc.id, "lineage_id": sc.lineage_id, "version": sc.version, "title": sc.title, "question": sc.question,
                     "category": sc.category, "status": sc.status, "simulator_id": sc.simulator_id, "simulator_version": sc.simulator_version,
                     "params": sc.params, "seed": sc.seed, "assumptions": sc.assumptions, "limitations": sc.limitations,
                     "investigation_id": sc.investigation_id},
        "runs": [{"run_id": r.id, "kind": r.run_kind, "status": r.status, "seed": r.seed, "started_at": r.started_at.isoformat(),
                  "completed_at": r.completed_at.isoformat() if r.completed_at else None, "runtime_ms": r.runtime_ms,
                  "result_sha256": r.result_sha256, "dataset_ref": r.dataset_ref, "error_code": r.error_code,
                  "metrics": (r.results or {}).get("metrics") if r.run_kind == "simulation" else None,
                  "sensitivity_ranking": (r.results or {}).get("ranking") if r.run_kind == "sensitivity" else None} for r in runs],
        "interpretation": ["Results are hypothetical outputs of a simulation on synthetic data.",
                           "They are not evidence and have not modified any assessment.",
                           "No confidence intervals are computed; spread across seeds is variability of the simulated outcome."],
    }
    name = f"scenario-{sc.id}"
    if fmt == "json":
        return json.dumps(doc, indent=2, default=str), "application/json", f"{name}.json"
    lines = [f"# [SIMULATED] {sc.title} (v{sc.version})", "", f"> {SIM_LABEL}", "",
             f"- Simulator: `{sc.simulator_id}` v{sc.simulator_version}", f"- Seed: {sc.seed}", f"- Status: {sc.status}"]
    if sc.question:
        lines += ["", "## Question", sc.question]
    lines += ["", "## Parameters", *[f"- `{k}` = {v}" for k, v in sorted(sc.params.items())],
              "", "## Assumptions", *([f"- {a}" for a in sc.assumptions] or ["- (none recorded)"]),
              "", "## Limitations", *([f"- {a}" for a in sc.limitations] or ["- (none recorded)"]), "", "## Runs"]
    if not doc["runs"]:
        lines.append("No runs yet.")
    for r in doc["runs"]:
        lines.append(f"### {r['kind']} run `{r['run_id']}` - {r['status']}")
        lines.append(f"seed {r['seed']}, runtime {r['runtime_ms']} ms, result sha256 `{r['result_sha256']}`")
        if r["error_code"]:
            lines.append(f"error: {r['error_code']}")
        for k, v in sorted((r["metrics"] or {}).items()):
            lines.append(f"- {k}: {v}")
        for item in r["sensitivity_ranking"] or []:
            lines.append(f"- {item['param']}: effect range {item['effect_range']}")
    lines += ["", "## Interpretation", *[f"- {i}" for i in doc["interpretation"]]]
    return "\n".join(lines) + "\n", "text/markdown", f"{name}.md"
