"""Bounded GeoJSON/CSV export of located records (Section
12). Mirrors app/services/export_service.py's existing discipline --
a hard row/feature ceiling (never a silent unbounded dump), explicit
`truncated` reporting rather than a misleading "complete" export, and
the same CSV-formula-injection guard -- applied here to the geospatial
subsystem's own record types instead of Event alone.

Only records with a currently-USABLE location
(app/geo/validation.classify_validation_status(...) == "valid") are
ever exported -- this reuses app/services/geo_query_service.py's
fetch_record_type(), the same fetch+validate path every other
geospatial query goes through, so an exported GeoJSON file can never
contain a fabricated or out-of-range coordinate.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.schemas.geospatial import ExportResultResponse, LocatedRecordResponse
from app.services.geo_query_service import fetch_record_type, resolve_record_types

settings = get_settings()

# Same leading-character set app/services/export_service.py guards
# against -- Section 12's "CSV-injection-safe" requirement, applied
# identically here rather than re-deriving a weaker rule.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

CSV_FIELDS = [
    "record_type", "record_id", "title", "summary", "source_id", "sensor_id",
    "latitude", "longitude", "coordinate_reference_system", "location_origin",
    "location_validation_status", "location_uncertainty_m", "altitude_m",
    "altitude_reference", "timestamp", "timestamp_type", "is_synthetic",
    "quality_findings", "distance_m",
]


def _csv_safe(value):
    if isinstance(value, str) and value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _serialize(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, list):
        return ";".join(str(v) for v in value)
    return value


def _fetch_bounded(
    db: Session, organization_id: str, *,
    record_types: Optional[list[str]],
    min_lat: Optional[float], max_lat: Optional[float],
    min_lon: Optional[float], max_lon: Optional[float],
    since: Optional[datetime], until: Optional[datetime],
    max_features: Optional[int],
) -> tuple[list[LocatedRecordResponse], bool, dict]:
    """Shared fetch for both export formats -- bounded at
    settings.GEOSPATIAL_MAX_EXPORT_FEATURES regardless of what the
    caller asks for (never an unrestricted full-dataset
    export)."""
    if (min_lat is None) != (max_lat is None) or (min_lon is None) != (max_lon is None):
        raise ValueError("min_lat/max_lat and min_lon/max_lon must be provided together")
    if min_lat is not None and (not (-90.0 <= min_lat <= 90.0) or not (-90.0 <= max_lat <= 90.0)):
        raise ValueError("latitude bounds must be within -90..90")
    if min_lon is not None and (not (-180.0 <= min_lon <= 180.0) or not (-180.0 <= max_lon <= 180.0)):
        raise ValueError("longitude bounds must be within -180..180")

    cap = min(max_features or settings.GEOSPATIAL_MAX_EXPORT_FEATURES, settings.GEOSPATIAL_MAX_EXPORT_FEATURES)
    types = resolve_record_types(record_types)

    all_items: list[LocatedRecordResponse] = []
    for rt in types:
        result = fetch_record_type(
            db, organization_id, rt,
            min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
            since=since, until=until, limit=cap,
        )
        all_items.extend(result.items)

    all_items.sort(key=lambda r: r.timestamp, reverse=True)
    truncated = len(all_items) > cap
    items = all_items[:cap]

    filters_applied = {
        "record_types": types,
        "min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon,
        "since": since.isoformat() if since else None, "until": until.isoformat() if until else None,
        "max_features": cap,
    }
    return items, truncated, filters_applied


def export_geojson(
    db: Session, organization_id: str, *,
    record_types: Optional[list[str]] = None,
    min_lat: Optional[float] = None, max_lat: Optional[float] = None,
    min_lon: Optional[float] = None, max_lon: Optional[float] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    max_features: Optional[int] = None,
) -> ExportResultResponse:
    """GeoJSON FeatureCollection -- coordinates in [longitude, latitude]
    order per the GeoJSON spec (RFC 7946), never [lat, lon]."""
    items, truncated, filters_applied = _fetch_bounded(
        db, organization_id, record_types=record_types,
        min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
        since=since, until=until, max_features=max_features,
    )

    features = []
    for item in items:
        properties = item.model_dump(exclude={"latitude", "longitude"})
        properties["timestamp"] = _serialize(properties["timestamp"])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [item.longitude, item.latitude]},
            "properties": properties,
        })

    generated_at = datetime.now(timezone.utc)
    content = json.dumps({
        "type": "FeatureCollection",
        "generated_at": generated_at.isoformat(),
        "truncated": truncated,
        "feature_count": len(features),
        "features": features,
    }, default=str)

    return ExportResultResponse(
        format="geojson", feature_count=len(features), truncated=truncated,
        generated_at=generated_at, filters_applied=filters_applied,
        content=content, content_type="application/geo+json",
        filename=f"aegis_geospatial_export_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.geojson",
    )


def export_csv(
    db: Session, organization_id: str, *,
    record_types: Optional[list[str]] = None,
    min_lat: Optional[float] = None, max_lat: Optional[float] = None,
    min_lon: Optional[float] = None, max_lon: Optional[float] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    max_features: Optional[int] = None,
) -> ExportResultResponse:
    items, truncated, filters_applied = _fetch_bounded(
        db, organization_id, record_types=record_types,
        min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
        since=since, until=until, max_features=max_features,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_FIELDS)
    for item in items:
        row = item.model_dump()
        writer.writerow([_csv_safe(_serialize(row[field])) for field in CSV_FIELDS])
    content = buffer.getvalue()

    generated_at = datetime.now(timezone.utc)
    return ExportResultResponse(
        format="csv", feature_count=len(items), truncated=truncated,
        generated_at=generated_at, filters_applied=filters_applied,
        content=content, content_type="text/csv",
        filename=f"aegis_geospatial_export_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.csv",
    )
