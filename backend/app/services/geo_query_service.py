"""Bounded spatial queries across every location-bearing record type.
A "located record" is one row from Event,
Sensor, Observation, or Asset that currently has a USABLE location
(app/geo/validation.classify_validation_status(...) == "valid") --
this module never fabricates a position for a record that lacks one.

Why validation is computed HERE, on every fetch, rather than read off
a stored `location_validation_status` column: that column exists on
every table (the migration), but no pre-original write path
(event/sensor/observation ingestion, asset creation) has ever
populated it -- it is NULL on every row created before this service
existed, and would stay NULL on ordinary new rows unless every one of
those write paths were also changed. Recomputing live from
latitude/longitude/coordinate_reference_system is cheap (a handful of
comparisons, no I/O) and -- critically -- always correct, instead of
being only as fresh as the last time something happened to write the
column. See docs/data/LOCATION_PROVENANCE_AND_UNCERTAINTY.md.

Antimeridian handling: a bounding box whose longitude span crosses
+/-180 is represented as ONE OR TWO sub-ranges by `_normalize_lon_ranges`
and queried with an OR across them -- never a single BETWEEN that would
silently match nothing (or everything) across the seam.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.geo.distance import bounding_box_for_radius, haversine_km
from app.geo.validation import classify_validation_status, validate_coordinates
from app.models.asset import Asset
from app.models.event import Event
from app.models.observation import Observation
from app.models.sensor import Sensor
from app.schemas.geospatial import (
    GEO_RECORD_TYPES,
    BoundsSearched,
    GeospatialQueryResponse,
    LocatedRecordResponse,
    SpatialGridCellResponse,
    TimeRangeSearched,
)

settings = get_settings()

RECORD_TYPE_MODELS = {"event": Event, "sensor": Sensor, "observation": Observation, "asset": Asset}

# Which timestamp field(s) each record type actually supports
# selecting between (Section 5C). Sensor/Asset have exactly one
# option -- their own `created_at`, exposed as "registered_at" since
# it describes when the record entered the registry, not when
# something was observed.
SELECTABLE_TIMESTAMP_TYPES = {
    "event": ("observed_at", "ingested_at"),
    "observation": ("observed_at", "ingested_at"),
    "sensor": ("registered_at",),
    "asset": ("registered_at",),
}


def _timestamp_and_type(row, record_type: str, requested_type: Optional[str]) -> tuple[datetime, str]:
    options = SELECTABLE_TIMESTAMP_TYPES[record_type]
    chosen = requested_type if requested_type in options else options[0]
    if chosen == "registered_at":
        return row.created_at, "registered_at"
    value = getattr(row, chosen, None)
    if value is None:
        # ingested_at can be NULL (distinct timestamps, never
        # defaulted into each other to hide a real gap) -- fall back to
        # observed_at and say so via the returned type, rather than
        # silently returning None where a datetime is required.
        return row.observed_at, "observed_at"
    return value, chosen


def _title_summary_source(row, record_type: str) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    if record_type == "event":
        return row.title, row.description, row.source_id, None
    if record_type == "sensor":
        return f"Sensor: {row.name}", row.description, row.source_id, None
    if record_type == "observation":
        return f"Observation: {row.observation_type}", None, row.source_id, row.sensor_id
    return f"Asset: {row.name}", row.description, None, None  # asset


def _is_synthetic(row, record_type: str) -> Optional[bool]:
    data_origin = getattr(row, "data_origin", None)
    if data_origin is None:
        return None
    return data_origin == "synthetic_demo"


def to_located_record(row, record_type: str, *, requested_timestamp_type: Optional[str] = None, distance_m: Optional[float] = None) -> Optional[LocatedRecordResponse]:
    """Converts one ORM row into a LocatedRecordResponse, or None if
    its coordinates are not currently usable for mapping."""
    status = classify_validation_status(row.latitude, row.longitude, coordinate_reference_system=row.coordinate_reference_system)
    if status != "valid":
        return None
    title, summary, source_id, sensor_id = _title_summary_source(row, record_type)
    timestamp, timestamp_type = _timestamp_and_type(row, record_type, requested_timestamp_type)
    findings = validate_coordinates(
        row.latitude, row.longitude,
        coordinate_reference_system=row.coordinate_reference_system,
        location_uncertainty_m=row.location_uncertainty_m,
    )
    quality_codes = [f.code for f in findings if f.code != "valid"]
    return LocatedRecordResponse(
        record_type=record_type,
        record_id=row.id,
        title=title,
        summary=summary,
        source_id=source_id,
        sensor_id=sensor_id,
        latitude=row.latitude,
        longitude=row.longitude,
        coordinate_reference_system=row.coordinate_reference_system,
        location_origin=row.location_origin,
        location_validation_status=status,
        location_uncertainty_m=row.location_uncertainty_m,
        altitude_m=row.altitude_m,
        altitude_reference=row.altitude_reference,
        timestamp=timestamp,
        timestamp_type=timestamp_type,
        is_synthetic=_is_synthetic(row, record_type),
        quality_findings=quality_codes,
        distance_m=distance_m,
    )


def _normalize_lon_ranges(min_lon: float, max_lon: float) -> list[tuple[float, float]]:
    if max_lon - min_lon >= 360.0:
        return [(-180.0, 180.0)]

    def wrap(x: float) -> float:
        while x < -180.0:
            x += 360.0
        while x > 180.0:
            x -= 360.0
        return x

    lo, hi = wrap(min_lon), wrap(max_lon)
    if lo <= hi:
        return [(lo, hi)]
    return [(lo, 180.0), (-180.0, hi)]


def _lon_filter(model, min_lon: float, max_lon: float):
    ranges = _normalize_lon_ranges(min_lon, max_lon)
    if len(ranges) == 1:
        lo, hi = ranges[0]
        return model.longitude.between(lo, hi)
    return or_(*(model.longitude.between(lo, hi) for lo, hi in ranges))


def _time_filter(model, record_type: str, timestamp_type: Optional[str], since: Optional[datetime], until: Optional[datetime]):
    if since is None and until is None:
        return None
    options = SELECTABLE_TIMESTAMP_TYPES[record_type]
    chosen = timestamp_type if timestamp_type in options else options[0]
    column = model.created_at if chosen == "registered_at" else getattr(model, chosen)
    clauses = []
    if since is not None:
        clauses.append(column >= since)
    if until is not None:
        clauses.append(column < until)  # half-open interval (Section 5C)
    return and_(*clauses) if clauses else None


@dataclass
class _FetchResult:
    items: list[LocatedRecordResponse]
    excluded_unusable: int


def fetch_record_type(
    db: Session, organization_id: str, record_type: str, *,
    min_lat: Optional[float] = None, max_lat: Optional[float] = None,
    min_lon: Optional[float] = None, max_lon: Optional[float] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    timestamp_type: Optional[str] = None, limit: int,
) -> _FetchResult:
    model = RECORD_TYPE_MODELS[record_type]
    stmt = select(model).where(
        model.organization_id == organization_id,
        model.latitude.is_not(None),
        model.longitude.is_not(None),
    )
    if min_lat is not None and max_lat is not None:
        stmt = stmt.where(model.latitude.between(min_lat, max_lat))
    if min_lon is not None and max_lon is not None:
        stmt = stmt.where(_lon_filter(model, min_lon, max_lon))
    time_clause = _time_filter(model, record_type, timestamp_type, since, until)
    if time_clause is not None:
        stmt = stmt.where(time_clause)

    # Fetch generously beyond `limit` so validity-filtering doesn't
    # under-fill a page -- capped at a sane multiple, never unbounded.
    rows = db.execute(stmt.limit(max(limit * 3, limit + 50))).scalars().all()

    items: list[LocatedRecordResponse] = []
    excluded = 0
    for row in rows:
        rec = to_located_record(row, record_type, requested_timestamp_type=timestamp_type)
        if rec is None:
            excluded += 1
        else:
            items.append(rec)
    return _FetchResult(items=items, excluded_unusable=excluded)


def resolve_record_types(record_types: Optional[list[str]]) -> list[str]:
    if not record_types:
        return list(GEO_RECORD_TYPES)
    return [t for t in record_types if t in GEO_RECORD_TYPES]


def query_viewport(
    db: Session, organization_id: str, *,
    min_lat: float, max_lat: float, min_lon: float, max_lon: float,
    record_types: Optional[list[str]] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    timestamp_type: Optional[str] = None,
    max_results: Optional[int] = None,
) -> GeospatialQueryResponse:
    if not (-90.0 <= min_lat <= 90.0) or not (-90.0 <= max_lat <= 90.0):
        raise ValueError("latitude bounds must be within -90..90")
    if min_lat > max_lat:
        raise ValueError("min_lat must not exceed max_lat")
    if not (-180.0 <= min_lon <= 180.0) or not (-180.0 <= max_lon <= 180.0):
        raise ValueError("longitude bounds must be within -180..180")

    types = resolve_record_types(record_types)
    cap = min(max_results or settings.GEOSPATIAL_MAX_RESULTS, settings.GEOSPATIAL_MAX_RESULTS)

    all_items: list[LocatedRecordResponse] = []
    excluded_total = 0
    for rt in types:
        result = fetch_record_type(
            db, organization_id, rt, min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
            since=since, until=until, timestamp_type=timestamp_type, limit=cap,
        )
        all_items.extend(result.items)
        excluded_total += result.excluded_unusable

    all_items.sort(key=lambda r: r.timestamp, reverse=True)
    total_matched = len(all_items)
    truncated = total_matched > cap
    returned = all_items[:cap]

    return GeospatialQueryResponse(
        items=returned,
        total_matched=total_matched,
        returned_count=len(returned),
        truncated=truncated,
        max_results=cap,
        bounds_searched=BoundsSearched(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon, crossed_antimeridian=min_lon > max_lon),
        time_range_searched=TimeRangeSearched(since=since, until=until, timestamp_type=timestamp_type or "observed_at") if (since or until) else None,
        record_types_searched=types,
        missing_or_invalid_location_count=excluded_total,
    )


def query_radius(
    db: Session, organization_id: str, *,
    center_latitude: float, center_longitude: float, radius_km: float,
    record_types: Optional[list[str]] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    timestamp_type: Optional[str] = None,
    max_results: Optional[int] = None,
) -> GeospatialQueryResponse:
    if not (-90.0 <= center_latitude <= 90.0):
        raise ValueError("center_latitude must be within -90..90")
    if not (-180.0 <= center_longitude <= 180.0):
        raise ValueError("center_longitude must be within -180..180")
    if radius_km <= 0:
        raise ValueError("radius_km must be positive")
    if radius_km > settings.GEOSPATIAL_MAX_RADIUS_KM:
        raise ValueError(f"radius_km must not exceed {settings.GEOSPATIAL_MAX_RADIUS_KM}")

    types = resolve_record_types(record_types)
    cap = min(max_results or settings.GEOSPATIAL_MAX_RESULTS, settings.GEOSPATIAL_MAX_RESULTS)
    min_lat, max_lat, min_lon, max_lon = bounding_box_for_radius(center_latitude, center_longitude, radius_km)

    candidates: list[LocatedRecordResponse] = []
    excluded_total = 0
    for rt in types:
        # Pre-filter with the cheap bounding box, then exact-check with
        # haversine below -- Section 5B.
        result = fetch_record_type(
            db, organization_id, rt, min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon,
            since=since, until=until, timestamp_type=timestamp_type, limit=settings.GEOSPATIAL_MAX_RESULTS * 5,
        )
        excluded_total += result.excluded_unusable
        for rec in result.items:
            distance_km = haversine_km(center_latitude, center_longitude, rec.latitude, rec.longitude)
            if distance_km <= radius_km:
                rec.distance_m = round(distance_km * 1000.0, 2)
                candidates.append(rec)

    candidates.sort(key=lambda r: r.distance_m or 0.0)
    total_matched = len(candidates)
    truncated = total_matched > cap
    returned = candidates[:cap]

    return GeospatialQueryResponse(
        items=returned,
        total_matched=total_matched,
        returned_count=len(returned),
        truncated=truncated,
        max_results=cap,
        radius_km=radius_km,
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        time_range_searched=TimeRangeSearched(since=since, until=until, timestamp_type=timestamp_type or "observed_at") if (since or until) else None,
        record_types_searched=types,
        missing_or_invalid_location_count=excluded_total,
    )


# A hard ceiling on how many raw rows a single grid-aggregation query
# will ever pull into Python, per record type -- same bounded-sample
# discipline as location_quality_service.MAX_QUALITY_SAMPLE_ROWS and
# geo_timeline_service.MAX_TEMPORAL_SAMPLE_ROWS ("avoid
# unbounded... aggregation").
MAX_GRID_SAMPLE_ROWS = 5000


def spatial_grid_counts(
    db: Session, organization_id: str, *,
    record_types: Optional[list[str]] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    grid_resolution_degrees: Optional[float] = None,
) -> tuple[list[SpatialGridCellResponse], bool]:
    """Counts of located records per fixed-size lat/lon grid cell
    (Section 9's "counts by geographic area"). This is a count of
    records in THIS project's own data -- never a density-based
    inference about real-world activity, and never a basis for
    assigning a threat level to an area (Section 20's prohibited-scope
    list: never draw a causal or threat conclusion from co-occurrence
    or density alone). Returns (cells, is_approximate) -- is_approximate
    is True only when more than MAX_GRID_SAMPLE_ROWS rows existed for
    ANY included record type, in which case the counts are a bounded
    sample, never silently presented as a complete total."""
    resolution = grid_resolution_degrees if grid_resolution_degrees is not None else settings.GEOSPATIAL_DEFAULT_GRID_RESOLUTION_DEGREES
    if resolution <= 0:
        raise ValueError("grid_resolution_degrees must be positive")
    types = resolve_record_types(record_types)

    cells: dict[tuple[float, float], dict] = {}
    any_approximate = False

    for rt in types:
        model = RECORD_TYPE_MODELS[rt]
        stmt = select(model).where(model.organization_id == organization_id, model.latitude.is_not(None), model.longitude.is_not(None))
        time_clause = _time_filter(model, rt, None, since, until)
        if time_clause is not None:
            stmt = stmt.where(time_clause)
        rows = db.execute(stmt.limit(MAX_GRID_SAMPLE_ROWS + 1)).scalars().all()
        if len(rows) > MAX_GRID_SAMPLE_ROWS:
            any_approximate = True
        for row in rows[:MAX_GRID_SAMPLE_ROWS]:
            if classify_validation_status(row.latitude, row.longitude, coordinate_reference_system=row.coordinate_reference_system) != "valid":
                continue
            cell_lat = math.floor(row.latitude / resolution) * resolution
            cell_lon = math.floor(row.longitude / resolution) * resolution
            key = (round(cell_lat, 6), round(cell_lon, 6))
            cell = cells.setdefault(key, {"count": 0, "record_types": {}})
            cell["count"] += 1
            cell["record_types"][rt] = cell["record_types"].get(rt, 0) + 1

    out = [
        SpatialGridCellResponse(
            min_lat=lat, max_lat=lat + resolution, min_lon=lon, max_lon=lon + resolution,
            count=data["count"], record_types=data["record_types"],
        )
        for (lat, lon), data in cells.items()
    ]
    out.sort(key=lambda c: c.count, reverse=True)
    return out, any_approximate
