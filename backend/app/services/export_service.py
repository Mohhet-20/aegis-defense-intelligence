"""Controlled export of normalized events.
Every export call is permission-gated at the route layer, explicitly
filtered (it reuses event_service's normal query filters -- never an
unrestricted "export everything" path), size-bounded, and audit-
logged. Only normalized Event fields are ever exported -- never a raw
record's payload and never any source's config_metadata -- so there is
nothing here that could leak a secret even if one were ever
(incorrectly) stored in config.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from app.models.event import Event

# A hard ceiling, not a default page size -- Section 17: "size limits."
# A request whose filters would return more rows than this is refused
# outright (never silently truncated, which would misrepresent a
# partial export as a complete one).
MAX_EXPORT_ROWS = 5000

# Leading characters a spreadsheet application (Excel, Google Sheets,
# LibreOffice) would interpret as the start of a formula -- Section 17's
# explicit "guard against CSV formula injection" requirement. Prefixing
# with a single quote forces the cell to be read as literal text.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

EXPORT_FIELDS = [
    "id", "source_id", "external_id", "event_type", "title", "description",
    "observed_at", "ingested_at", "latitude", "longitude", "source_severity",
    "priority", "confidence", "classification", "processing_status", "data_origin",
]


def _csv_safe(value):
    if isinstance(value, str) and value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _serialize(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def _row_dict(event: Event) -> dict:
    return {field: _serialize(getattr(event, field)) for field in EXPORT_FIELDS}


def export_events_csv(events: list[Event]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_FIELDS)
    for event in events:
        row = _row_dict(event)
        writer.writerow([_csv_safe(row[field]) for field in EXPORT_FIELDS])
    return buffer.getvalue()


def export_events_json(events: list[Event]) -> str:
    return json.dumps([_row_dict(event) for event in events], default=str)
