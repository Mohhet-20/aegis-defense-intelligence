"""Section envelope builder: guarantees every emitted number is a catalogued metric."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, has_permission
from app.reporting import definitions as defs
from app.reporting.window import AnalyticsFilters, AnalyticsWindow, as_utc, now_utc


@dataclass
class Ctx:
    db: Session
    user: AuthenticatedUser
    window: AnalyticsWindow
    filters: AnalyticsFilters
    now: datetime = field(default_factory=now_utc)

    @property
    def org(self) -> str:
        return self.user.organization_id

    def can(self, perm: Permission) -> bool:
        return has_permission(self.user.role, perm)


class Section:
    def __init__(self, section_id: str, ctx: Ctx):
        self.id, self.ctx = section_id, ctx
        self.values: dict[str, dict] = {}
        self.tables: dict[str, dict] = {}
        self.caveats: list[str] = []
        self.sample_counts: dict[str, Any] = {}
        self.freshness: dict[str, Any] = {}
        self.drilldown: dict[str, str] = {}
        self.status = "ok"  # ok | partial | not_authorized | empty

    def value(self, mid: str, value: Any, n: Optional[int] = None, reason: Optional[str] = None) -> None:
        meta = defs.CATALOG[mid]  # KeyError == undefined metric: a bug, caught by tests
        self.values[mid] = {"value": value, "unit": meta["unit"], "n": n, "reason": reason if value is None else None}

    def rate(self, mid: str, num: int, den: int, minimum: int = 1) -> None:
        if den <= 0:
            self.value(mid, None, den, "no_records_in_window")
        elif den < minimum:
            self.value(mid, None, den, f"insufficient_sample(n={den}<{minimum})")
        else:
            self.value(mid, round(num / den, 4), den)

    def table(self, tid: str, mid: str, title: str, columns: list[str], rows: list[list], unit: Optional[str] = None) -> None:
        meta = defs.CATALOG[mid]
        self.tables[tid] = {"title": title, "unit": unit or meta["unit"], "columns": columns, "rows": rows, "metric_ids": [mid]}

    def caveat(self, text: str) -> None:
        if text not in self.caveats:
            self.caveats.append(text)

    def freshness_from(self, latest: Optional[datetime], label: str = "latest_record_at") -> None:
        s = get_settings()
        if latest is None:
            self.freshness = {label: None, "age_hours": None, "stale": None, "note": "No stored records match; freshness cannot be stated."}
            return
        latest = as_utc(latest)
        age = (self.ctx.now - latest).total_seconds() / 3600
        self.freshness = {label: latest.isoformat(), "age_hours": round(age, 2), "stale": age > s.ANALYTICS_STALE_HOURS, "stale_after_hours": s.ANALYTICS_STALE_HOURS}

    def build(self) -> dict:
        return {
            "section": self.id, "status": self.status, "definition_version": defs.DEFINITION_VERSION, "generated_at": self.ctx.now.isoformat(),
            "window": self.ctx.window.describe(), "filters": self.ctx.filters.describe(), "sample_counts": self.sample_counts,
            "freshness": self.freshness, "values": self.values, "tables": self.tables, "caveats": self.caveats, "drilldown": self.drilldown,
        }


def not_authorized(section_id: str, ctx: Ctx, needs: str) -> dict:
    s = Section(section_id, ctx)
    s.status = "not_authorized"
    s.caveat(f"Requires the {needs} permission; no data from this section is included.")
    return s.build()
