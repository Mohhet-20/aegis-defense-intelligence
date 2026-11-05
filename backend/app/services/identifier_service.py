"""Identifier and attribute comparison. Cautious,
auditable, namespace-aware matching between two events' structured
attributes -- NEVER a blind diff of arbitrary JSON, and never an
assumption that the same local identifier from two different sources
means the same real-world object.

Three outcomes for any single comparable field, always distinguished:
  * MATCH    -- both sides have it, and the values agree.
  * CONFLICT -- both sides have it, and the values disagree.
  * (nothing)-- one or both sides don't have it. Missing is UNKNOWN,
                never treated as agreement OR disagreement -- Section 7:
                "treat missing attributes as unknown."

This module produces the raw comparison data; `conflict_service.py`
turns CONFLICT entries into persisted `Conflict` rows, and
`correlation_service.py`/`relationship_service.py` can cite a MATCH as
part of a relationship's `explanation`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import get_settings
from app.models.event import Event

settings = get_settings()


@dataclass(frozen=True)
class IdentifierComparison:
    field: str
    namespace: Optional[str]  # the source_id a source-local id is scoped to, if applicable
    value_a: Any
    value_b: Any
    outcome: str  # "match" | "conflict"


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


def compare_source_local_identifiers(a: Event, b: Event) -> Optional[IdentifierComparison]:
    """`Event.external_id` is only ever unique WITHIN a source (
    the data platform's own `uq_events_source_external_id` constraint) -- comparing it
    across two DIFFERENT sources would be exactly the mistake Section 7
    warns about ("never assume identical local IDs from different
    sources identify the same object"), so this only ever compares when
    `a.source_id == b.source_id`. Cross-source identifier equality is
    not evaluated by this function at all."""
    if a.source_id != b.source_id:
        return None
    if not a.external_id or not b.external_id:
        return None
    outcome = "match" if _normalize(a.external_id) == _normalize(b.external_id) else "conflict"
    return IdentifierComparison(field="external_id", namespace=a.source_id, value_a=a.external_id, value_b=b.external_id, outcome=outcome)


def compare_asset_reference(a: Event, b: Event) -> Optional[IdentifierComparison]:
    if not a.asset_id or not b.asset_id:
        return None
    outcome = "match" if a.asset_id == b.asset_id else "conflict"
    return IdentifierComparison(field="asset_id", namespace=None, value_a=a.asset_id, value_b=b.asset_id, outcome=outcome)


def compare_attributes(a: Event, b: Event, *, attribute_keys: Optional[list[str]] = None) -> list[IdentifierComparison]:
    """Compares only the documented, identifier-like attribute keys
    ("use schema-aware comparisons rather than blindly
    comparing arbitrary JSON"); `attribute_keys` defaults to
    `settings.fusion_identifier_attribute_keys_list` so the allow-list
    is configuration, not a hard-coded constant buried in this module."""
    keys = attribute_keys if attribute_keys is not None else settings.fusion_identifier_attribute_keys_list
    results: list[IdentifierComparison] = []
    attrs_a = a.attributes or {}
    attrs_b = b.attributes or {}
    for key in keys:
        if key not in attrs_a or key not in attrs_b:
            continue  # unknown, not a conflict
        value_a, value_b = attrs_a[key], attrs_b[key]
        if value_a in (None, "") or value_b in (None, ""):
            continue
        outcome = "match" if _normalize(value_a) == _normalize(value_b) else "conflict"
        results.append(IdentifierComparison(field=f"attributes.{key}", namespace=None, value_a=value_a, value_b=value_b, outcome=outcome))
    return results


def compare_events(a: Event, b: Event, *, attribute_keys: Optional[list[str]] = None) -> list[IdentifierComparison]:
    """All identifier/attribute comparisons for a pair, in one call --
    used by both `conflict_service.py` (which only cares about the
    `conflict` outcomes) and anything explaining a `shares_source_identifier`
    relationship (which cares about the `match` outcomes)."""
    comparisons: list[IdentifierComparison] = []
    source_local = compare_source_local_identifiers(a, b)
    if source_local:
        comparisons.append(source_local)
    asset_ref = compare_asset_reference(a, b)
    if asset_ref:
        comparisons.append(asset_ref)
    comparisons.extend(compare_attributes(a, b, attribute_keys=attribute_keys))
    return comparisons
