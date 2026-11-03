"""The ingestion engine. One shared pipeline
-- validate, normalize, deduplicate, preserve provenance, persist --
used by BOTH ingestion paths this platform supports:

  * `run_ingestion()`      -- a one-shot JSON/CSV file upload (Phase 1's
                              original entry point; exact behavior
                              preserved, including the intra-batch
                              duplicate fix and its regression tests).
  * `run_connector_source()` -- a connector-driven source (http_api,
                              synthetic_demo) being explicitly "run"
                              through the API.

Both call the shared `_process_batch()` so a record from an uploaded
file and a record fetched from an HTTP API go through identical
validation/normalization/dedup/provenance logic -- there is exactly
one place that decides what counts as a duplicate or an invalid
record, regardless of where the record came from.

Partial failure is always reported honestly (Rule 5 / Section 10): one
bad record never aborts the whole job, and nothing here ever claims a
record was accepted when it wasn't.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.connectors.registry import get_connector_class, get_file_connector_class
from app.connectors.types import ConnectorResult
from app.core.config import get_settings
from app.models.data_source import DataSource
from app.models.event import Event
from app.models.ingestion_job import IngestionJob
from app.models.raw_record import RawRecord
from app.services import normalization_service as norm
from app.services.validation_service import validate_record

settings = get_settings()

ALLOWED_EXTENSIONS = {"json", "csv"}

# Attribute keys that have their own dedicated Event column -- anything
# else in a record is preserved verbatim in Event.attributes, so a
# source-specific field is never silently discarded.
_RESERVED_ATTRIBUTE_KEYS = {"event_type", "title", "description", "observed_at", "latitude", "longitude", "severity", "external_id"}


class UnsupportedFileTypeError(ValueError):
    pass


class FileTooLargeError(ValueError):
    pass


class SourceDisabledError(ValueError):
    """Raised by run_connector_source() for a source that is registered
    but currently disabled -- disabling a source must actually stop new
    ingestion jobs, not just change a cosmetic label."""


class NoConnectorForSourceError(ValueError):
    """Raised when a source's source_type has no connector-driven fetch
    path -- i.e. it's a file-upload-only source being asked to "run"."""


