from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.demo import DEMO_ACCOUNTS, DEMO_PASSWORD

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("")
def demo_info() -> dict:
    """Public. Tells the sign-in page whether this is a public demo and, only then,
    which shared accounts to offer. Outside DEMO_MODE it reveals nothing else."""
    settings = get_settings()
    if not settings.DEMO_MODE:
        return {"enabled": False}
    return {
        "enabled": True,
        "password": DEMO_PASSWORD,
        "accounts": [{"username": u, "role": r} for u, r in DEMO_ACCOUNTS.items()],
        "reset_hours": settings.DEMO_RESET_HOURS or None,
    }
