"""Process metrics, operational summary and detailed health.
All routes are authenticated; the unauthenticated surface remains the minimal
/health/live and /health/ready pair."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.obs_metrics import UNAVAILABLE, registry
from app.core.security import AuthenticatedUser, Permission, has_permission, require_permission
from app.db.session import get_db
from app.services import observability_service as obs

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/metrics")
def metrics(user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVABILITY_READ))):
    return {"scope": "this API process only; resets on restart; not aggregated across workers", "since_epoch": registry.started_at,
            "metrics": registry.snapshot(), "unavailable": UNAVAILABLE}


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
def metrics_prometheus(user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVABILITY_READ))):
    return PlainTextResponse(registry.to_prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/summary")
def summary(days: int = Query(default=7, ge=1, le=30), user: AuthenticatedUser = Depends(require_permission(Permission.MLOPS_READ)), db: Session = Depends(get_db)):
    data = obs.summary(db, user.organization_id, days)
    if not has_permission(user.role, Permission.OBSERVABILITY_READ):
        data["requests"] = {"status": "restricted", "reason": "Process-level request metrics require the observability:read permission."}
    return data


@router.get("/health")
def detailed_health(user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVABILITY_READ)), db: Session = Depends(get_db)):
    return obs.detailed_health(db, user.organization_id)
