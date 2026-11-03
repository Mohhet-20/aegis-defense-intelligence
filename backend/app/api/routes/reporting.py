"""Analytics, executive dashboards and reports.

Authorization is `require_permission` here plus per-section permission inside the
analytics service (a caller never receives numbers from a section they cannot read).
Report files are only ever served from `/reports/{id}/download` after the same
checks; there is no static or guessable URL."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import MlopsNotFound
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.reporting import definitions as defs
from app.reporting import render
from app.reporting.envelope import Ctx
from app.reporting.window import build_filters, build_window
from app.schemas.common import PageParams
from app.schemas.reporting import ReportOut, ReportRequest
from app.services import analytics_service as an
from app.services import audit_service, report_service as rs

router = APIRouter(prefix="/reporting", tags=["reporting"])


def _rid(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _ctx(db: Session, user: AuthenticatedUser, days, start, end, bucket, time_basis, source_id, category, include_archived) -> Ctx:
    return Ctx(db=db, user=user, window=build_window(start, end, days, bucket, time_basis), filters=build_filters(source_id, category, include_archived))


@router.get("/metrics")
def metric_catalog(section: Optional[str] = Query(default=None, pattern="^[a-z_]{1,30}$"), user: AuthenticatedUser = Depends(require_permission(Permission.REPORTING_READ))):
    items = defs.for_section(section) if section else list(defs.CATALOG.values())
    if section and section not in defs.SECTION_IDS:
        raise MlopsNotFound("unknown section")
    return {"definition_version": defs.DEFINITION_VERSION, "sections": list(defs.SECTION_IDS), "metrics": items}


@router.get("/analytics/{section}")
def analytics_section(
    section: str, request: Request, days: Optional[int] = Query(default=None, ge=1, le=366), start: Optional[datetime] = None, end: Optional[datetime] = None,
    bucket: str = Query(default="auto", pattern="^(auto|hour|day)$"), time_basis: str = Query(default="event", pattern="^(event|ingestion)$"),
    source_id: Optional[str] = Query(default=None, max_length=100), category: Optional[str] = Query(default=None, max_length=100), include_archived: bool = False,
    user: AuthenticatedUser = Depends(require_permission(Permission.REPORTING_READ)), db: Session = Depends(get_db),
):
    if section not in an.SECTIONS:
        raise MlopsNotFound("unknown analytics section")
    ctx = _ctx(db, user, days, start, end, bucket, time_basis, source_id, category, include_archived)
    out = an.build_section(ctx, section)
    audit_service.record(db, action="analytics.viewed", actor_user_id=user.id, organization_id=user.organization_id, target_type="analytics", target_id=section,
                         request_id=_rid(request), context_metadata={"window": ctx.window.describe(), "filters": ctx.filters.describe(), "status": out["status"]})
    db.commit()
    return out


@router.get("/dashboards/executive")
def executive(
    request: Request, days: Optional[int] = Query(default=None, ge=1, le=366), start: Optional[datetime] = None, end: Optional[datetime] = None,
    bucket: str = Query(default="auto", pattern="^(auto|hour|day)$"), time_basis: str = Query(default="event", pattern="^(event|ingestion)$"),
    source_id: Optional[str] = Query(default=None, max_length=100), category: Optional[str] = Query(default=None, max_length=100), include_archived: bool = False,
    user: AuthenticatedUser = Depends(require_permission(Permission.REPORTING_READ)), db: Session = Depends(get_db),
):
    ctx = _ctx(db, user, days, start, end, bucket, time_basis, source_id, category, include_archived)
    out = an.executive_dashboard(ctx)
    audit_service.record(db, action="analytics.viewed", actor_user_id=user.id, organization_id=user.organization_id, target_type="analytics", target_id="executive",
                         request_id=_rid(request), context_metadata={"window": ctx.window.describe(), "filters": ctx.filters.describe(), "section_status": out["section_status"]})
    db.commit()
    return out


@router.get("/templates")
def templates(user: AuthenticatedUser = Depends(require_permission(Permission.REPORTING_READ))):
    return {"templates": rs.templates_for(user), "formats": list(render.RENDERERS), "unsupported_formats": ["pdf"],
            "retention_days": get_settings().REPORT_RETENTION_DAYS, "max_artifact_bytes": get_settings().REPORT_MAX_ARTIFACT_BYTES}


@router.post("/reports/validate")
def validate_report(body: ReportRequest, user: AuthenticatedUser = Depends(require_permission(Permission.REPORT_GENERATE))):
    plan = rs.validate(user, body)
    return {"valid": True, "template_key": plan.template_key, "title": plan.title, "sections": plan.sections, "window": plan.window.describe(), "filters": plan.filters.describe(),
            "required_permissions": plan.required, "format": plan.format, "visibility": plan.visibility, "has_commentary": bool(plan.notes)}


@router.post("/reports", response_model=ReportOut, status_code=201)
def create_report(body: ReportRequest, request: Request, response: Response, user: AuthenticatedUser = Depends(require_permission(Permission.REPORT_GENERATE)), db: Session = Depends(get_db)):
    run, replayed = rs.generate(db, user, body, request_id=_rid(request))
    db.commit()
    if replayed:
        response.status_code = 200
    return rs.serialize(run, replayed=replayed)


@router.get("/reports")
def list_reports(status: Optional[str] = Query(default=None, pattern="^(running|completed|failed|expired)$"), template_key: Optional[str] = Query(default=None, max_length=40),
                 page_params: PageParams = Depends(), user: AuthenticatedUser = Depends(require_permission(Permission.REPORTING_READ)), db: Session = Depends(get_db)):
    size = max(1, min(page_params.page_size, get_settings().MAX_PAGE_SIZE))
    page = max(page_params.page, 1)
    stmt = rs.list_query(user, status=status, template_key=template_key)
    rows = db.execute(stmt.limit(size * 5).offset((page - 1) * size)).scalars().all()  # over-fetch to drop rows lacking required permissions
    visible = rs.permitted(user, list(rows))[:size]
    total = len([r for r in db.execute(stmt.limit(get_settings().ANALYTICS_MAX_ROWS)).scalars() if rs.can_read(user, r)])
    return {"items": [rs.serialize(r) for r in visible], "total": total, "page": page, "page_size": size}


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(report_id: str, user: AuthenticatedUser = Depends(require_permission(Permission.REPORTING_READ)), db: Session = Depends(get_db)):
    return rs.serialize(rs.get_for_user(db, user, report_id))


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.REPORTING_READ)), db: Session = Depends(get_db)):
    run, data = rs.read_artifact(db, user, report_id, request_id=_rid(request))
    db.commit()
    headers = {"Content-Disposition": f'attachment; filename="{run.artifact_name}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store, private",
               "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox", "X-Report-Sha256": run.content_sha256 or ""}
    return Response(content=data, media_type=render.CONTENT_TYPES[run.format], headers=headers)


@router.post("/reports/purge-expired")
def purge(request: Request, user: AuthenticatedUser = Depends(require_permission(Permission.LIFECYCLE_APPROVE)), db: Session = Depends(get_db)):
    n = rs.purge_expired(db, user.organization_id, request_id=_rid(request))
    db.commit()
    return {"expired": n}
