from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.demo import guard_demo_account
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.models.audit import AuditRecord
from app.models.user import User
from app.schemas.audit import AuditRecordResponse
from app.schemas.auth import ResetPasswordRequest, UserCreateRequest, UserResponse, UserUpdateRequest
from app.services import audit_service, user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(
    current_user: AuthenticatedUser = Depends(require_permission(Permission.USER_READ)),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    users = user_service.list_users(db, current_user.organization_id)
    return [UserResponse.model_validate(u) for u in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> UserResponse:
    try:
        user = user_service.create_user(
            db,
            organization_id=current_user.organization_id,
            username=payload.username,
            email=payload.email,
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
        )
    except user_service.DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except user_service.PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    audit_service.record(
        db, action="user.create", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="user", target_id=user.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"role": user.role, "username": user.username},
    )
    db.commit()
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.USER_READ)),
    db: Session = Depends(get_db),
) -> UserResponse:
    return UserResponse.model_validate(_org_user_or_404(db, current_user, user_id))


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = _org_user_or_404(db, current_user, user_id)
    guard_demo_account(user.username)
    before = {"display_name": user.display_name, "role": user.role, "is_active": user.is_active}
    request_id = getattr(request.state, "request_id", None)
    try:
        updated = user_service.update_user(
            db, user, display_name=payload.display_name, role=payload.role, is_active=payload.is_active,
            acting_user_id=current_user.id,
        )
    except user_service.AccessChangeError as exc:
        audit_service.record(
            db, action="user.update", actor_user_id=current_user.id, organization_id=current_user.organization_id,
            target_type="user", target_id=user.id, outcome="denied", request_id=request_id,
            context_metadata={"reason": str(exc), "requested": payload.model_dump(exclude_none=True)},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    after = {"display_name": updated.display_name, "role": updated.role, "is_active": updated.is_active}
    audit_service.record(
        db, action="user.update", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="user", target_id=user.id, request_id=request_id,
        context_metadata={**payload.model_dump(exclude_none=True), "before": before, "after": after,
                          "sessions_revoked": before["role"] != after["role"] or (before["is_active"] and not after["is_active"])},
    )
    db.commit()
    return UserResponse.model_validate(updated)


def _org_user_or_404(db: Session, current_user: AuthenticatedUser, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_sessions(
    user_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """Forces the target user to sign in again (all tokens invalidated)."""
    user = _org_user_or_404(db, current_user, user_id)
    guard_demo_account(user.username)
    user_service.revoke_sessions(db, user)
    audit_service.record(
        db, action="auth.sessions_revoked", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="user", target_id=user.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"scope": "admin"},
    )
    db.commit()


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(
    user_id: str,
    payload: ResetPasswordRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """Administrator sets a new password for a user in the SAME org and
    revokes that user's sessions. The password is never echoed or audited."""
    user = _org_user_or_404(db, current_user, user_id)
    guard_demo_account(user.username)
    try:
        user_service.set_password(db, user, payload.new_password)
    except user_service.PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    audit_service.record(
        db, action="user.password_reset", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="user", target_id=user.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"sessions_revoked": True},
    )
    db.commit()


@router.get("/{user_id}/access-history", response_model=list[AuditRecordResponse])
def user_access_history(
    user_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.USER_MANAGE)),
    db: Session = Depends(get_db),
) -> list[AuditRecordResponse]:
    """Account / permission change history for one user in this org
    (newest first, bounded to 200)."""
    user = _org_user_or_404(db, current_user, user_id)
    rows = db.execute(
        select(AuditRecord)
        .where(AuditRecord.organization_id == current_user.organization_id, AuditRecord.target_type == "user", AuditRecord.target_id == user.id)
        .order_by(AuditRecord.created_at.desc()).limit(200)
    ).scalars().all()
    return [AuditRecordResponse.model_validate(r) for r in rows]
