from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.demo import is_protected_demo_account
from app.core.passwords import validate_password_policy
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.services.timeutil import ensure_utc

settings = get_settings()

# Verified against when the identifier is unknown, so "no such user" costs
# the same bcrypt work as "wrong password" (login timing equalisation).
_DUMMY_HASH: Optional[str] = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-password-0")
    return _DUMMY_HASH


class PasswordPolicyError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("Password " + "; ".join(problems))
        self.problems = problems


class AccessChangeError(ValueError):
    """An account change refused for safety (self-lockout, last admin)."""


class DuplicateUserError(ValueError):
    pass


def get_by_username_or_email(db: Session, identifier: str) -> Optional[User]:
    stmt = select(User).where((User.username == identifier) | (User.email == identifier))
    return db.execute(stmt).scalar_one_or_none()


def create_user(
    db: Session,
    *,
    organization_id: str,
    username: str,
    email: str,
    display_name: str,
    password: str,
    role: str,
) -> User:
    if get_by_username_or_email(db, username) or get_by_username_or_email(db, email):
        raise DuplicateUserError("A user with this username or email already exists")
    problems = validate_password_policy(password, username=username, email=email)
    if problems:
        raise PasswordPolicyError(problems)
    user = User(
        organization_id=organization_id,
        username=username,
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()  # the route commits AFTER writing the audit row, so both persist or neither does
    return user


def is_locked_out(user: User) -> bool:
    return user.locked_until is not None and ensure_utc(user.locked_until) > datetime.now(timezone.utc)


def record_login_failure(db: Session, user: User) -> None:
    if is_protected_demo_account(user.username):
        return  # shared public-demo account: never locked (the rate limit still applies)
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCOUNT_LOCKOUT_MINUTES)
    db.add(user)
    db.commit()


def record_login_success(db: Session, user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()


def authenticate(db: Session, identifier: str, password: str) -> tuple[Optional[User], Optional[str]]:
    """Returns (user, None) on success, or (None, reason) on failure.
    `reason` is always a generic string -- never reveals whether the
    username or the password was the problem (standard login-enumeration
    mitigation)."""
    user = get_by_username_or_email(db, identifier)
    if user is None:
        verify_password(password, _dummy_hash())  # timing equalisation
        return None, "Invalid credentials"
    if is_locked_out(user):
        return None, "Account is temporarily locked due to repeated failed logins"
    if not verify_password(password, user.password_hash):
        if user.is_active:
            record_login_failure(db, user)
        return None, "Invalid credentials"
    # Only a caller who proved knowledge of the password learns the
    # account is disabled (no unauthenticated account-state oracle).
    if not user.is_active:
        return None, "Account is disabled"
    record_login_success(db, user)
    return user, None


def count_active_admins(db: Session, organization_id: str) -> int:
    from sqlalchemy import func

    return db.scalar(
        select(func.count()).select_from(User).where(
            User.organization_id == organization_id, User.role == "administrator", User.is_active.is_(True)
        )
    ) or 0


def check_access_change(
    db: Session, user: User, *, acting_user_id: Optional[str], role: Optional[str], is_active: Optional[bool]
) -> None:
    """Refuses account changes that would lock the organization out:
    changing your OWN role / disabling yourself, or demoting / disabling
    the last active administrator. Raises AccessChangeError."""
    role_changes = role is not None and role != user.role
    disables = is_active is False and user.is_active
    if acting_user_id is not None and user.id == acting_user_id and (role_changes or disables):
        raise AccessChangeError("You cannot change your own role or disable your own account")
    if user.role == "administrator" and user.is_active and (
        (role is not None and role != "administrator") or is_active is False
    ):
        if count_active_admins(db, user.organization_id) <= 1:
            raise AccessChangeError("Cannot demote or disable the last active administrator of the organization")


def revoke_sessions(db: Session, user: User) -> None:
    """Invalidates every access/refresh token issued so far (flush only)."""
    user.token_version = (user.token_version or 0) + 1
    db.add(user)
    db.flush()


def update_user(db: Session, user: User, *, display_name: Optional[str] = None, role: Optional[str] = None, is_active: Optional[bool] = None, acting_user_id: Optional[str] = None) -> User:
    check_access_change(db, user, acting_user_id=acting_user_id, role=role, is_active=is_active)
    revoke = (role is not None and role != user.role) or (is_active is False and user.is_active)
    if display_name is not None:
        user.display_name = display_name
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if revoke:
        user.token_version = (user.token_version or 0) + 1
    db.add(user)
    db.flush()  # committed by the route together with its audit row
    return user


def set_password(db: Session, user: User, new_password: str) -> None:
    """Applies the password policy, stores the new hash and revokes all
    existing sessions. Flush only -- the caller commits."""
    problems = validate_password_policy(new_password, username=user.username, email=user.email)
    if problems:
        raise PasswordPolicyError(problems)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.token_version = (user.token_version or 0) + 1
    db.add(user)
    db.flush()


def list_users(db: Session, organization_id: str) -> list[User]:
    stmt = select(User).where(User.organization_id == organization_id).order_by(User.created_at)
    return list(db.execute(stmt).scalars().all())
