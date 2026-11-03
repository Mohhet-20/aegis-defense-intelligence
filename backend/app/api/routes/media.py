from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.config import get_settings
from app.core.uploads import read_bounded
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.cv.media_validation import MediaValidationError
from app.db.session import get_db
from app.schemas.common import Page, PageParams
from app.schemas.media import MediaAssetResponse
from app.services import audit_service, media_service

settings = get_settings()
router = APIRouter(prefix="/media", tags=["media"])


@router.post("", response_model=MediaAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.MEDIA_MANAGE)),
    db: Session = Depends(get_db),
) -> MediaAssetResponse:
    """Section 3: the uploaded bytes are sniffed, size/dimension/
    duration-checked, hashed, and content-addressed-stored by
    media_service.ingest_media() -- `file.filename` and
    `file.content_type` are NEVER trusted for anything beyond a
    display-only label; see app/cv/media_validation.py."""
    content = await read_bounded(file, max(settings.CV_MAX_IMAGE_UPLOAD_BYTES, settings.CV_MAX_VIDEO_UPLOAD_BYTES))
    try:
        media_asset = media_service.ingest_media(
            db, organization_id=current_user.organization_id, declared_filename=file.filename,
            content=content, uploaded_by_user_id=current_user.id,
        )
    except MediaValidationError as exc:
        audit_service.record(
            db, action="media.upload_rejected", actor_user_id=current_user.id, organization_id=current_user.organization_id,
            outcome="failure", request_id=getattr(request.state, "request_id", None),
            context_metadata={"reason": str(exc), "declared_filename": file.filename},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    audit_service.record(
        db, action="media.upload", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="media_asset", target_id=media_asset.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"media_type": media_asset.media_type, "byte_size": media_asset.byte_size},
    )
    db.commit()
    return MediaAssetResponse.model_validate(media_asset)


@router.get("", response_model=Page[MediaAssetResponse])
def list_media(
    media_type: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.MEDIA_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = media_service.list_media_query(current_user.organization_id, media_type=media_type)
    return paginate(db, stmt, page_params.page, page_params.page_size, MediaAssetResponse)


@router.get("/{media_asset_id}", response_model=MediaAssetResponse)
def get_media(
    media_asset_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.MEDIA_READ)),
    db: Session = Depends(get_db),
) -> MediaAssetResponse:
    media_asset = media_service.get_media_asset(db, current_user.organization_id, media_asset_id)
    if media_asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found")
    return MediaAssetResponse.model_validate(media_asset)


@router.get("/{media_asset_id}/content")
def get_media_content(
    media_asset_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.MEDIA_READ)),
    db: Session = Depends(get_db),
) -> Response:
    """The ONLY way to read media bytes back out -- authenticated,
    permission-gated, and organization-scoped ("never
    serve media from a public, unauthenticated static directory").
    app/main.py registers no StaticFiles mount for CV_MEDIA_STORAGE_ROOT
    at all."""
    media_asset = media_service.get_media_asset(db, current_user.organization_id, media_asset_id)
    if media_asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media asset not found")
    try:
        content = media_service.read_media_content(media_asset)
    except FileNotFoundError:
        # The row exists but the stored artifact is gone (e.g. a failed
        # lifecycle cleanup or manual file removal) -- say so explicitly.
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Media artifact is missing from storage")
    # Hash verification: a corrupted/modified stored file is never served.
    import hashlib

    if hashlib.sha256(content).hexdigest() != media_asset.content_hash:
        audit_service.record(
            db, action="media.integrity_failure", actor_user_id=current_user.id, organization_id=current_user.organization_id,
            target_type="media_asset", target_id=media_asset.id, outcome="failure", request_id=getattr(request.state, "request_id", None),
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stored media failed integrity verification")
    if settings.AUDIT_MEDIA_ACCESS:
        audit_service.record(
            db, action="media.content_access", actor_user_id=current_user.id, organization_id=current_user.organization_id,
            target_type="media_asset", target_id=media_asset.id, request_id=getattr(request.state, "request_id", None),
            context_metadata={"byte_size": len(content)},
        )
        db.commit()
    return Response(content=content, media_type=media_asset.detected_mime_type, headers={"Content-Disposition": "inline", "Cache-Control": "private, no-store"})
