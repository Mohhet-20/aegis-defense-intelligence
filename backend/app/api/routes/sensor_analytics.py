from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.pagination import paginate
from app.core.config import get_settings
from app.core.security import AuthenticatedUser, Permission, require_permission
from app.db.session import get_db
from app.schemas.anomaly import AnomalyReviewRequest, AnomalyRunRequest, AnomalyRunResponse, ObservationAnomalyResponse
from app.schemas.common import Page, PageParams
from app.schemas.sensor import SensorHealthResponse
from app.schemas.timeseries import DescriptiveStatisticsResponse, GapSummaryResponse, TimeSeriesPointResponse, TimeSeriesResponse
from app.services import anomaly_service, audit_service, sensor_health_service, sensor_service, timeseries_service

router = APIRouter(prefix="/sensor-analytics", tags=["sensor-analytics"])
settings = get_settings()


def _resolve_sensor(db: Session, organization_id: str, sensor_id: str):
    sensor = sensor_service.get_sensor(db, organization_id, sensor_id)
    if sensor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sensor not found")
    return sensor


@router.get("/sensors/{sensor_id}/timeseries", response_model=TimeSeriesResponse)
def get_timeseries(
    sensor_id: str,
    measurement_type: str = Query(...),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    max_points: int = Query(default=500, ge=1, le=5000),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_READ)),
    db: Session = Depends(get_db),
) -> TimeSeriesResponse:
    sensor = _resolve_sensor(db, current_user.organization_id, sensor_id)
    try:
        since_r, until_r = timeseries_service.validate_time_range(since, until)
    except timeseries_service.QueryRangeTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    total_in_range = timeseries_service.count_observations(db, current_user.organization_id, sensor_id, measurement_type, since_r, until_r)
    rows, truncated = timeseries_service.fetch_series(db, current_user.organization_id, sensor_id, measurement_type, since_r, until_r)

    is_downsampled = False
    aggregation_note = None
    if len(rows) > max_points:
        rows = timeseries_service.downsample(rows, target_points=max_points)
        is_downsampled = True
        aggregation_note = f"deterministically stride-sampled to {len(rows)} of {total_in_range} points in range -- not every transient value is shown"
    elif truncated:
        aggregation_note = f"query range contains more than the {settings.SENSOR_MAX_RAW_SAMPLES}-sample cap; results were truncated, not averaged"
        is_downsampled = True

    configured_unit = (sensor.measurement_units or {}).get(measurement_type)
    return TimeSeriesResponse(
        sensor_id=sensor_id, measurement_type=measurement_type, unit=configured_unit, since=since_r, until=until_r,
        points=[
            TimeSeriesPointResponse(observation_id=o.id, observed_at=o.observed_at, value=o.measurement_value, unit=o.unit, validation_status=o.validation_status, quality_flags=o.quality_flags)
            for o in rows
        ],
        total_in_range=total_in_range, returned_count=len(rows), is_downsampled=is_downsampled, aggregation_note=aggregation_note,
    )


@router.get("/sensors/{sensor_id}/statistics", response_model=DescriptiveStatisticsResponse)
def get_statistics(
    sensor_id: str,
    measurement_type: str = Query(...),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_READ)),
    db: Session = Depends(get_db),
) -> DescriptiveStatisticsResponse:
    sensor = _resolve_sensor(db, current_user.organization_id, sensor_id)
    try:
        since_r, until_r = timeseries_service.validate_time_range(since, until)
    except (timeseries_service.QueryRangeTooLargeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    configured_unit = (sensor.measurement_units or {}).get(measurement_type)
    stats = timeseries_service.compute_statistics(
        db, current_user.organization_id, sensor_id, measurement_type, since_r, until_r,
        unit=configured_unit, nominal_interval_seconds=sensor.nominal_sampling_interval_seconds,
    )
    return DescriptiveStatisticsResponse(
        measurement_type=stats.measurement_type, unit=stats.unit, valid_count=stats.valid_count, invalid_count=stats.invalid_count,
        minimum=stats.minimum, maximum=stats.maximum, mean=stats.mean, median=stats.median, stdev_sample=stats.stdev_sample,
        percentiles=stats.percentiles, latest_valid_value=stats.latest_valid_value, latest_valid_observed_at=stats.latest_valid_observed_at,
        rate_of_change_per_second=stats.rate_of_change_per_second,
        gap_summary=GapSummaryResponse(gap_count=stats.gap_summary.gap_count, max_gap_seconds=stats.gap_summary.max_gap_seconds, missing_frame_like=stats.gap_summary.missing_frame_like) if stats.gap_summary else None,
        insufficient_sample=stats.insufficient_sample, method_version=stats.method_version,
    )


@router.get("/sensors/{sensor_id}/health", response_model=SensorHealthResponse)
def get_sensor_health(
    sensor_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_READ)),
    db: Session = Depends(get_db),
) -> SensorHealthResponse:
    sensor = _resolve_sensor(db, current_user.organization_id, sensor_id)
    health = sensor_health_service.compute_health(db, current_user.organization_id, sensor)
    return SensorHealthResponse.model_validate(health, from_attributes=True)


