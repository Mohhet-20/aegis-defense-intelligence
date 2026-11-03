from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import Role

_VALID_ROLES = {r.value for r in Role}


def _validate_role(value: str) -> str:
    if value not in _VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
    return value


class LoginRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    # None for browser (cookie-mode) sessions: the refresh token is then only in an
    # HttpOnly cookie that page scripts cannot read.
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=1, max_length=255)


class RefreshRequest(BaseModel):
    # Omit in cookie mode (header X-Session-Mode: cookie); required otherwise.
    refresh_token: Optional[str] = None


class CurrentUserResponse(BaseModel):
    id: str
    username: str
    email: str
    display_name: str
    role: str
    organization_id: str
    is_active: bool
    last_login_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=255)
    role: str = Field(default="viewer")

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        return _validate_role(v)


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=200)
    role: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_role(v)


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    display_name: str
    role: str
    organization_id: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
