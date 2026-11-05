"""Sensor observation batch ingestion. Reuses
the SAME `IngestionJob`/`RawRecord` tables the Event pipeline
uses -- `RawRecord.event_id` simply stays NULL for every row this
module creates, and `IngestionJob.job_type` gets new sensor-specific
values ("sensor_json_batch", "sensor_csv_batch", "sensor_synthetic").
This is deliberately NOT a parallel ingestion-job table: Section 1's
"extend existing models rather than creating competing duplicates."

One record always produces exactly one RawRecord (the quarantine/
provenance reference, Section 6: "preserve a quarantine reference so
authorized users can inspect ingestion failures") and, ONLY if the
record's quality outcome is accepted, exactly one Observation. A
record is never silently dropped.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.types import ConnectorResult
from app.core.config import get_settings
from app.models.ingestion_job import IngestionJob
from app.models.observation import SENSOR_OBSERVATION_SCHEMA_VERSION, Observation
from app.models.raw_record import RawRecord
from app.models.sensor import Sensor
from app.sensors import quality as quality_lib
from app.sensors.adapters.registry import (
    get_connector_adapter_class,
    get_file_adapter_class,
)
from app.services import normalization_service as norm
from app.services.timeutil import ensure_utc

settings = get_settings()

SENSOR_INGESTION_JOB_TYPES = ("sensor_json_batch", "sensor_csv_batch", "sensor_synthetic")
SENSOR_RETRYABLE_JOB_TYPES = {"sensor_synthetic"}


# Keys with a dedicated Observation/RawRecord column -- anything else
# in a record is preserved verbatim in Observation.payload, mirroring
# ingestion_service.py's _build_attributes.
_RESERVED_KEYS = {"sensor_id", "measurement_type", "value", "unit", "observed_at", "external_id", "latitude", "longitude", "device_status", "calibration_metadata", "uncertainty_metadata", "note"}

# How many of a sensor+measurement_type's most recent VALID values this
# module keeps in memory per batch, for the repeated-value/baseline
# checks -- bounded, never an unbounded in-batch cache.
_RECENT_VALUES_WINDOW = max(settings.SENSOR_MAX_IDENTICAL_RUN, settings.SENSOR_ANOMALY_ROLLING_WINDOW) + 5


class UnsupportedBatchFormatError(ValueError):
    pass


class BatchTooLargeError(ValueError):
    pass


class SensorRetiredError(ValueError):
    pass


def _build_attributes(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in _RESERVED_KEYS}


class _SensorContext:
    """Per-(sensor_id, measurement_type) rolling context for one batch
    -- seeded from the DB once, then updated in-memory as the batch's
    own records are accepted, so a 2000-record batch issues one seed
    query per distinct key rather than one per record."""

    def __init__(self, db: Session, organization_id: str, sensor_id: str, measurement_type: str):
        stmt = (
            select(Observation.observed_at, Observation.measurement_value)
            .where(
                Observation.organization_id == organization_id,
                Observation.sensor_id == sensor_id,
                Observation.observation_type == measurement_type,
                Observation.measurement_value.is_not(None),
            )
            .order_by(Observation.observed_at.desc())
            .limit(_RECENT_VALUES_WINDOW)
        )
        rows = list(db.execute(stmt).all())[::-1]  # ascending order
        self.recent_values: list[float] = [r[1] for r in rows]
        self.latest_observed_at: Optional[datetime] = ensure_utc(rows[-1][0]) if rows else None

    def record_accepted(self, observed_at: datetime, value: Optional[float]) -> None:
        if value is not None:
            self.recent_values.append(value)
            self.recent_values = self.recent_values[-_RECENT_VALUES_WINDOW:]
        observed_at = ensure_utc(observed_at)
        if self.latest_observed_at is None or observed_at > self.latest_observed_at:
            self.latest_observed_at = observed_at


def _resolve_sensor(db: Session, organization_id: str, sensor_id: str) -> Optional[Sensor]:
    stmt = select(Sensor).where(Sensor.id == sensor_id, Sensor.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def _existing_raw_record_id(db: Session, organization_id: str, source_id: str, external_id: str) -> Optional[str]:
    stmt = (
        select(RawRecord.id)
        .where(RawRecord.organization_id == organization_id, RawRecord.source_id == source_id, RawRecord.external_record_id == external_id, RawRecord.is_duplicate.is_(False))
        .order_by(RawRecord.created_at.asc())
    )
    row = db.execute(stmt).first()
    return row[0] if row else None


def _observation_already_exists(db: Session, organization_id: str, source_id: str, external_id: str) -> bool:
    stmt = (
        select(Observation.id)
        .join(RawRecord, Observation.source_record_id == RawRecord.id)
        .where(RawRecord.organization_id == organization_id, RawRecord.source_id == source_id, RawRecord.external_record_id == external_id)
    )
    return db.execute(stmt).first() is not None


def _process_batch(
    db: Session,
    *,
    job: IngestionJob,
    organization_id: str,
    source_id: str,
    connector_result: ConnectorResult,
    data_origin: str,
    seen_external_ids: set[str],
    seen_raw_record_ids: dict[str, str],
    sensor_contexts: dict[tuple[str, str], _SensorContext],
    sensor_cache: dict[str, Optional[Sensor]],
) -> tuple[int, int, int, int, list[dict]]:
    accepted = rejected = skipped = duplicate = 0
    errors: list[dict] = []
    received_at = datetime.now(timezone.utc)

    for connector_error in connector_result.errors:
        rejected += 1
        errors.append({"error": f"[{connector_error.category.value}] {connector_error.message}"})

    for index, raw in enumerate(connector_result.records):
        record = raw.payload
        try:
            if not isinstance(record, dict):
                rejected += 1
                errors.append({"index": index, "error": f"record is not an object: {type(record).__name__}"})
                continue

            sensor_id = record.get("sensor_id")
            sensor = sensor_cache.get(sensor_id) if sensor_id in sensor_cache else _resolve_sensor(db, organization_id, str(sensor_id)) if sensor_id else None
            sensor_cache[sensor_id] = sensor

            fingerprint = norm.content_fingerprint(record)
            external_id = raw.external_id or str(record.get("external_id") or "") or fingerprint

            is_duplicate = False
            duplicate_reason: Optional[str] = None
            duplicate_of_id: Optional[str] = None
            if external_id in seen_external_ids:
                is_duplicate = True
                duplicate_reason = "external_id repeated earlier in this same ingestion batch"
                duplicate_of_id = seen_raw_record_ids.get(external_id)
            elif _observation_already_exists(db, organization_id, source_id, external_id):
                is_duplicate = True
                duplicate_reason = "external_id already produced an observation for this source from a previous ingestion"
                duplicate_of_id = _existing_raw_record_id(db, organization_id, source_id, external_id)

            if sensor is None:
                outcome = quality_lib.QualityOutcome(validation_status="invalid", quality_flags=["unknown_sensor"], is_accepted=False)
                issues_for_record = [quality_lib.QualityIssue("unknown_sensor", f"sensor_id '{sensor_id}' does not exist in this organization", is_error=True)]
            elif sensor.lifecycle_status == "retired":
                outcome = quality_lib.QualityOutcome(validation_status="invalid", quality_flags=["sensor_retired"], is_accepted=False)
                issues_for_record = [quality_lib.QualityIssue("sensor_retired", f"sensor '{sensor_id}' is retired and accepts no further observations", is_error=True)]
            else:
                measurement_type = record.get("measurement_type")
                ctx_key = (sensor.id, str(measurement_type))
                if ctx_key not in sensor_contexts:
                    sensor_contexts[ctx_key] = _SensorContext(db, organization_id, sensor.id, str(measurement_type))
                ctx = sensor_contexts[ctx_key]

                configured_unit = (sensor.measurement_units or {}).get(str(measurement_type))
                operating_range = (sensor.operating_range or {}).get(str(measurement_type))

                outcome = quality_lib.evaluate_observation(
                    record,
                    ingested_at=received_at,
                    configured_unit=configured_unit,
                    operating_range=operating_range,
                    recent_values=ctx.recent_values,
                    latest_prior_observed_at=ctx.latest_observed_at,
                    nominal_interval_seconds=sensor.nominal_sampling_interval_seconds,
                    stale_after_seconds=settings.SENSOR_STALE_AFTER_SECONDS,
                    missed_multiple=settings.SENSOR_HEARTBEAT_MISSED_INTERVAL_MULTIPLE,
                    max_identical_run=settings.SENSOR_MAX_IDENTICAL_RUN,
                )
                issues_for_record = outcome.issues

            raw_record_row = RawRecord(
                organization_id=organization_id,
                source_id=source_id,
                ingestion_job_id=job.id,
                event_id=None,
                external_record_id=external_id or None,
                connector_type=connector_result.connector_type,
                connector_version=connector_result.connector_version,
                normalization_version=quality_lib.QUALITY_RULESET_VERSION,
                schema_version=SENSOR_OBSERVATION_SCHEMA_VERSION,
                content_fingerprint=fingerprint,
                payload=record,
                source_observed_at_raw=raw.source_observed_at_raw or (str(record.get("observed_at")) if record.get("observed_at") is not None else None),
                received_at=received_at,
                validation_status="valid" if outcome.is_accepted else "invalid",
                validation_errors=[{"code": i.code, "field": None, "message": i.message} for i in issues_for_record if i.is_error],
                validation_warnings=[{"code": i.code, "field": None, "message": i.message} for i in issues_for_record if not i.is_error],
                is_duplicate=is_duplicate,
                duplicate_of_raw_record_id=duplicate_of_id,
                duplicate_reason=duplicate_reason,
            )
            db.add(raw_record_row)
            db.flush()

            if is_duplicate:
                duplicate += 1
                continue

            if not outcome.is_accepted:
                rejected += 1
                message = "; ".join(i.message for i in issues_for_record if i.is_error) or "record could not be accepted"
                errors.append({"index": index, "error": message})
                continue

            latitude = longitude = None
            try:
                latitude, longitude = norm.normalize_coordinates(record.get("latitude"), record.get("longitude"))
            except ValueError:
                raw_record_row.validation_warnings = raw_record_row.validation_warnings + [{"code": "invalid_location_dropped", "field": "latitude/longitude", "message": "optional location was present but invalid -- dropped, not defaulted to 0/0"}]

            calibration_metadata = record.get("calibration_metadata") if isinstance(record.get("calibration_metadata"), dict) else None
            uncertainty_metadata = record.get("uncertainty_metadata") if isinstance(record.get("uncertainty_metadata"), dict) else None

            observation = Observation(
                organization_id=organization_id,
                sensor_id=sensor.id,
                source_id=source_id,
                observed_at=outcome.normalized_observed_at,
                ingested_at=received_at,
                observation_type=str(record.get("measurement_type")),
                payload=_build_attributes(record),
                quality_metadata={"issues": [{"code": i.code, "message": i.message} for i in issues_for_record], "ruleset_version": quality_lib.QUALITY_RULESET_VERSION},
                provenance={
                    "raw_record_id": raw_record_row.id,
                    "connector_type": connector_result.connector_type,
                    "connector_version": connector_result.connector_version,
                    "schema_version": SENSOR_OBSERVATION_SCHEMA_VERSION,
                    "content_fingerprint": fingerprint,
                    "quality_ruleset_version": quality_lib.QUALITY_RULESET_VERSION,
                },
                processing_status="ingested",
                data_origin=data_origin,
                latitude=latitude,
                longitude=longitude,
                ingestion_job_id=job.id,
                measurement_value=outcome.normalized_value,
                unit=record.get("unit") or (sensor.measurement_units or {}).get(str(record.get("measurement_type"))),
                validation_status=outcome.validation_status,
                quality_flags=outcome.quality_flags,
                source_record_id=raw_record_row.id,
                schema_version=SENSOR_OBSERVATION_SCHEMA_VERSION,
                calibration_metadata=calibration_metadata,
                uncertainty_metadata=uncertainty_metadata,
            )
            db.add(observation)
            db.flush()

            raw_record_row.event_id = None
            ctx.record_accepted(outcome.normalized_observed_at, outcome.normalized_value)

            device_status = record.get("device_status")
            if device_status:
                sensor.device_reported_status = str(device_status)
                sensor.device_reported_status_at = received_at
            if sensor.lifecycle_status in ("registered", "offline"):
                sensor.lifecycle_status = "active"
            sensor.last_seen_at = outcome.normalized_observed_at if (sensor.last_seen_at is None or outcome.normalized_observed_at > ensure_utc(sensor.last_seen_at)) else sensor.last_seen_at
            sensor.last_ingestion_success_at = received_at
            db.add(sensor)

            seen_external_ids.add(external_id)
            seen_raw_record_ids[external_id] = raw_record_row.id
            accepted += 1
        except Exception as exc:  # one bad record must never abort the whole job
            rejected += 1
            errors.append({"index": index, "error": f"unexpected error: {exc}"})

    return accepted, rejected, skipped, duplicate, errors


def _finalize_job(db: Session, *, job: IngestionJob, accepted: int, rejected: int, skipped: int, duplicate: int, errors: list[dict]) -> IngestionJob:
    job.accepted_count = accepted
    job.rejected_count = rejected
    job.skipped_count = skipped
    job.duplicate_count = duplicate
    job.error_summary = errors[:50]
    job.status = "completed" if rejected == 0 else "completed_with_errors"
    job.completed_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _run(
    db: Session,
    *,
    organization_id: str,
    source_id: str,
    job_type: str,
    connector_result: ConnectorResult,
    data_origin: str,
    created_by_user_id: Optional[str],
    trigger_type: str,
    correlation_id: Optional[str],
    extra_provenance: Optional[dict] = None,
) -> IngestionJob:
    started_at = datetime.now(timezone.utc)
    job = IngestionJob(
        organization_id=organization_id, source_id=source_id, created_by_user_id=created_by_user_id,
        job_type=job_type, status="running", started_at=started_at, trigger_type=trigger_type, correlation_id=correlation_id,
        provenance=extra_provenance or {},
    )
    db.add(job)
    db.flush()

    if not connector_result.records and connector_result.errors:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_summary = [{"error": f"[{e.category.value}] {e.message}"} for e in connector_result.errors][:50]
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    accepted, rejected, skipped, duplicate, errors = _process_batch(
        db, job=job, organization_id=organization_id, source_id=source_id, connector_result=connector_result,
        data_origin=data_origin, seen_external_ids=set(), seen_raw_record_ids={}, sensor_contexts={}, sensor_cache={},
    )
    return _finalize_job(db, job=job, accepted=accepted, rejected=rejected, skipped=skipped, duplicate=duplicate, errors=errors)


def submit_file_batch(
    db: Session, *, organization_id: str, source_id: str, fmt: str, content: bytes, created_by_user_id: Optional[str],
    data_origin: str = "user_upload", correlation_id: Optional[str] = None,
) -> IngestionJob:
    if len(content) > settings.MAX_UPLOAD_BYTES:
        raise BatchTooLargeError(f"batch exceeds the {settings.MAX_UPLOAD_BYTES} byte upload limit")
    adapter_cls = get_file_adapter_class(fmt)
    if adapter_cls is None:
        raise UnsupportedBatchFormatError(f"unsupported batch format '{fmt}' -- only json/csv are accepted")
    connector = adapter_cls(content=content)
    result = connector.fetch(limit=settings.SENSOR_MAX_OBSERVATIONS_PER_BATCH)
    job_type = "sensor_json_batch" if fmt == "json" else "sensor_csv_batch"
    return _run(
        db, organization_id=organization_id, source_id=source_id, job_type=job_type, connector_result=result,
        data_origin=data_origin, created_by_user_id=created_by_user_id, trigger_type="manual", correlation_id=correlation_id,
    )


def submit_synthetic_batch(
    db: Session, *, organization_id: str, source_id: str, config: dict, created_by_user_id: Optional[str],
    trigger_type: str = "manual", correlation_id: Optional[str] = None,
) -> IngestionJob:
    adapter_cls = get_connector_adapter_class("sensor_synthetic")
    connector = adapter_cls(config)
    config_errors = connector.validate_config()
    if config_errors:
        started_at = datetime.now(timezone.utc)
        job = IngestionJob(
            organization_id=organization_id, source_id=source_id, created_by_user_id=created_by_user_id,
            job_type="sensor_synthetic", status="failed", started_at=started_at, completed_at=started_at,
            trigger_type=trigger_type, correlation_id=correlation_id, error_summary=[{"error": "; ".join(config_errors)}],
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    result = connector.fetch(limit=settings.SENSOR_MAX_OBSERVATIONS_PER_BATCH)
    return _run(
        db, organization_id=organization_id, source_id=source_id, job_type="sensor_synthetic", connector_result=result,
        data_origin="synthetic_demo", created_by_user_id=created_by_user_id, trigger_type=trigger_type, correlation_id=correlation_id,
        extra_provenance={"synthetic_config": config},
    )


def get_job(db: Session, organization_id: str, job_id: str) -> Optional[IngestionJob]:
    stmt = select(IngestionJob).where(IngestionJob.id == job_id, IngestionJob.organization_id == organization_id, IngestionJob.job_type.in_(SENSOR_INGESTION_JOB_TYPES))
    return db.execute(stmt).scalar_one_or_none()


def list_jobs_query(organization_id: str, *, source_id: Optional[str] = None):
    stmt = select(IngestionJob).where(IngestionJob.organization_id == organization_id, IngestionJob.job_type.in_(SENSOR_INGESTION_JOB_TYPES))
    if source_id:
        stmt = stmt.where(IngestionJob.source_id == source_id)
    return stmt.order_by(IngestionJob.started_at.desc())


def list_raw_records_for_job_query(organization_id: str, job_id: str, *, validation_status: Optional[str] = None):
    stmt = select(RawRecord).where(RawRecord.organization_id == organization_id, RawRecord.ingestion_job_id == job_id)
    if validation_status:
        stmt = stmt.where(RawRecord.validation_status == validation_status)
    return stmt.order_by(RawRecord.created_at.asc())


def retry_job(db: Session, organization_id: str, job: IngestionJob, *, created_by_user_id: Optional[str], correlation_id: Optional[str] = None) -> IngestionJob:
    if job.job_type not in SENSOR_RETRYABLE_JOB_TYPES:
        raise ValueError(f"job type '{job.job_type}' is not safely retryable -- a file-upload batch requires re-submitting the file")
    config = (job.provenance or {}).get("synthetic_config")
    if not config:
        raise ValueError("original synthetic configuration was not preserved on this job -- cannot retry")
    new_job = submit_synthetic_batch(
        db, organization_id=organization_id, source_id=job.source_id, config=config,
        created_by_user_id=created_by_user_id, trigger_type="retry", correlation_id=correlation_id,
    )
    new_job.retry_count = job.retry_count + 1
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job
