from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

import hashlib

from app.core.config import get_settings
from app.core.demo import guard_demo_account
from app.core.rate_limit import limiter
from app.core.security import (
    AuthenticatedUser,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    token_matches_user,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import ChangePasswordRequest, CurrentUserResponse, LoginRequest, RefreshRequest, TokenResponse
from app.services import audit_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# Browser sessions ("cookie mode"): the frontend sends X-Session-Mode: cookie and the
# refresh token travels only in an HttpOnly cookie scoped to the auth endpoints, so page
# scripts (and any injected script) can never read it. The custom header is also the
# CSRF guard for cookie-authenticated refresh: cross-site forms cannot set it, and the
# cookie is SameSite=Strict on top. API clients that omit the header keep receiving
# the refresh token in the response body, as before.
SESSION_MODE_HEADER = "x-session-mode"
REFRESH_COOKIE = "aegis_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _cookie_mode(request: Request) -> bool:
    return request.headers.get(SESSION_MODE_HEADER, "").lower() == "cookie"


def _cookie_secure() -> bool:
    if settings.AUTH_COOKIE_SECURE is not None:
        return settings.AUTH_COOKIE_SECURE
    return settings.ENVIRONMENT.lower() == "production"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE, token, max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60, path=REFRESH_COOKIE_PATH,
        httponly=True, secure=_cookie_secure(), samesite="strict",
    )


def _tokens(user: User, request: Optional[Request] = None, response: Optional[Response] = None) -> TokenResponse:
    tv = user.token_version or 0
    access = create_access_token(user.id, user.role, tv)
    refresh_token = create_refresh_token(user.id, user.role, tv)
    if request is not None and response is not None and _cookie_mode(request):
        _set_refresh_cookie(response, refresh_token)
        return TokenResponse(access_token=access, refresh_token=None)
    return TokenResponse(access_token=access, refresh_token=refresh_token)


def _identifier_fingerprint(identifier: str) -> dict:
    """The raw identifier is NOT stored: users sometimes paste a password
    into the username box. A short hash lets an administrator correlate
    repeated attempts without retaining what was typed."""
    return {
        "identifier_sha256_prefix": hashlib.sha256(identifier.strip().lower().encode("utf-8")).hexdigest()[:12],
        "identifier_length": len(identifier),
    }


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    user, reason = user_service.authenticate(db, payload.username_or_email, payload.password)
    request_id = getattr(request.state, "request_id", None)
    if user is None:
        known = user_service.get_by_username_or_email(db, payload.username_or_email)
        audit_service.record(
            db, action="auth.login", actor_user_id=None, organization_id=known.organization_id if known else None,
            target_type="user" if known else None, target_id=known.id if known else None,
            outcome="denied", request_id=request_id,
            context_metadata={**_identifier_fingerprint(payload.username_or_email), "reason": reason},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=reason)
    audit_service.record(
        db, action="auth.login", actor_user_id=user.id, organization_id=user.organization_id,
        outcome="success", request_id=request_id,
    )
    db.commit()
    return _tokens(user, request, response)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_REFRESH)  # higher than login: called on every full page load
def refresh(request: Request, response: Response, payload: Optional[RefreshRequest] = None, db: Session = Depends(get_db)) -> TokenResponse:
    """Re-issues a token pair. NOTE: this is NOT refresh-token rotation --
    the old refresh token stays valid until it expires or the user's
    sessions are revoked (password change, role change, disablement, or
    an explicit revoke). See docs/security/AUTHENTICATION_AND_AUTHORIZATION.md."""
    raw = payload.refresh_token if payload and payload.refresh_token else None
    if raw is None and _cookie_mode(request):
        raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    token_payload = decode_token(raw)
    if token_payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expected a refresh token")
    user = db.get(User, token_payload.get("sub"))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    if not token_matches_user(token_payload, user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")
    return _tokens(user, request, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    # Ends a browser session by clearing the refresh cookie. Bearer tokens already
    # issued stay valid until they expire (short-lived access tokens); use
    # /auth/revoke-sessions to invalidate every token at once.
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, secure=_cookie_secure(), samesite="strict")
    return response


@router.post("/change-password", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Changes the caller's own password. Revokes ALL existing sessions
    (including this one) and returns a fresh token pair for this client."""
    user = db.get(User, current_user.id)
    guard_demo_account(user.username)
    request_id = getattr(request.state, "request_id", None)
    if not verify_password(payload.current_password, user.password_hash):
        audit_service.record(
            db, action="auth.password_change", actor_user_id=user.id, organization_id=user.organization_id,
            target_type="user", target_id=user.id, outcome="denied", request_id=request_id,
            context_metadata={"reason": "current password incorrect"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="New password must differ from the current password")
    try:
        user_service.set_password(db, user, payload.new_password)
    except user_service.PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    audit_service.record(
        db, action="auth.password_change", actor_user_id=user.id, organization_id=user.organization_id,
        target_type="user", target_id=user.id, request_id=request_id,
        context_metadata={"sessions_revoked": True},
    )
    db.commit()
    db.refresh(user)
    return _tokens(user, request, response)


@router.post("/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_sessions(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Signs the caller out everywhere (all issued tokens stop working)."""
    user = db.get(User, current_user.id)
    guard_demo_account(user.username)
    user_service.revoke_sessions(db, user)
    audit_service.record(
        db, action="auth.sessions_revoked", actor_user_id=user.id, organization_id=user.organization_id,
        target_type="user", target_id=user.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"scope": "self"},
    )
    db.commit()


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: AuthenticatedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> CurrentUserResponse:
    user = db.get(User, current_user.id)
    return CurrentUserResponse.model_validate(user)
