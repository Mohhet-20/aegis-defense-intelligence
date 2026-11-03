from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.track_annotation import TrackAnnotationCreateRequest, TrackAnnotationResponse
from app.services import audit_service, track_annotation_service, tracking_service

router = APIRouter(prefix="/tracking", tags=["track-annotations"])


@router.post("/tracks/{track_id}/annotations", response_model=TrackAnnotationResponse, status_code=status.HTTP_201_CREATED)
def create_track_annotation(
    track_id: str,
    payload: TrackAnnotationCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACK_ANNOTATE)),
    db: Session = Depends(get_db),
) -> TrackAnnotationResponse:
    track = tracking_service.get_track(db, current_user.organization_id, track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")
    try:
        annotation = track_annotation_service.create_annotation(
            db, organization_id=current_user.organization_id, track=track, annotation_type=payload.annotation_type,
            note=payload.note, created_by_user_id=current_user.id, supersedes_annotation_id=payload.supersedes_annotation_id,
        )
    except track_annotation_service.AnnotationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit_service.record(
        db, action="track.annotate", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="track", target_id=track.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"annotation_type": annotation.annotation_type, "annotation_id": annotation.id, "supersedes": payload.supersedes_annotation_id},
    )
    db.commit()
    return TrackAnnotationResponse.model_validate(annotation)


@router.get("/tracks/{track_id}/annotations", response_model=list[TrackAnnotationResponse])
def list_track_annotations(
    track_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.TRACKING_READ)),
    db: Session = Depends(get_db),
) -> list[TrackAnnotationResponse]:
    track = tracking_service.get_track(db, current_user.organization_id, track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")
    annotations = track_annotation_service.list_annotations_for_track(db, current_user.organization_id, track_id)
    return [TrackAnnotationResponse.model_validate(a) for a in annotations]