def _validate_file(filename: str, content: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(f"Unsupported file type '.{ext}' -- only .json and .csv are accepted")
    if len(content) > settings.MAX_UPLOAD_BYTES:
        raise FileTooLargeError(f"File exceeds the {settings.MAX_UPLOAD_BYTES} byte upload limit")
    return ext


def _event_already_exists(db: Session, source_id: str, external_id: str) -> bool:
    stmt = select(Event.id).where(Event.source_id == source_id, Event.external_id == external_id)
    return db.execute(stmt).first() is not None


def _existing_raw_record_id(db: Session, source_id: str, external_id: str) -> Optional[str]:
    """Best-effort lookup of the earlier, non-duplicate RawRecord this
    external_id belongs to -- used only to explain a cross-batch
    duplicate ("preserve an explanation for why something
    was flagged duplicate"). Returning None is harmless; the duplicate
    is still correctly counted either way."""
    stmt = (
        select(RawRecord.id)
        .where(RawRecord.source_id == source_id, RawRecord.external_record_id == external_id, RawRecord.is_duplicate.is_(False))
        .order_by(RawRecord.created_at.asc())
    )
    row = db.execute(stmt).first()
    return row[0] if row else None


def _build_attributes(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in _RESERVED_ATTRIBUTE_KEYS}


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
) -> tuple[int, int, int, int, list[dict]]:
    """Validates, normalizes, deduplicates and persists one connector
    batch. Returns (accepted, rejected, skipped, duplicate, errors).

    `seen_external_ids` / `seen_raw_record_ids` are passed in (rather
    than created here) so a caller processing multiple pages of the
    same job shares one in-batch dedup set across pages."""
    accepted = rejected = skipped = duplicate = 0
    errors: list[dict] = []
    received_at = datetime.now(timezone.utc)

    # A connector-level error (malformed row, non-object list entry)
    # already failed before a record existed to validate -- reported
    # as rejected, same as a per-record validation failure.
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

            outcome = validate_record(record)
            fingerprint = norm.content_fingerprint(record)
            external_id = raw.external_id or str(record.get("external_id") or "") or fingerprint

            is_duplicate = False
            duplicate_reason: Optional[str] = None
            duplicate_of_id: Optional[str] = None
            if external_id in seen_external_ids:
                is_duplicate = True
                duplicate_reason = "external_id repeated earlier in this same ingestion batch"
                duplicate_of_id = seen_raw_record_ids.get(external_id)
            elif _event_already_exists(db, source_id, external_id):
                is_duplicate = True
                duplicate_reason = "external_id already exists for this source from a previous ingestion"
                duplicate_of_id = _existing_raw_record_id(db, source_id, external_id)

            raw_observed = record.get("observed_at")
            raw_record_row = RawRecord(
                organization_id=organization_id,
                source_id=source_id,
                ingestion_job_id=job.id,
                external_record_id=external_id or None,
                connector_type=connector_result.connector_type,
                connector_version=connector_result.connector_version,
                normalization_version=norm.NORMALIZATION_VERSION,
                schema_version=norm.SCHEMA_VERSION,
                content_fingerprint=fingerprint,
                payload=record,
                source_observed_at_raw=raw.source_observed_at_raw or (str(raw_observed) if raw_observed is not None else None),
                received_at=received_at,
                validation_status=outcome.status,
                validation_errors=[{"code": e.code, "field": e.field, "message": e.message} for e in outcome.errors],
                validation_warnings=[{"code": w.code, "field": w.field, "message": w.message} for w in outcome.warnings],
                is_duplicate=is_duplicate,
                duplicate_of_raw_record_id=duplicate_of_id,
                duplicate_reason=duplicate_reason,
            )
            db.add(raw_record_row)
            db.flush()  # need raw_record_row.id for linking, and to catch constraint errors per-record

            if is_duplicate:
                duplicate += 1
                continue

            if not outcome.is_valid:
                rejected += 1
                message = "; ".join(e.message for e in outcome.errors)
                errors.append({"index": index, "error": message})
                continue

            event = Event(
                organization_id=organization_id,
                source_id=source_id,
                external_id=external_id or None,
                event_type=str(record["event_type"]),
                title=str(record["title"]),
                description=record.get("description"),
                observed_at=outcome.normalized_observed_at,
                ingested_at=received_at,
                latitude=outcome.normalized_latitude,
                longitude=outcome.normalized_longitude,
                source_severity=record.get("severity"),
                priority=outcome.normalized_priority,
                attributes=_build_attributes(record),
                data_origin=data_origin,
                ingestion_job_id=job.id,
                processing_status="normalized",
                provenance={
                    "raw_record_id": raw_record_row.id,
                    "connector_type": connector_result.connector_type,
                    "connector_version": connector_result.connector_version,
                    "normalization_version": norm.NORMALIZATION_VERSION,
                    "schema_version": norm.SCHEMA_VERSION,
                    "content_fingerprint": fingerprint,
                    "timestamp_policy": outcome.timestamp_policy,
                    "validation_warning_codes": [w.code for w in outcome.warnings],
                },
            )
            # The in-batch set and the pre-insert SELECT above catch
            # almost every duplicate, but neither closes the window
            # between "checked, nothing exists" and "committed" that a
            # genuinely concurrent second request could race through.
            # The DB's own uq_events_source_external_id constraint is
            # the real backstop ("DB-level constraints to
            # prevent race-condition duplicates") -- a SAVEPOINT keeps
            # that constraint's failure from poisoning the rest of this
            # job's transaction, so it can be turned into an ordinary
            # counted duplicate instead of an aborted job.
            try:
                with db.begin_nested():
                    db.add(event)
                    db.flush()
            except IntegrityError:
                raw_record_row.is_duplicate = True
                raw_record_row.duplicate_reason = "external_id uniqueness constraint violated at insert time -- a concurrent request won the race"
                db.add(raw_record_row)
                db.flush()
                duplicate += 1
                continue

            raw_record_row.event_id = event.id

            seen_external_ids.add(external_id)
            seen_raw_record_ids[external_id] = raw_record_row.id
            accepted += 1
        except Exception as exc:  # one bad record must never abort the whole job
            rejected += 1
            errors.append({"index": index, "error": f"unexpected error: {exc}"})

    return accepted, rejected, skipped, duplicate, errors


