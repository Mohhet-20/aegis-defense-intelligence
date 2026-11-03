"""Password policy + timing-equalisation helper (Phase 14, Phase D).

The policy is deliberately modest and documented: minimum length, at
least one letter and one digit, not a trivially guessable value derived
from the account name, and not on a small built-in deny list. It is NOT a
breach-corpus check and is not a substitute for MFA.
"""
from __future__ import annotations

from typing import Optional

from app.core.config import get_settings

_COMMON = {
    "password", "password1", "password123", "passw0rd123", "1234567890", "qwerty12345",
    "letmein1234", "admin12345", "administrator1", "welcome1234", "changeme123",
    "iloveyou123", "abc1234567",
}


def validate_password_policy(password: str, *, username: Optional[str] = None, email: Optional[str] = None) -> list[str]:
    """Returns a list of human-readable problems (empty list == acceptable)."""
    settings = get_settings()
    problems: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if not any(c.isalpha() for c in password):
        problems.append("must contain at least one letter")
    if not any(c.isdigit() for c in password):
        problems.append("must contain at least one digit")
    lowered = password.lower()
    if lowered in _COMMON:
        problems.append("is too common")
    for label, value in (("username", username), ("email", email)):
        if value:
            local = value.split("@")[0].lower()
            if len(local) >= 3 and local in lowered:
                problems.append(f"must not contain the {label}")
    if len(password.encode("utf-8")) > 72:
        problems.append("must be at most 72 bytes when UTF-8 encoded (bcrypt limit)")
    return problems
