"""HTTP-shaped errors raised workspace services.

Subclassing HTTPException means the existing app-wide handler already
renders them in the platform's {detail, request_id} error shape."""
from __future__ import annotations

from fastapi import HTTPException, status


class WorkspaceError(HTTPException):
    pass


def not_found(what: str) -> WorkspaceError:
    return WorkspaceError(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def conflict(detail: str) -> WorkspaceError:
    return WorkspaceError(status_code=status.HTTP_409_CONFLICT, detail=detail)


def invalid(detail: str) -> WorkspaceError:
    return WorkspaceError(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def forbidden(detail: str) -> WorkspaceError:
    return WorkspaceError(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
