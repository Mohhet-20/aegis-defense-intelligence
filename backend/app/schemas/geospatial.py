"""Response/request shapes for the geospatial intelligence subsystem.
See app/services/geo_query_service.py, geo_timeline_service.py,
location_quality_service.py, spatial_relationship_service.py,
geo_export_service.py for the logic these shapes carry."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

GEO_RECORD_TYPES = ("event", "sensor", "observation", "asset")

# Which timestamp a located record's `timestamp`/`timestamp_type` fields
# actually carry -- Section 2's "do not collapse these timestamps into
# one generic date." "registered_at" (created_at) is the only option
# for sensor/asset, which have no per-occurrence event time of their
# own; event/observation support an explicit choice between the two.
TIMESTAMP_TYPES = ("observed_at", "ingested_at", "registered_at")


class LocatedRecordResponse(BaseModel):
    record_type: str
    record_id: str
    title: str
    summary: Optional[str] = None
    source_id: Optional[str] = None
    sensor_id: Optional[str] = None

    latitude: float
    longitude: float
    coordinate_reference_system: str
    location_origin: Optional[str]
    location_validation_status: Optional[str]
    location_uncertainty_m: Optional[float]
    altitude_m: Optional[float]
    altitude_reference: Optional[str]

    timestamp: datetime
    timestamp_type: str

    # None means "not applicable to this record type" (sensor/asset
    # carry no data_origin field) -- never defaulted to False, which
    # would falsely claim the record is known-real.
    is_synthetic: Optional[bool] = None

    # Informational-only findings from app/geo/validation.py (e.g.
    # "uncertainty_unavailable", "stale_location_timestamp") -- a
    # record only reaches this response at all if its location is
    # USABLE (location_validation_status == "valid"), so this list
    # never contains an error-level finding.
    quality_findings: list[str] = Field(default_factory=list)

    # Only populated by a radius query (Section 5B: "return distance
    # only when it has actually been calculated").
    distance_m: Optional[float] = None


class BoundsSearched(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    crossed_antimeridian: bool = False


class TimeRangeSearched(BaseModel):
    since: Optional[datetime]
    until: Optional[datetime]
    timestamp_type: str


class GeospatialQueryResponse(BaseModel):
    """Shared response shape for viewport, radius, and combined
    queries. `truncated` + `total_matched` are how Section
    5A's 'prevent unrestricted full-dataset downloads' is made honest
    rather than silent."""

    items: list[LocatedRecordResponse]
    total_matched: int
    returned_count: int
    truncated: bool
    max_results: int
    bounds_searched: Optional[BoundsSearched] = None
    radius_km: Optional[float] = None
    center_latitude: Optional[float] = None
    center_longitude: Optional[float] = None
    time_range_searched: Optional[TimeRangeSearched] = None
    record_types_searched: list[str]
    missing_or_invalid_location_count: int


class LocationFindingResponse(BaseModel):
    code: str
    is_error: bool
    explanation: str


class LocationQualityRecordResponse(BaseModel):
    record_type: str
    record_id: str
    title: str
    latitude: Optional[float]
    longitude: Optional[float]
    coordinate_reference_system: str
    location_validation_status: Optional[str]
    findings: list[LocationFindingResponse]


class LocationQualitySummaryResponse(BaseModel):
    record_types_checked: list[str]
    total_records_checked: int
    missing_count: int
    invalid_range_count: int
    non_finite_count: int
    unsupported_crs_count: int
    valid_count: int
    uncertainty_unavailable_count: int
    stale_count: int
    by_record_type: dict


class SpatialRelationshipCandidateResponse(BaseModel):
    relationship_id: str
    source_ref_type: str
    source_ref_id: str
    source_record_type: str
    source_record_id: str
    target_ref_type: str
    target_ref_id: str
    target_record_type: str
    target_record_id: str
    relationship_type: str
    distance_m: Optional[float]
    time_difference_seconds: Optional[float]
    rule_version: str
    explanation: str
    review_status: str
    origin: str
    source_location_quality: Optional[str]
    target_location_quality: Optional[str]
    created_at: datetime


class SpatialRelationshipGenerateRequest(BaseModel):
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    distance_threshold_m: Optional[float] = Field(default=None, gt=0)
    time_window_seconds: Optional[int] = Field(default=None, gt=0)


class SpatialRelationshipRunResponse(BaseModel):
    candidates_created: int
    candidates_already_known: int
    pairs_considered: int
    # How many located records were compared, and whether the per-run cap
    # (GEOSPATIAL_RELATIONSHIP_MAX_CANDIDATES) cut the input -- in which case only
    # the earliest records in the window were analysed. Never silently truncated.
    candidates_considered: int = 0
    candidates_truncated: bool = False
    rule_version: str
    distance_threshold_m: float
    time_window_seconds: int


class TimeBucketCountResponse(BaseModel):
    bucket_start: datetime
    bucket_end: datetime
    count: int


class TimeBucketCountsResponse(BaseModel):
    """`is_approximate` mirrors geo_timeline_service.time_bucket_counts's
    own (buckets, is_approximate) return -- Section 15: a bounded
    sample is always reported as such, never presented as a silently
    complete count."""

    buckets: list[TimeBucketCountResponse]
    is_approximate: bool


class TemporalGapResponse(BaseModel):
    record_type: str
    gap_start: datetime
    gap_end: datetime
    gap_seconds: float


class TemporalGapsResponse(BaseModel):
    gaps: list[TemporalGapResponse]
    is_approximate: bool


class SpatialGridCellResponse(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    count: int
    record_types: dict


class SpatialGridResponse(BaseModel):
    cells: list[SpatialGridCellResponse]
    is_approximate: bool


class GeospatialOverviewResponse(BaseModel):
    located_records_total: int
    located_records_by_type: dict
    missing_or_invalid_location_total: int
    recent_located_records: list[LocatedRecordResponse]
    spatial_relationship_candidates_unreviewed: int
    location_conflicts_unreviewed: int
    temporal_coverage_earliest: Optional[datetime]
    temporal_coverage_latest: Optional[datetime]
    data_quality_summary: LocationQualitySummaryResponse


class GeoJsonExportRequest(BaseModel):
    record_types: list[str]
    min_lat: Optional[float] = None
    max_lat: Optional[float] = None
    min_lon: Optional[float] = None
    max_lon: Optional[float] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    max_features: Optional[int] = None


class ExportResultResponse(BaseModel):
    format: str
    feature_count: int
    truncated: bool
    generated_at: datetime
    filters_applied: dict
    content: str
    content_type: str
    filename: str
