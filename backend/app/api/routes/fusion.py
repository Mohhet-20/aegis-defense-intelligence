from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.fusion import FusionJobResponse, GraphResponse, RunFusionJobRequest
from app.services import audit_service, fusion_service, graph_service

router = APIRouter(prefix="/fusion", tags=["fusion"])


@router.post("/run", response_model=FusionJobResponse, status_code=status.HTTP_201_CREATED)
def run_fusion_job(
    payload: RunFusionJobRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.FUSION_RUN)),
    db: Session = Depends(get_db),
) -> FusionJobResponse:
    """The one explicit, authorized entry point for the fusion pipeline --
    composes correlation recompute + conflict detection
    into a single inspectable FusionJob. There is no background
    scheduler; this only ever runs because an analyst/admin asked it to."""
    job = fusion_service.run_fusion_job(
        db, current_user.organization_id, triggered_by_user_id=current_user.id,
        time_window_seconds=payload.time_window_seconds,
        spatial_threshold_meters=payload.spatial_threshold_meters,
        spatial_conflict_threshold_meters=payload.spatial_conflict_threshold_meters,
    )
    audit_service.record(
        db, action="fusion.run", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="fusion_job", target_id=job.id, outcome="success" if job.status == "completed" else "failure",
        request_id=getattr(request.state, "request_id", None),
        context_metadata={"status": job.status, "correlations_created": job.correlations_created, "conflicts_created": job.conflicts_created},
    )
    db.commit()
    return FusionJobResponse.model_validate(job)


@router.get("/jobs", response_model=Page[FusionJobResponse])
def list_fusion_jobs(
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.FUSION_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = fusion_service.list_jobs_query(current_user.organization_id)
    return paginate(db, stmt, page_params.page, page_params.page_size, FusionJobResponse)


@router.get("/jobs/{job_id}", response_model=FusionJobResponse)
def get_fusion_job(
    job_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.FUSION_READ)),
    db: Session = Depends(get_db),
) -> FusionJobResponse:
    job = fusion_service.get_job(db, current_user.organization_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fusion job not found")
    return FusionJobResponse.model_validate(job)


@router.get("/graph", response_model=GraphResponse)
def get_evidence_graph(
    seed_type: str = Query(..., description="'event', 'evidence', or 'assessment'"),
    seed_id: str = Query(...),
    # No upper bound here: the real cap is always settings.FUSION_GRAPH_MAX_DEPTH/
    # FUSION_GRAPH_MAX_NODES, enforced unconditionally inside graph_service.build_graph
    # regardless of what a client asks for. An upper `le` here would make the API
    # *reject* an over-large request instead of *clamping* it, which is not the
    # bounded-graph guarantee Section 10 asks for.
    max_depth: Optional[int] = Query(default=None, ge=1),
    max_nodes: Optional[int] = Query(default=None, ge=1),
    relationship_type: Optional[list[str]] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    source_id: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.GRAPH_READ)),
    db: Session = Depends(get_db),
) -> GraphResponse:
    """Bounded breadth-first traversal from one seed node
    -- `max_depth`/`max_nodes` are always clamped server-side to
    `settings.FUSION_GRAPH_MAX_DEPTH`/`FUSION_GRAPH_MAX_NODES` no
    matter what a client requests; see graph_service.py."""
    try:
        graph = graph_service.build_graph(
            db, current_user.organization_id, seed_type=seed_type, seed_id=seed_id,
            max_depth=max_depth, max_nodes=max_nodes, relationship_types=relationship_type,
            review_status=review_status, source_id=source_id, since=since, until=until,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return GraphResponse(**graph)
