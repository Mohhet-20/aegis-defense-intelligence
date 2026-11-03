from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.core.security import ROLE_PERMISSIONS, Role
from app.core import security_config

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/config")
def security_config_report(current_user: AuthenticatedUser = Depends(require_permission(Permission.SECURITY_READ))) -> dict:
    """Read-only, secret-free view of security-relevant settings and the
    findings derived from them. Never returns a secret value."""
    return security_config.evaluate(get_settings())


@router.get("/roles")
def role_permission_matrix(current_user: AuthenticatedUser = Depends(require_permission(Permission.USER_MANAGE))) -> dict:
    """Role -> permission review for access administration (read-only; the
    matrix is defined in code, not editable through the API)."""
    return {
        "roles": [
            {"role": r.value, "permissions": sorted(p.value for p in ROLE_PERMISSIONS[r]), "permission_count": len(ROLE_PERMISSIONS[r])}
            for r in Role
        ],
        "all_permissions": sorted(p.value for p in Permission),
    }
