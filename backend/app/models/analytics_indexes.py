"""Composite indexes that serve windowed analytics queries.

Every analytics query filters by organization and a time window; single-column
indexes on organization_id and the time column cannot serve both. Declared here
(rather than editing each model) so the migration and the ORM stay in
step; creating them is non-destructive.
"""
from __future__ import annotations

from sqlalchemy import Index

from app.models.event import Event
from app.models.ingestion_job import IngestionJob
from app.models.investigation import Investigation
from app.models.observation import Observation
from app.models.raw_record import RawRecord

ANALYTICS_INDEXES = [
    Index("ix_events_org_observed_at", Event.organization_id, Event.observed_at),
    Index("ix_events_org_ingested_at", Event.organization_id, Event.ingested_at),
    Index("ix_observations_org_observed_at", Observation.organization_id, Observation.observed_at),
    Index("ix_observations_org_ingested_at", Observation.organization_id, Observation.ingested_at),
    Index("ix_ingestion_jobs_org_started_at", IngestionJob.organization_id, IngestionJob.started_at),
    Index("ix_raw_records_org_received_at", RawRecord.organization_id, RawRecord.received_at),
    Index("ix_investigations_org_created_at", Investigation.organization_id, Investigation.created_at),
]