def run_ingestion(
    db: Session,
    *,
    organization_id: str,
    source_id: str,
    filename: str,
    content: bytes,
    created_by_user_id: Optional[str],
    data_origin: str,
    correlation_id: Optional[str] = None,
) -> IngestionJob:
    started_at = datetime.now(timezone.utc)
    job = IngestionJob(
        organization_id=organization_id,
        source_id=source_id,
        created_by_user_id=created_by_user_id,
        job_type="json_upload",
        status="running",
        started_at=started_at,
        trigger_type="manual",
        correlation_id=correlation_id,
    )
    db.add(job)
    db.flush()

    try:
        ext = _validate_file(filename, content)
    except (UnsupportedFileTypeError, FileTooLargeError) as exc:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_summary = [{"error": str(exc)}]
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    job.job_type = f"{ext}_upload"
    connector_cls = get_file_connector_class(ext)
    connector = connector_cls(content=content)
    result = connector.fetch()

    # A fully-unparseable upload (invalid JSON syntax, wrong top-level
    # shape, undecodable CSV bytes) produces zero records and at least
    # one connector error -- that is a job-level failure, not a
    # per-record one, matching Phase 1's original "malformed upload ->
    # failed job" contract.
    if not result.records and result.errors:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_summary = [{"error": f"[{e.category.value}] {e.message}"} for e in result.errors][:50]
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    accepted, rejected, skipped, duplicate, errors = _process_batch(
        db,
        job=job,
        organization_id=organization_id,
        source_id=source_id,
        connector_result=result,
        data_origin=data_origin,
        seen_external_ids=set(),
        seen_raw_record_ids={},
    )

    _finalize_job(db, job=job, started_at=started_at, accepted=accepted, rejected=rejected, skipped=skipped, duplicate=duplicate, errors=errors)
    return job


def run_connector_source(
    db: Session,
    *,
    organization_id: str,
    source: DataSource,
    created_by_user_id: Optional[str],
    trigger_type: str = "manual",
    correlation_id: Optional[str] = None,
    limit: int = 500,
) -> IngestionJob:
    """Explicitly "runs" a connector-driven source (http_api,
    synthetic_demo) -- fetches one batch, processes it through the same
    engine run_ingestion() uses, and advances the source's checkpoint
    cursor only if that batch actually committed."""
    connector_cls = get_connector_class(source.source_type)
    if connector_cls is None:
        raise NoConnectorForSourceError(f"source_type '{source.source_type}' has no connector-driven fetch path -- it only accepts file uploads")
    if not source.enabled:
        raise SourceDisabledError(f"source '{source.name}' is disabled and cannot be run")

    started_at = datetime.now(timezone.utc)
    job = IngestionJob(
        organization_id=organization_id,
        source_id=source.id,
        created_by_user_id=created_by_user_id,
        job_type=source.source_type,
        status="running",
        started_at=started_at,
        trigger_type=trigger_type,
        correlation_id=correlation_id,
    )
    db.add(job)
    db.flush()

    connector = connector_cls(source.config_metadata or {})
    try:
        config_errors = connector.validate_config()
        if config_errors:
            job.status = "failed"
            job.completed_at = datetime.now(timezone.utc)
            job.error_summary = [{"error": "; ".join(config_errors)}]
            source.last_error_category = "configuration"
            db.add(job)
            db.add(source)
            db.commit()
            db.refresh(job)
            return job

        result = connector.fetch(cursor=source.last_checkpoint_cursor, limit=limit)
    finally:
        connector.close()

    if not result.records and result.errors:
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_summary = [{"error": f"[{e.category.value}] {e.message}"} for e in result.errors][:50]
        source.last_ingestion_attempt_at = started_at
        source.last_error_category = result.errors[0].category.value
        db.add(job)
        db.add(source)
        db.commit()
        db.refresh(job)
        return job

    accepted, rejected, skipped, duplicate, errors = _process_batch(
        db,
        job=job,
        organization_id=organization_id,
        source_id=source.id,
        connector_result=result,
        data_origin="external_source" if source.source_type == "http_api" else "synthetic_demo",
        seen_external_ids=set(),
        seen_raw_record_ids={},
    )

    _finalize_job(db, job=job, started_at=started_at, accepted=accepted, rejected=rejected, skipped=skipped, duplicate=duplicate, errors=errors, source=source)

    # Checkpoint only after this batch's records are part of the same
    # commit as the job itself -- if the commit fails, the checkpoint
    # never advances, so a retry safely re-fetches from the old cursor.
    if result.cursor:
        source.last_checkpoint_cursor = result.cursor
        source.last_checkpoint_at = datetime.now(timezone.utc)
        db.add(source)
        db.commit()

    return job


