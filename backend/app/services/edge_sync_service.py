"""The durable, idempotent central sync pipeline (Phase 8, Sections
5-9). This module is the only place that ever writes `SyncRecord.sync_status`
-- every transition goes through `_transition()`, which enforces
`SYNC_RECORD_TRANSITIONS` ("prevent invalid state changes").
See docs/architecture/SYNC_PROTOCOL.md for the full narrative and
docs/operations/CONFLICT_RESOLUTION.md for the two-tier conflict policy
implemented in `_accept_mutable`/`_accept_immutable` below.

Durability model actually implemented here (documented honestly, see
docs/architecture/EDGE_ARCHITECTURE.md Section 7): a logical record is
durably accepted the moment its SyncRecord row commits with
`sync_status="synced"`. There is no further downstream system in this
phase -- the SyncRecord table itself IS the durable central store, not
a staging area for one. Promoting an accepted record into a canonical
Event/Observation/Evidence row is an explicit, deferred follow-up (see
the module docstring on app/models/sync_record.py), not a silent gap.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.device import Device
from app.models.device_health_report import DeviceHealthReport
from app.models.sync_conflict import SyncConflict
from app.models.sync_record import (
    MUTABLE_SYNC_RECORD_TYPES,
    SYNC_RECORD_TRANSITIONS,
    SYNC_RECORD_TYPES,
    SyncRecord,
)
from app.schemas.edge_sync import (
    EDGE_SYNC_PROTOCOL_VERSION,
    SUPPORTED_EDGE_SYNC_PROTOCOL_VERSIONS,
    HealthReportRequest,
    SyncBatchRequest,
    SyncBatchResponse,
    SyncRecordAckResponse,
    SyncRecordEnvelope,
)
from app.services import audit_service, device_service
from app.services.timeutil import ensure_utc


class UnsupportedProtocolVersionError(ValueError):
    pass


class InvalidSyncTransitionError(ValueError):
    pass


class BatchTooLargeError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def compute_backoff_seconds(retry_count: int, settings: Settings) -> float:
    """Exponential backoff, bounded, with symmetric jitter.
    `random.uniform` is called through the module-level `random` import
    (not `from random import uniform`) specifically so tests can
    monkeypatch `edge_sync_service.random.uniform` for deterministic
    assertions."""
    delay = min(settings.EDGE_SYNC_RETRY_BASE_DELAY_SECONDS * (2 ** max(retry_count, 0)), settings.EDGE_SYNC_RETRY_MAX_DELAY_SECONDS)
    jitter = delay * settings.EDGE_SYNC_RETRY_JITTER_FRACTION
    jittered = delay + random.uniform(-jitter, jitter)
    return round(max(0.0, jittered), 3)


def _compute_payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _payload_size_bytes(payload: dict) -> int:
    return len(json.dumps(payload, default=str).encode("utf-8"))


def _transition(record: SyncRecord, new_status: str) -> None:
    allowed = SYNC_RECORD_TRANSITIONS.get(record.sync_status, ())
    if new_status not in allowed:
        raise InvalidSyncTransitionError(f"illegal sync_record transition '{record.sync_status}' -> '{new_status}'")
    record.sync_status = new_status


def _commit_transition(db: Session, record: SyncRecord, new_status: str, **field_updates) -> SyncRecord:
    for key, value in field_updates.items():
        setattr(record, key, value)
    _transition(record, new_status)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _ack(message_id: str, record: SyncRecord, *, conflict_id: Optional[str] = None, retry_after_seconds: Optional[float] = None) -> SyncRecordAckResponse:
    return SyncRecordAckResponse(
        message_id=message_id,
        idempotency_key=record.idempotency_key,
        client_record_id=record.client_record_id,
        sync_record_id=record.id,
        sync_status=record.sync_status,
        error_category=record.last_error_category,
        error_message=record.last_error_message,
        conflict_id=conflict_id,
        retry_after_seconds=retry_after_seconds,
    )


def _get_or_create_record(db: Session, device: Device, batch_id: Optional[str], envelope: SyncRecordEnvelope) -> tuple[SyncRecord, bool]:
    """THE idempotency guarantee, realized as a lookup
    before insert, backed by `uq_sync_records_device_idempotency`.
    Returns (record, is_new)."""
    existing = db.execute(
        select(SyncRecord).where(
            SyncRecord.organization_id == device.organization_id,
            SyncRecord.device_id == device.id,
            SyncRecord.idempotency_key == envelope.idempotency_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    effective_hash = envelope.payload_hash or _compute_payload_hash(envelope.payload)
    record = SyncRecord(
        organization_id=device.organization_id,
        device_id=device.id,
        message_id=envelope.message_id,
        idempotency_key=envelope.idempotency_key,
        batch_id=batch_id,
        protocol_version=EDGE_SYNC_PROTOCOL_VERSION,
        schema_version=envelope.schema_version,
        record_type=envelope.record_type,
        client_record_id=envelope.client_record_id,
        base_revision=envelope.base_revision,
        payload=envelope.payload,
        payload_hash=effective_hash,
        source_created_at=envelope.source_created_at,
        queued_at=envelope.queued_at,
        sync_status="queued",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, True


def _get_current_accepted(db: Session, organization_id: str, record_type: str, client_record_id: str) -> Optional[SyncRecord]:
    """The CENTRAL authoritative state for a logical record -- scoped
    to the organization and record_type/client_record_id, deliberately
    NOT to one device, since the central record a device is comparing
    against may have been written by any device or by
    an analyst directly."""
    stmt = (
        select(SyncRecord)
        .where(
            SyncRecord.organization_id == organization_id,
            SyncRecord.record_type == record_type,
            SyncRecord.client_record_id == client_record_id,
            SyncRecord.sync_status == "synced",
        )
        .order_by(SyncRecord.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def _accept_mutable(db: Session, record: SyncRecord) -> Optional[str]:
    """Section 8.2/8.3 -- optimistic-concurrency revisioning for the one
    mutable record_type. NEVER unconditional last-write-wins: a
    mismatched base_revision always creates a real, human-resolvable
    SyncConflict row with full local/central snapshots, never a silent
    overwrite and never a silent drop. Returns the new SyncConflict's id
    if one was created, else None."""
    current = _get_current_accepted(db, record.organization_id, record.record_type, record.client_record_id)
    current_revision = current.revision if (current is not None and current.revision is not None) else 0

    if record.base_revision != current_revision:
        conflict = SyncConflict(
            organization_id=record.organization_id,
            device_id=record.device_id,
            sync_record_id=record.id,
            record_type=record.record_type,
            client_record_id=record.client_record_id,
            conflict_reason="revision_mismatch",
            local_version={
                "payload": record.payload,
                "base_revision": record.base_revision,
                "sync_record_id": record.id,
                "device_id": record.device_id,
                "source_created_at": record.source_created_at.isoformat(),
            },
            central_version=(
                {"payload": current.payload, "revision": current_revision, "sync_record_id": current.id}
                if current is not None
                else {"payload": None, "revision": 0, "sync_record_id": None}
            ),
            resolution_status="unresolved",
        )
        db.add(conflict)
        record.last_error_category = "conflict"
        record.last_error_message = f"base_revision {record.base_revision} does not match current central revision {current_revision}"
        record.processed_at = _now()
        record.acknowledged_at = _now()
        _transition(record, "conflict")
        db.add(record)
        db.commit()
        db.refresh(record)
        db.refresh(conflict)
        audit_service.record(
            db, action="edge_sync.conflict_detected", actor_user_id=None, organization_id=record.organization_id,
            target_type="sync_conflict", target_id=conflict.id, outcome="success",
            context_metadata={"device_id": record.device_id, "client_record_id": record.client_record_id, "sync_record_id": record.id},
        )
        db.commit()
        return conflict.id

    record.revision = current_revision + 1
    record.supersedes_sync_record_id = current.id if current is not None else None
    record.processed_at = _now()
    record.acknowledged_at = _now()
    _transition(record, "synced")
    db.add(record)
    db.commit()
    db.refresh(record)
    return None


def _accept_immutable(db: Session, record: SyncRecord) -> None:
    """Section 8.1 -- append-only/immutable record types. A resubmission
    of the SAME client_record_id with the SAME payload_hash is a benign
    duplicate (idempotent accept, see docs/operations/CONFLICT_RESOLUTION.md).
    A resubmission with a DIFFERENT payload_hash under the same
    client_record_id is quarantined for human review -- NEVER merged,
    NEVER silently overwritten."""
    existing_accepted = _get_current_accepted(db, record.organization_id, record.record_type, record.client_record_id)
    if existing_accepted is not None and existing_accepted.id != record.id and existing_accepted.payload_hash != record.payload_hash:
        record.last_error_category = "integrity_failure"
        record.last_error_message = f"client_record_id '{record.client_record_id}' was already accepted with a different payload_hash"
        record.processed_at = _now()
        record.acknowledged_at = _now()
        _transition(record, "quarantined")
        db.add(record)
        db.commit()
        db.refresh(record)
        audit_service.record(
            db, action="edge_sync.quarantined", actor_user_id=None, organization_id=record.organization_id,
            target_type="sync_record", target_id=record.id, outcome="failure",
            context_metadata={"error_category": "integrity_failure", "client_record_id": record.client_record_id},
        )
        db.commit()
        return

    record.processed_at = _now()
    record.acknowledged_at = _now()
    _transition(record, "synced")
    db.add(record)
    db.commit()
    db.refresh(record)


def _accept_record(db: Session, record: SyncRecord) -> Optional[str]:
    if record.record_type in MUTABLE_SYNC_RECORD_TYPES:
        return _accept_mutable(db, record)
    _accept_immutable(db, record)
    return None


def _run_acceptance(db: Session, record: SyncRecord, settings: Settings) -> tuple[Optional[str], Optional[float]]:
    """Runs `_accept_record` with `record` already committed in
    `syncing`. A genuine SQLAlchemyError raised while accepting (e.g. a
    SQLite "database is locked" transient error under concurrent
    writers) is caught here and classified `server_error`/retryable,
    bounded by EDGE_SYNC_MAX_RETRY_COUNT -- this is the one server-side
    failure mode this synchronous, single-process implementation can
    genuinely hit (there is no further downstream dependency to fail
    against in this phase, see module docstring)."""
    try:
        conflict_id = _accept_record(db, record)
        return conflict_id, None
    except SQLAlchemyError:
        db.rollback()
        db.refresh(record)
        record.retry_count += 1
        if record.retry_count >= settings.EDGE_SYNC_MAX_RETRY_COUNT:
            _commit_transition(
                db, record, "permanent_failure", last_error_category="server_error",
                last_error_message="maximum retry count exceeded after a central processing error", processed_at=_now(),
            )
            return None, None
        delay = compute_backoff_seconds(record.retry_count, settings)
        _commit_transition(
            db, record, "retryable_failure", last_error_category="server_error",
            last_error_message="a transient central processing error occurred", next_retry_at=_now() + timedelta(seconds=delay),
        )
        return None, delay


def process_record(db: Session, device: Device, batch_id: Optional[str], envelope: SyncRecordEnvelope) -> SyncRecordAckResponse:
    settings = get_settings()
    record, is_new = _get_or_create_record(db, device, batch_id, envelope)

    if not is_new and record.sync_status not in ("queued", "retryable_failure"):
        # Idempotent no-op: synced/permanent_failure/conflict/quarantined/
        # cancelled are all terminal (or awaiting explicit human
        # resolution) -- a resubmission just reflects current state,
        # never reprocesses.
        return _ack(envelope.message_id, record)

    if not is_new and record.retry_count >= settings.EDGE_SYNC_MAX_RETRY_COUNT:
        _commit_transition(db, record, "permanent_failure", last_error_message="maximum retry count exceeded", processed_at=_now())
        return _ack(envelope.message_id, record)

    if is_new:
        if record.record_type not in SYNC_RECORD_TYPES:
            _commit_transition(db, record, "syncing")
            _commit_transition(
                db, record, "quarantined", last_error_category="validation_error",
                last_error_message=f"unknown record_type '{record.record_type}'", processed_at=_now(), acknowledged_at=_now(),
            )
            return _ack(envelope.message_id, record)

        payload_bytes = _payload_size_bytes(record.payload)
        if payload_bytes > settings.EDGE_SYNC_MAX_PAYLOAD_BYTES:
            _commit_transition(db, record, "syncing")
            _commit_transition(
                db, record, "quarantined", last_error_category="validation_error",
                last_error_message=f"payload of {payload_bytes} bytes exceeds the {settings.EDGE_SYNC_MAX_PAYLOAD_BYTES}-byte limit",
                processed_at=_now(), acknowledged_at=_now(),
            )
            return _ack(envelope.message_id, record)

        if record.record_type in MUTABLE_SYNC_RECORD_TYPES and record.base_revision is None:
            _commit_transition(db, record, "syncing")
            _commit_transition(
                db, record, "quarantined", last_error_category="validation_error",
                last_error_message="mutable record_type requires base_revision", processed_at=_now(), acknowledged_at=_now(),
            )
            return _ack(envelope.message_id, record)

    _commit_transition(db, record, "syncing")
    conflict_id, retry_after = _run_acceptance(db, record, settings)
    return _ack(envelope.message_id, record, conflict_id=conflict_id, retry_after_seconds=retry_after)


def _derive_device_sync_status(db: Session, device: Device) -> str:
    """Updates the convenience `Device.sync_status` column -- never
    trusted as authoritative (see device_service's live-computed
    pending/conflict counts), just a reasonable last-known value for a
    direct DB read or export."""
    if device_service.compute_unresolved_conflict_count(db, device.organization_id, device.id) > 0:
        return "conflict"
    if device_service.compute_pending_sync_count(db, device.organization_id, device.id) > 0:
        return "pending"
    return "synced"


def ingest_batch(db: Session, device: Device, batch: SyncBatchRequest) -> SyncBatchResponse:
    settings = get_settings()
    if batch.protocol_version not in SUPPORTED_EDGE_SYNC_PROTOCOL_VERSIONS:
        raise UnsupportedProtocolVersionError(
            f"protocol_version '{batch.protocol_version}' is not supported by this server "
            f"(supported: {', '.join(SUPPORTED_EDGE_SYNC_PROTOCOL_VERSIONS)})"
        )
    if len(batch.records) > settings.EDGE_SYNC_MAX_BATCH_SIZE:
        raise BatchTooLargeError(f"batch of {len(batch.records)} records exceeds the configured maximum of {settings.EDGE_SYNC_MAX_BATCH_SIZE}")

    results = [process_record(db, device, batch.batch_id, envelope) for envelope in batch.records]

    device.last_sync_at = _now()
    device.connectivity_state = "online"
    device.sync_status = _derive_device_sync_status(db, device)
    db.add(device)
    db.commit()

    accepted = sum(1 for r in results if r.sync_status == "synced")
    conflicted = sum(1 for r in results if r.sync_status == "conflict")
    quarantined = sum(1 for r in results if r.sync_status == "quarantined")
    rejected = len(results) - accepted - conflicted - quarantined

    return SyncBatchResponse(
        protocol_version=EDGE_SYNC_PROTOCOL_VERSION, batch_id=batch.batch_id,
        accepted_count=accepted, conflict_count=conflicted, quarantined_count=quarantined,
        rejected_count=rejected, results=results,
    )


def process_health_report(db: Session, device: Device, report: HealthReportRequest) -> DeviceHealthReport:
    if report.protocol_version not in SUPPORTED_EDGE_SYNC_PROTOCOL_VERSIONS:
        raise UnsupportedProtocolVersionError(
            f"protocol_version '{report.protocol_version}' is not supported by this server "
            f"(supported: {', '.join(SUPPORTED_EDGE_SYNC_PROTOCOL_VERSIONS)})"
        )
    entry = DeviceHealthReport(
        organization_id=device.organization_id, device_id=device.id, reported_at=report.reported_at,
        connectivity_state=report.connectivity_state, resource_metrics=report.resource_metrics,
        queue_depth=report.queue_depth, pending_sync_count=report.pending_sync_count,
        model_status=report.model_status, software_version=report.software_version,
        runtime_capabilities=report.runtime_capabilities,
    )
    db.add(entry)
    device.last_health_report_at = _now()
    device.last_seen_at = _now()
    device.connectivity_state = report.connectivity_state
    if report.software_version:
        device.software_version = report.software_version
    device.local_storage_status = {"queue_depth": report.queue_depth, "pending_sync_count": report.pending_sync_count}
    # a convenience mirror only -- see
    # Device.last_resource_metrics's docstring. device_health_reports
    # remains the authoritative history.
    if report.resource_metrics is not None:
        device.last_resource_metrics = report.resource_metrics
    db.add(device)
    db.commit()
    db.refresh(entry)

    # Phase 9, Sections 7/9: capability discovery and infrastructure
    # alerting are both derived from the same health-report data this
    # endpoint already accepts (Part 3's "reuse" instruction) -- never a
    # second, parallel ingestion path.
    from app.services import fleet_alert_service, fleet_capability_service

    fleet_capability_service.sync_from_health_report(db, device, entry)
    fleet_alert_service.evaluate_alerts_for_device(db, device)
    return entry


def recover_stale_syncing_records(db: Session, *, organization_id: Optional[str] = None) -> int:
    """Crash-recovery sweep ("nothing stuck permanently in an
    in-progress state"). A record left in `syncing` with no update for
    longer than EDGE_SYNC_SYNCING_STALE_AFTER_SECONDS is treated as an
    orphaned attempt (the process handling it died mid-write) and reset
    to retryable_failure/permanent_failure exactly as if its acceptance
    had raised. Safe to call repeatedly / from multiple workers -- each
    row is only ever touched once per sweep since its `updated_at`
    advances the moment it's recovered."""
    settings = get_settings()
    cutoff = _now() - timedelta(seconds=settings.EDGE_SYNC_SYNCING_STALE_AFTER_SECONDS)
    stmt = select(SyncRecord).where(SyncRecord.sync_status == "syncing")
    if organization_id:
        stmt = stmt.where(SyncRecord.organization_id == organization_id)
    candidates = db.execute(stmt).scalars().all()
    recovered = 0
    for record in candidates:
        updated = ensure_utc(record.updated_at)
        if updated is None or updated >= cutoff:
            continue
        record.retry_count += 1
        if record.retry_count >= settings.EDGE_SYNC_MAX_RETRY_COUNT:
            _commit_transition(
                db, record, "permanent_failure", last_error_category="server_error",
                last_error_message="recovered from a stale in-progress state after exceeding max retries", processed_at=_now(),
            )
        else:
            delay = compute_backoff_seconds(record.retry_count, settings)
            _commit_transition(
                db, record, "retryable_failure", last_error_category="server_error",
                last_error_message="recovered from a stale in-progress state (the process handling it likely crashed mid-write)",
                next_retry_at=_now() + timedelta(seconds=delay),
            )
        recovered += 1
    return recovered


def cancel_sync_record(db: Session, record: SyncRecord, *, actor_user_id: str, reason: Optional[str] = None) -> SyncRecord:
    if record.sync_status not in ("queued", "retryable_failure"):
        raise InvalidSyncTransitionError(f"cannot cancel a sync record in status '{record.sync_status}'")
    _commit_transition(db, record, "cancelled", last_error_message=reason, processed_at=_now())
    audit_service.record(
        db, action="edge_sync.cancel", actor_user_id=actor_user_id, organization_id=record.organization_id,
        target_type="sync_record", target_id=record.id, context_metadata={"reason": reason},
    )
    db.commit()
    return record


def force_retry_sync_record(db: Session, record: SyncRecord, *, actor_user_id: str) -> SyncRecord:
    """Section 15 (EDGE_SYNC_MANAGE): an operator forcing another attempt
    at a retryable_failure OR permanent_failure record -- never fakes
    success, it genuinely re-runs `_accept_record` against the stored
    payload. Forcing a retry on a permanent_failure record explicitly
    resets its retry_count, since an operator override is a deliberate
    human decision, not another automatic attempt."""
    if record.sync_status not in ("retryable_failure", "permanent_failure"):
        raise InvalidSyncTransitionError(f"cannot force-retry a sync record in status '{record.sync_status}'")
    settings = get_settings()
    if record.sync_status == "permanent_failure":
        # An operator override is a deliberate human decision, not
        # another automatic attempt -- the retry counter resets so this
        # fresh attempt gets the full automatic-retry budget again.
        record.retry_count = 0
    _commit_transition(db, record, "syncing")
    conflict_id, retry_after = _run_acceptance(db, record, settings)
    audit_service.record(
        db, action="edge_sync.force_retry", actor_user_id=actor_user_id, organization_id=record.organization_id,
        target_type="sync_record", target_id=record.id, context_metadata={"resulting_status": record.sync_status, "conflict_id": conflict_id},
    )
    db.commit()
    db.refresh(record)
    return record


def get_sync_record(db: Session, organization_id: str, sync_record_id: str) -> Optional[SyncRecord]:
    stmt = select(SyncRecord).where(SyncRecord.id == sync_record_id, SyncRecord.organization_id == organization_id)
    return db.execute(stmt).scalar_one_or_none()


def list_sync_records_query(
    organization_id: str, *, device_id: Optional[str] = None, sync_status: Optional[str] = None, record_type: Optional[str] = None,
):
    stmt = select(SyncRecord).where(SyncRecord.organization_id == organization_id)
    if device_id:
        stmt = stmt.where(SyncRecord.device_id == device_id)
    if sync_status:
        stmt = stmt.where(SyncRecord.sync_status == sync_status)
    if record_type:
        stmt = stmt.where(SyncRecord.record_type == record_type)
    return stmt.order_by(SyncRecord.created_at.desc())


def get_queue_summary(db: Session, organization_id: str) -> dict:
    """Section 15's observability numbers -- every field here is a real
    query result over SyncRecord/SyncConflict, computed at request time,
    never a cached or fabricated figure."""
    total_records = db.scalar(select(func.count()).select_from(SyncRecord).where(SyncRecord.organization_id == organization_id)) or 0

    by_status_rows = db.execute(
        select(SyncRecord.sync_status, func.count())
        .where(SyncRecord.organization_id == organization_id)
        .group_by(SyncRecord.sync_status)
    ).all()
    by_status = [{"sync_status": status, "count": count} for status, count in by_status_rows]

    oldest_pending = db.scalar(
        select(func.min(SyncRecord.queued_at)).where(
            SyncRecord.organization_id == organization_id,
            SyncRecord.sync_status.in_(("queued", "syncing", "retryable_failure")),
        )
    )
    oldest_aware = ensure_utc(oldest_pending)
    oldest_pending_age_seconds = (_now() - oldest_aware).total_seconds() if oldest_aware is not None else None

    unresolved_conflict_count = db.scalar(
        select(func.count()).select_from(SyncConflict).where(SyncConflict.organization_id == organization_id, SyncConflict.resolution_status == "unresolved")
    ) or 0
    quarantined_count = db.scalar(
        select(func.count()).select_from(SyncRecord).where(SyncRecord.organization_id == organization_id, SyncRecord.sync_status == "quarantined")
    ) or 0
    devices_with_pending_records = db.scalar(
        select(func.count(func.distinct(SyncRecord.device_id))).where(
            SyncRecord.organization_id == organization_id,
            SyncRecord.sync_status.in_(("queued", "syncing", "retryable_failure")),
        )
    ) or 0

    return {
        "total_records": total_records,
        "by_status": by_status,
        "oldest_pending_age_seconds": oldest_pending_age_seconds,
        "unresolved_conflict_count": unresolved_conflict_count,
        "quarantined_count": quarantined_count,
        "devices_with_pending_records": devices_with_pending_records,
    }