@router.post("/sensors/{sensor_id}/health/recompute", response_model=SensorHealthResponse)
def recompute_sensor_health(
    sensor_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.SENSOR_MANAGE)),
    db: Session = Depends(get_db),
) -> SensorHealthResponse:
    sensor = _resolve_sensor(db, current_user.organization_id, sensor_id)
    _, health = sensor_health_service.recompute_lifecycle_status(db, current_user.organization_id, sensor, actor_user_id=current_user.id)
    return SensorHealthResponse.model_validate(health, from_attributes=True)


@router.post("/anomalies/run", response_model=AnomalyRunResponse)
def run_anomaly_checks(
    payload: AnomalyRunRequest,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.OBSERVATION_INGEST)),
    db: Session = Depends(get_db),
) -> AnomalyRunResponse:
    sensor = _resolve_sensor(db, current_user.organization_id, payload.sensor_id)
    result = anomaly_service.run_checks(db, organization_id=current_user.organization_id, sensor=sensor, measurement_type=payload.measurement_type)
    return AnomalyRunResponse(
        created=[ObservationAnomalyResponse.model_validate(a) for a in result["created"]],
        already_known=[ObservationAnomalyResponse.model_validate(a) for a in result["already_known"]],
        insufficient_baseline=result["insufficient_baseline"],
    )


@router.get("/anomalies", response_model=Page[ObservationAnomalyResponse])
def list_anomalies(
    sensor_id: Optional[str] = Query(default=None),
    measurement_type: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    page_params: PageParams = Depends(),
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANOMALY_READ)),
    db: Session = Depends(get_db),
) -> Page:
    stmt = anomaly_service.list_anomalies_query(current_user.organization_id, sensor_id=sensor_id, measurement_type=measurement_type, review_status=review_status, category=category)
    return paginate(db, stmt, page_params.page, page_params.page_size, ObservationAnomalyResponse)


@router.get("/anomalies/{anomaly_id}", response_model=ObservationAnomalyResponse)
def get_anomaly(
    anomaly_id: str,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANOMALY_READ)),
    db: Session = Depends(get_db),
) -> ObservationAnomalyResponse:
    anomaly = anomaly_service.get_anomaly(db, current_user.organization_id, anomaly_id)
    if anomaly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anomaly not found")
    return ObservationAnomalyResponse.model_validate(anomaly)


@router.post("/anomalies/{anomaly_id}/review", response_model=ObservationAnomalyResponse)
def review_anomaly(
    anomaly_id: str,
    payload: AnomalyReviewRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_permission(Permission.ANOMALY_REVIEW)),
    db: Session = Depends(get_db),
) -> ObservationAnomalyResponse:
    anomaly = anomaly_service.get_anomaly(db, current_user.organization_id, anomaly_id)
    if anomaly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anomaly not found")
    updated = anomaly_service.review_anomaly(db, anomaly, reviewer_user_id=current_user.id, review_status=payload.review_status, review_note=payload.review_note)
    audit_service.record(
        db, action="anomaly.review", actor_user_id=current_user.id, organization_id=current_user.organization_id,
        target_type="observation_anomaly", target_id=anomaly.id, request_id=getattr(request.state, "request_id", None),
        context_metadata={"review_status": payload.review_status},
    )
    db.commit()
    return ObservationAnomalyResponse.model_validate(updated)
