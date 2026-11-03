"""SECRET_KEY rotation with a grace period (KNOWN_RISKS 47): former keys listed in
SECRET_KEY_PREVIOUS verify existing tokens; new tokens are always signed with SECRET_KEY."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.security import create_access_token, decode_token
from app.core.security_config import startup_blockers

OLD = "old-key-" + "o" * 40
NEW = "new-key-" + "n" * 40


def _token(key: str, minutes: int = 5) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": "u1", "role": "analyst", "type": "access", "tv": 0, "iat": now, "exp": now + timedelta(minutes=minutes)},
                      key, algorithm="HS256")


def test_tokens_from_a_listed_previous_key_verify_until_it_is_removed(monkeypatch):
    s = get_settings()
    old_token = _token(OLD)
    monkeypatch.setattr(s, "SECRET_KEY", NEW)
    monkeypatch.setattr(s, "SECRET_KEY_PREVIOUS", "")
    with pytest.raises(HTTPException):          # rotated without a grace period: old token refused
        decode_token(old_token)
    monkeypatch.setattr(s, "SECRET_KEY_PREVIOUS", f" {OLD} , ")
    assert decode_token(old_token)["sub"] == "u1"  # grace period: accepted


def test_new_tokens_are_signed_only_with_the_current_key(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "SECRET_KEY", NEW)
    monkeypatch.setattr(s, "SECRET_KEY_PREVIOUS", OLD)
    token = create_access_token("u1", "analyst")
    jwt.decode(token, NEW, algorithms=["HS256"])            # verifies with the current key
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, OLD, algorithms=["HS256"])


def test_expired_or_unknown_key_tokens_are_still_refused(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "SECRET_KEY", NEW)
    monkeypatch.setattr(s, "SECRET_KEY_PREVIOUS", OLD)
    with pytest.raises(HTTPException):
        decode_token(_token(OLD, minutes=-1))                 # expired, even though the key is listed
    with pytest.raises(HTTPException):
        decode_token(_token("someone-else-" + "x" * 40))      # never-listed key


def test_short_previous_key_blocks_production_start(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ENVIRONMENT", "production")
    monkeypatch.setattr(s, "SECRET_KEY", NEW)
    monkeypatch.setattr(s, "CORS_ALLOWED_ORIGINS", "https://aegis.example.org")
    monkeypatch.setattr(s, "SECRET_KEY_PREVIOUS", "short")
    assert any("SECRET_KEY_PREVIOUS" in b for b in startup_blockers(s))
    monkeypatch.setattr(s, "SECRET_KEY_PREVIOUS", OLD)
    assert not any("SECRET_KEY_PREVIOUS" in b for b in startup_blockers(s))
