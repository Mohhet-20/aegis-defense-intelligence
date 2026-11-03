"""Public-demo mode (DEMO_MODE): shared, documented accounts that visitors cannot break.

The demo accounts are created by scripts/seed.py with a publicly documented password.
On a public showcase every visitor shares them, so one visitor must not be able to lock
the others out: in demo mode they are exempt from account lockout (the per-address rate
limit still applies) and their password, role, status and sessions cannot be changed.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.core.config import get_settings

# username -> role, as created by scripts/seed.py
DEMO_ACCOUNTS: dict[str, str] = {
    "admin": "administrator",
    "analyst": "analyst",
    "investigator": "investigator",
    "viewer": "viewer",
}
DEMO_PASSWORD = "DevPassword123!"  # pragma: allowlist secret (public, documented demo password)


def is_protected_demo_account(username: str | None) -> bool:
    return bool(get_settings().DEMO_MODE and username in DEMO_ACCOUNTS)


def guard_demo_account(username: str | None) -> None:
    """403 when a visitor tries to change a shared demo account."""
    if is_protected_demo_account(username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shared demo accounts cannot be changed in the public demo. Create a new user to try this.",
        )