def _finalize_job(
    db: Session,
    *,
    job: IngestionJob,
    started_at: datetime,
    accepted: int,
    rejected: int,
    skipped: int,
    duplicate: int,
    errors: list[dict],
    source: Optional[DataSource] = None,
) -> None:
    job.accepted_count = accepted
    job.rejected_count = rejected
    job.skipped_count = skipped
    job.duplicate_count = duplicate
    job.error_summary = errors[:50]  # bounded -- never an unbounded error dump
    job.status = "completed" if rejected == 0 else "completed_with_errors"
    job.completed_at = datetime.now(timezone.utc)

    if source is None:
        source = db.get(DataSource, job.source_id)
    if source is not None:
        source.last_ingestion_attempt_at = started_at
        if accepted > 0:
            source.last_ingestion_success_at = datetime.now(timezone.utc)
        if rejected == 0:
            source.last_error_category = None
        db.add(source)

    db.add(job)
    db.commit()
    db.refresh(job)


def get_job(db: Session, organization_id: str, job_id: str) -> Optional[IngestionJob]:
    stmt = select(IngestionJob).where(IngestionJob.id == job_id, IngestionJob.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_jobs_query(organization_id: str, *, source_id: Optional[str] = None):
    stmt = select(IngestionJob).where(IngestionJob.organization_id == organization_id)
    if source_id:
        stmt = stmt.where(IngestionJob.source_id == source_id)
    return stmt.order_by(IngestionJob.started_at.desc())


def get_raw_record(db: Session, organization_id: str, raw_record_id: str) -> Optional[RawRecord]:
    stmt = select(RawRecord).where(RawRecord.id == raw_record_id, RawRecord.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_raw_records_for_job_query(organization_id: str, job_id: str):
    return (
        select(RawRecord)
        .where(RawRecord.organization_id == organization_id, RawRecord.ingestion_job_id == job_id)
        .order_by(RawRecord.created_at.asc())
    )


# Connector-driven job types that CAN be safely retried -- the
# connector can simply be asked to fetch again. A file-upload job
# (json_upload/csv_upload) is never auto-retryable because this
# platform does not persist the original uploaded bytes indefinitely;
# re-running one requires the analyst to re-upload the file (Section
# 10: never claim an unsafe retry is safe).
RETRYABLE_JOB_TYPES = {"http_api", "synthetic_demo", "synthetic_generator"}


def retry_job(db: Session, organization_id: str, job: IngestionJob, *, created_by_user_id: Optional[str], correlation_id: Optional[str] = None) -> IngestionJob:
    if job.job_type not in RETRYABLE_JOB_TYPES:
        raise ValueError(f"job type '{job.job_type}' is not safely retryable -- file-upload jobs require re-uploading the file")
    source = db.get(DataSource, job.source_id)
    if source is None:
        raise ValueError("the source for this job no longer exists")
    new_job = run_connector_source(
        db,
        organization_id=organization_id,
        source=source,
        created_by_user_id=created_by_user_id,
        trigger_type="retry",
        correlation_id=correlation_id,
    )
    new_job.retry_count = job.retry_count + 1
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job
