from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.correlation import EventCorrelationResponse
from app.schemas.event import EventResponse
from app.schemas.raw_record import RawRecordResponse
from app.services import audit_service, correlation_service, event_service, export_service, ingestion_service

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=Page[EventResponse])
def list_events(
    event_type: Optional[str] = Query(default=None),
    source_id: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    data_origin: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVENT_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = event_service.list_events_query(
        current_user.organization_id, event_type=event_type, source_id=source_id, priority=priority, data_origin=data_origin,
    )
    return paginate(db, stmt, page_params.page, page_params.page_size, EventResponse)


@router.get("/export")
def export_events(
    request: Request,
    format: Literal["csv", "json"] = Query(default="csv"),
    event_type: Optional[str] = Query(default=None),
    source_id: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    data_origin: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.DATA_EXPORT)),
    db: Session = Depends(get_db),
) -> Response:
    """Controlled bulk export -- gated by its own
    DATA_EXPORT permission (not every role that can read events may
    bulk-export them), explicitly filtered, size-bounded, and logged.
    Only normalized Event fields are exported -- never a raw payload."""
    stmt = event_service.list_events_query(
        current_user.organization_id, event_type=event_type, source_id=source_id, priority=priority, data_origin=data_origin,
    )
    rows = db.execute(stmt.limit(export_service.MAX_EXPORT_ROWS + 1)).scalars().all()
    if len(rows) > export_service.MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"this filter would export more than {export_service.MAX_EXPORT_ROWS} rows -- narrow the filters (event_type/source_id/priority/data_origin) before exporting",
        )

    audit_service.record(
        db, action="event.export", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="event_export", target_id=None, request_id=getattr(request.state, "request_id", None),
        context_metadata={"format": format, "row_count": len(rows), "filters": {"event_type": event_type, "source_id": source_id, "priority": priority, "data_origin": data_origin}},
    )
    db.commit()

    if format == "json":
        body = export_service.export_events_json(rows)
        return Response(content=body, media_type="application/json", headers={"Content-Disposition": "attachment; filename=events_export.json"})

    body = export_service.export_events_csv(rows)
    return Response(content=body, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=events_export.csv"})


@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    event_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.EVENT_READ)),
    db: Session = Depends(get_db),
) -> EventResponse:
    event = event_service.get_event(db, current_user.organization_id, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return EventResponse.model_validate(event)


@router.get("/{event_id}/raw-record", response_model=RawRecordResponse)
def get_event_raw_record(
    event_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.RAW_RECORD_READ)),
    db: Session = Depends(get_db),
) -> RawRecordResponse:
    """Provenance inspection -- gated separately from EVENT_READ
    because the raw payload may carry source-side detail
    a normalized Event intentionally drops."""
    event = event_service.get_event(db, current_user.organization_id, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    raw_record_id = (event.provenance or {}).get("raw_record_id")
    if not raw_record_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This event has no linked raw record (it was not created by file ingestion)")
    raw_record = ingestion_service.get_raw_record(db, current_user.organization_id, raw_record_id)
    if raw_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw record not found")
    return RawRecordResponse.model_validate(raw_record)


@router.get("/{event_id}/correlations", response_model=list[EventCorrelationResponse])
def get_event_correlations(
    event_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.CORRELATION_READ)),
    db: Session = Depends(get_db),
) -> list[EventCorrelationResponse]:
    event = event_service.get_event(db, current_user.organization_id, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    correlations = correlation_service.list_correlations_for_event(db, current_user.organization_id, event_id)
    return [EventCorrelationResponse.model_validate(c) for c in correlations]
