from __future__ import annotations

from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.common import Page

settings = get_settings()

M = TypeVar("M")


def paginate(db: Session, stmt, page: int, page_size: int, response_model) -> Page:
    """Applies a bounded LIMIT/OFFSET to `stmt` and returns a Page of
    `response_model`-validated items plus a real total count -- Section
    19 requires bounded list queries; page_size is clamped server-side
    regardless of what a client requests."""
    page = max(page, 1)
    page_size = max(1, min(page_size, settings.MAX_PAGE_SIZE))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().all()
    items = [response_model.model_validate(r) for r in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)
