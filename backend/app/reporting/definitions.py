"""Shared metric definitions.

Every number reported by an analytics section or a report has an id here. The same
id means the same thing on every dashboard and in every report because both read
the same section functions; this catalog is the human-readable contract
(`GET /reporting/metrics`, docs/analytics/METRIC_DEFINITIONS.md). `Env.value` and
`Env.table` refuse an id that is not defined here, and a test fails if a section
emits one that is missing.

Kinds of statement (never blurred): ``fact`` (a count of stored records),
``derived`` (a calculation over facts), ``assessment`` (an analyst/model
judgement already stored by the platform), ``configured`` (a threshold/setting).
"""
from __future__ import annotations

DEFINITION_VERSION = "1"

_C: dict[str, dict] = {}


def _m(mid: str, section: str, label: str, definition: str, unit: str, kind: str = "fact", basis: str = "event_or_ingestion_time", caveat: str | None = None) -> None:
    _C[mid] = {"id": mid, "section": section, "label": label, "definition": definition, "unit": unit, "kind": kind, "time_basis": basis, "caveat": caveat}


# ---- events -------------------------------------------------------------------
_m("events.count", "events", "Events", "Stored events whose selected timestamp (event time or ingestion time) falls in the window, after filters. Archived events are excluded unless include_archived.", "events")
_m("events.by_bucket", "events", "Events per interval", "Event count per hour/day bucket of the selected time basis. A zero means no stored event had that timestamp; it does not distinguish 'quiet' from 'nothing received'.", "events")
_m("events.by_category", "events", "Events by category", "Count by event_type (top 20, remainder grouped as 'other').", "events")
_m("events.by_source", "events", "Events by source", "Count by data source (top 20, remainder grouped as 'other').", "events")
_m("events.by_processing_status", "events", "Events by processing status", "Count by processing_status (ingested, normalized, correlated, archived).", "events")
_m("events.by_data_origin", "events", "Events by data origin", "Count by data_origin; synthetic_demo is shown separately so demonstration data is never mistaken for real data.", "events")
_m("events.synthetic_share", "events", "Synthetic share", "Share of in-window events whose data_origin is synthetic_demo.", "proportion", "derived")
_m("events.missing_description_rate", "events", "Missing description", "Share of in-window events with an empty description. A missing value is not zero and not evidence of anything.", "proportion", "derived")
_m("events.missing_location_rate", "events", "Missing location", "Share of in-window events with no latitude/longitude.", "proportion", "derived")
_m("events.invalid_location_rate", "events", "Invalid location", "Among events that carry coordinates, the share whose location_validation_status is not 'valid'.", "proportion", "derived")
_m("events.missing_confidence_rate", "events", "Missing confidence", "Share of in-window events with no confidence value.", "proportion", "derived")
_m("events.late_arrival_rate", "events", "Late-arriving events", "Share of in-window events whose ingested_at is more than ANALYTICS_LATE_ARRIVAL_HOURS after observed_at. Computed over at most ANALYTICS_MAX_ROWS rows.", "proportion", "derived")
_m("events.ingestion_lag_p50_seconds", "events", "Ingestion lag p50", "Median of ingested_at - observed_at (nearest-rank), seconds. Negative values (source clock ahead) are kept and counted as clock_skew.", "seconds", "derived")
_m("events.ingestion_lag_p95_seconds", "events", "Ingestion lag p95", "95th percentile of ingested_at - observed_at (nearest-rank), seconds.", "seconds", "derived")
# ---- observations ---------------------------------------------------------------
_m("observations.count", "observations", "Observations", "Stored sensor observations whose selected timestamp falls in the window, after filters.", "observations")
_m("observations.by_bucket", "observations", "Observations per interval", "Observation count per hour/day bucket of the selected time basis.", "observations")
_m("observations.by_type", "observations", "Observations by type", "Count by observation_type (top 20 + other).", "observations")
_m("observations.by_validation_status", "observations", "Observations by validation status", "Count by validation_status assigned at ingestion.", "observations")
_m("observations.by_sensor", "observations", "Observations by sensor", "Count per sensor (top 20 by sensor name, then other). Not a ranking of sensor quality.", "observations")
_m("observations.not_usable_rate", "observations", "Not-usable observations", "Share of in-window observations whose validation_status is not valid or valid_with_warnings.", "proportion", "derived")
_m("observations.missing_value_rate", "observations", "Missing measurement value", "Share of in-window observations with no measurement_value.", "proportion", "derived")
_m("observations.late_arrival_rate", "observations", "Late-arriving observations", "Share with ingested_at more than ANALYTICS_LATE_ARRIVAL_HOURS after observed_at.", "proportion", "derived")
_m("observations.ingestion_lag_p50_seconds", "observations", "Ingestion lag p50", "Median of ingested_at - observed_at, seconds.", "seconds", "derived")
_m("observations.ingestion_lag_p95_seconds", "observations", "Ingestion lag p95", "95th percentile of ingested_at - observed_at, seconds.", "seconds", "derived")
# ---- ingestion --------------------------------------------------------------------
_m("ingestion.jobs_count", "ingestion", "Ingestion jobs", "Jobs whose started_at falls in the window (always job start time).", "jobs", basis="job_start_time")
_m("ingestion.by_status", "ingestion", "Jobs by status", "Count by job status.", "jobs", basis="job_start_time")
_m("ingestion.by_bucket", "ingestion", "Jobs per interval", "Jobs per bucket of started_at, split by outcome.", "jobs", basis="job_start_time")
_m("ingestion.by_source", "ingestion", "Jobs by source", "Per-source job outcomes and record counts, plus the source's recorded last success.", "jobs", basis="job_start_time")
_m("ingestion.failure_rate", "ingestion", "Job failure rate", "failed / (completed + completed_with_errors + failed) among finished jobs. Not reported (null) when fewer than ANALYTICS_MIN_FINISHED_JOBS jobs have finished.", "proportion", "derived", "job_start_time")
_m("ingestion.partial_rate", "ingestion", "Jobs completed with errors", "completed_with_errors / finished jobs; same minimum denominator as failure_rate.", "proportion", "derived", "job_start_time")
_m("ingestion.duration_p50_seconds", "ingestion", "Job duration p50", "Median of completed_at - started_at over finished jobs, seconds.", "seconds", "derived", "job_start_time")
_m("ingestion.duration_p95_seconds", "ingestion", "Job duration p95", "95th percentile of completed_at - started_at over finished jobs, seconds.", "seconds", "derived", "job_start_time")
_m("ingestion.records_accepted", "ingestion", "Records accepted", "Sum of accepted_count over in-window jobs.", "records", basis="job_start_time")
_m("ingestion.records_rejected", "ingestion", "Records rejected", "Sum of rejected_count over in-window jobs.", "records", basis="job_start_time")
_m("ingestion.records_skipped", "ingestion", "Records skipped", "Sum of skipped_count over in-window jobs.", "records", basis="job_start_time")
_m("ingestion.records_duplicate", "ingestion", "Duplicate records", "Sum of duplicate_count over in-window jobs (records recognised as already stored).", "records", basis="job_start_time")
_m("ingestion.duplicate_rate", "ingestion", "Duplicate rate", "duplicate / (accepted + rejected + skipped + duplicate) over in-window jobs. Duplicates are expected with overlapping pulls and are not a fault by themselves.", "proportion", "derived", "job_start_time")
_m("ingestion.raw_records", "ingestion", "Raw records received", "Raw records whose received_at falls in the window.", "records", basis="received_time")
_m("ingestion.raw_invalid_rate", "ingestion", "Raw records failing validation", "Share of in-window raw records with validation_status 'invalid'.", "proportion", "derived", "received_time")
_m("ingestion.raw_duplicate_rate", "ingestion", "Raw records flagged duplicate", "Share of in-window raw records with is_duplicate set.", "proportion", "derived", "received_time")
# ---- fusion -------------------------------------------------------------------------
_m("fusion.correlations_by_review_status", "fusion", "Correlations by review status", "Correlation candidates created in the window, by review_status. A correlation is an association, not proof of causation or identity.", "correlations", basis="created_time")
_m("fusion.relationships_by_type_origin", "fusion", "Relationships by type and origin", "Evidence relationships created in the window by relationship_type and origin (rule_based/model_assisted = inferred; analyst_created = explicitly recorded).", "relationships", basis="created_time")
_m("fusion.relationships_inferred_share", "fusion", "Inferred relationship share", "Share of in-window relationships whose origin is rule_based or model_assisted rather than analyst_created.", "proportion", "derived", "created_time")
_m("fusion.conflicts_by_status", "fusion", "Conflicts by status", "Conflicts created in the window by review_status.", "conflicts", basis="created_time")
_m("fusion.conflicts_unresolved", "fusion", "Unresolved conflicts", "All conflicts currently in status 'unresolved' (a backlog, not windowed).", "conflicts", basis="current")
_m("fusion.jobs_by_status", "fusion", "Fusion jobs by status", "Fusion jobs started in the window by status.", "jobs", basis="job_start_time")
_m("fusion.time_to_review_p50_seconds", "fusion", "Correlation time-to-review p50", "Median of reviewed_at - created_at for correlations reviewed in the window, seconds.", "seconds", "derived", "review_time")
# ---- sensors --------------------------------------------------------------------------
_m("sensors.by_lifecycle_status", "sensors", "Sensors by lifecycle status", "Current count of sensors by lifecycle_status (not windowed).", "sensors", basis="current")
_m("sensors.coverage", "sensors", "Observation coverage per sensor", "Observations received in the window divided by the observations expected from the sensor's nominal_sampling_interval_seconds (capped at 1). Null when no nominal interval is configured. This is data coverage, NOT uptime or availability.", "proportion", "derived")
_m("sensors.silent_count", "sensors", "Sensors with no observations", "Active/degraded sensors with zero stored observations in the window. A silent sensor may be offline, misconfigured, or simply have no data stored; it is not evidence of tampering.", "sensors", "derived")
_m("sensors.by_category", "sensors", "Sensor groups by category", "Sensor count and in-window observation count grouped by sensor category.", "sensors")
_m("sensors.anomalies_by_review_status", "sensors", "Anomalies by review status", "Recorded anomaly candidates created in the window by review_status. An anomaly is a statistical flag for review, not a finding.", "anomalies", basis="created_time")
_m("sensors.anomalies_by_severity", "sensors", "Anomalies by severity", "Recorded anomaly candidates created in the window by severity.", "anomalies", basis="created_time")
# ---- investigations -----------------------------------------------------------------------
_m("investigations.by_status", "investigations", "Investigations by status", "Current count by status among investigations visible to the caller (restricted investigations the caller cannot open are excluded).", "investigations", basis="current")
_m("investigations.created_count", "investigations", "Investigations created", "Visible investigations whose created_at is in the window.", "investigations", basis="created_time")
_m("investigations.closed_count", "investigations", "Investigations closed", "Visible investigations whose closed_at is in the window.", "investigations", basis="closed_time")
_m("investigations.created_by_bucket", "investigations", "Created per interval", "Visible investigations created per bucket.", "investigations", basis="created_time")
_m("investigations.closed_by_bucket", "investigations", "Closed per interval", "Visible investigations closed per bucket.", "investigations", basis="closed_time")
_m("investigations.time_to_close_p50_days", "investigations", "Time to close p50", "Median of closed_at - created_at (days) for visible investigations closed in the window. Null when none closed.", "days", "derived", "closed_time")
_m("investigations.by_priority", "investigations", "Open investigations by priority", "Current count of non-closed, non-archived visible investigations by priority.", "investigations", basis="current")
_m("investigations.transitions", "investigations", "Status transitions", "Status-history rows in the window by target status.", "transitions", basis="transition_time")
_m("investigations.assignment_distribution", "investigations", "Assignment distribution", "Open visible investigations per assignee (administrators only; listed alphabetically, deliberately not ranked, and not a productivity measure).", "investigations", basis="current")
# ---- evidence ---------------------------------------------------------------------------------
_m("evidence.count", "evidence", "Evidence items", "Evidence items created in the window that the caller may access (restricted items excluded for roles without access). More items does not mean stronger evidence.", "items", basis="created_time")
_m("evidence.by_type", "evidence", "Evidence by type", "Count by evidence_type.", "items", basis="created_time")
_m("evidence.by_review_status", "evidence", "Evidence by review status", "Count by review_status.", "items", basis="created_time")
_m("evidence.missing_origin_rate", "evidence", "Evidence without a recorded origin link", "Share of in-window evidence with no linked event, raw record, observation, media, detection, source or external reference.", "proportion", "derived", "created_time")
_m("evidence.missing_integrity_hash_rate", "evidence", "Evidence without an integrity hash", "Share of in-window evidence with no recorded integrity hash. A hash is an integrity check of stored content, not proof of authenticity.", "proportion", "derived", "created_time")
_m("evidence.review_backlog", "evidence", "Evidence awaiting review", "All accessible evidence currently unreviewed or in_review (backlog, not windowed).", "items", basis="current")
_m("evidence.integrity_checks_by_result", "evidence", "Integrity checks by result", "Evidence integrity checks run in the window by result.", "checks", basis="check_time")
_m("evidence.notes_by_kind", "evidence", "Analyst notes by kind", "Investigation notes created in the window by note_kind, over visible investigations.", "notes", basis="created_time")
# ---- models -------------------------------------------------------------------------------------
_m("models.versions_by_lifecycle", "models", "Model versions by lifecycle state", "Visible model versions by lifecycle_state (current).", "versions", basis="current")
_m("models.evaluation_status", "models", "Derived evaluation status", "Per-version status derived by the MLOps registry (none, running, failed, stale, review_needed, passed). 'passed' is not a quality claim.", "versions", basis="current")
_m("models.runs_by_status", "models", "Experiment runs by status", "Experiment runs started in the window by status.", "runs", basis="run_start_time")
_m("models.run_duration_p50_seconds", "models", "Run duration p50", "Median experiment duration over succeeded/failed runs in the window, seconds.", "seconds", "derived", "run_start_time")
_m("models.latest_evaluations", "models", "Latest evaluations", "Most recent succeeded run per version with its stored metrics, sample count and dataset name/version (read from stored experiment runs via the MLOps service; metrics are never recomputed here, and runs on different datasets are not ranked against each other).", "runs", "assessment", "current")
_m("models.signals_by_category", "models", "Open model review signals", "Unresolved model-quality review signals by category and severity. Drift, prediction drift and measured performance degradation are distinct categories.", "signals", basis="current")
_m("models.monitoring_coverage", "models", "Monitoring coverage", "Model versions with a current monitoring snapshot vs. in scope.", "versions", basis="current")
_m("models.inference_jobs_by_status", "models", "Inference jobs by status", "Inference jobs created in the window by status.", "jobs", basis="created_time")
_m("models.inference_failure_rate", "models", "Inference failure rate", "failed / (completed + failed) among finished inference jobs; null below ANALYTICS_MIN_FINISHED_JOBS.", "proportion", "derived", "created_time")
_m("models.inference_duration_p50_seconds", "models", "Inference duration p50", "Median finished_at - started_at over completed jobs, seconds.", "seconds", "derived", "created_time")
_m("models.inference_duration_p95_seconds", "models", "Inference duration p95", "95th percentile finished_at - started_at over completed jobs, seconds.", "seconds", "derived", "created_time")
# ---- system -------------------------------------------------------------------------------------------
_m("system.dependency_health", "system", "Dependency health (now)", "Result of the readiness probes at generation time. A point-in-time check, not a trend and not an uptime percentage.", "status", basis="current")
_m("system.jobs_by_status", "system", "Background job outcomes", "Ingestion, fusion and inference jobs started in the window by status.", "jobs", basis="job_start_time")
_m("system.requests_total", "system", "API requests (this process)", "Requests counted by the in-process metrics registry since process start. Per-process; resets on restart; requires observability:read.", "requests", basis="process_lifetime")
_m("system.server_error_rate", "system", "API 5xx rate (this process)", "5xx responses / all responses since process start; null when no requests were counted.", "proportion", "derived", "process_lifetime")
_m("system.latency_upper_bound_p50_seconds", "system", "API latency p50 (upper bound)", "Upper bound of the histogram bucket containing the median since process start.", "seconds", "derived", "process_lifetime")
_m("system.latency_upper_bound_p95_seconds", "system", "API latency p95 (upper bound)", "Upper bound of the histogram bucket containing the 95th percentile since process start.", "seconds", "derived", "process_lifetime")
_m("system.lifecycle_requests_by_status", "system", "Data-lifecycle requests", "Lifecycle requests created in the window by status.", "requests", basis="created_time")
_m("system.reports_by_status", "system", "Reports generated", "Report runs created in the window by status and template.", "reports", basis="created_time")
# ---- geo ---------------------------------------------------------------------------------------------------
_m("geo.coordinate_status", "geo", "Coordinate validity", "Events and observations in the window split by whether they carry coordinates and their location_validation_status.", "records")
_m("geo.grid_cells", "geo", "Records per grid cell", "Records with valid coordinates aggregated into square cells of the stated resolution (degrees). Cells with fewer than ANALYTICS_GEO_MIN_CELL_COUNT records are suppressed. Individual coordinates are never returned.", "records")
_m("geo.median_uncertainty_m", "geo", "Median location uncertainty", "Median location_uncertainty_m over in-window records that report it. Null when none do.", "metres", "derived")
# ---- review backlog -----------------------------------------------------------------------------------------------
_m("review.backlog", "review_backlog", "Review backlog", "Items currently awaiting a human decision, by queue (current state, not windowed). Each queue is shown only to callers who may read it.", "items", basis="current")

CATALOG: dict[str, dict] = _C
SECTION_IDS = ("events", "observations", "ingestion", "fusion", "sensors", "investigations", "evidence", "models", "system", "geo", "review_backlog")


def get(metric_id: str) -> dict:
    return CATALOG[metric_id]


def for_section(section: str) -> list[dict]:
    return [m for m in CATALOG.values() if m["section"] == section]
