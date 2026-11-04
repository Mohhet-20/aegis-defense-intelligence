from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.routes.auth import _tokens
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.services import audit_service

router = APIRouter(prefix="/demo", tags=["demo"])

settings = get_settings()

# The account a visitor's "Explore the live demo" session uses: it can ingest data, review detections and write
# assessments, and it cannot administer users or security settings.
GUEST_USERNAME = "analyst"


@router.get("")
def demo_info() -> dict:
    """Public. Tells the sign-in page whether this is a public demo. It never reveals an account or a password:
    visitors get in through POST /demo/session."""
    if not get_settings().DEMO_MODE:
        return {"enabled": False}
    return {"enabled": True, "reset_hours": get_settings().DEMO_RESET_HOURS or None}


@router.post("/session", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def demo_session(request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    """Public demo only: signs the visitor in as the guest analyst with no password involved (the account's own
    password is random and unknown; scripts/secure_demo_accounts.py). 404 outside DEMO_MODE."""
    if not get_settings().DEMO_MODE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    user = db.query(User).filter_by(username=GUEST_USERNAME).first()
    if user is None or not user.is_active or user.role == "administrator":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="The demo is not available")
    audit_service.record(
        db, action="auth.demo_session", actor_user_id=user.id, organization_id=user.organization_id,
        outcome="success", request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return _tokens(user, request, response)
