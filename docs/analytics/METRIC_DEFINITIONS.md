# Metric definitions (definition version 1)

Generated from `backend/app/reporting/definitions.py` (the same catalog served by `GET /api/v1/reporting/metrics`). A test fails if any analytics section emits a metric id that is not listed here.

**Kinds:** `fact` = count of stored records; `derived` = calculation over facts; `assessment` = a judgement already stored by the platform (read, never recomputed); `configured` = a setting.

**Rates** are `null` (with a reason) when the denominator is 0, or below `ANALYTICS_MIN_FINISHED_JOBS` for job-based rates. **Counts** are true zeros: they mean *no stored records*, not *no activity*.

## events

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `events.count` | Events | events | fact | event_or_ingestion_time | Stored events whose selected timestamp (event time or ingestion time) falls in the window, after filters. Archived events are excluded unless include_archived. |
| `events.by_bucket` | Events per interval | events | fact | event_or_ingestion_time | Event count per hour/day bucket of the selected time basis. A zero means no stored event had that timestamp; it does not distinguish 'quiet' from 'nothing received'. |
| `events.by_category` | Events by category | events | fact | event_or_ingestion_time | Count by event_type (top 20, remainder grouped as 'other'). |
| `events.by_source` | Events by source | events | fact | event_or_ingestion_time | Count by data source (top 20, remainder grouped as 'other'). |
| `events.by_processing_status` | Events by processing status | events | fact | event_or_ingestion_time | Count by processing_status (ingested, normalized, correlated, archived). |
| `events.by_data_origin` | Events by data origin | events | fact | event_or_ingestion_time | Count by data_origin; synthetic_demo is shown separately so demonstration data is never mistaken for real data. |
| `events.synthetic_share` | Synthetic share | proportion | derived | event_or_ingestion_time | Share of in-window events whose data_origin is synthetic_demo. |
| `events.missing_description_rate` | Missing description | proportion | derived | event_or_ingestion_time | Share of in-window events with an empty description. A missing value is not zero and not evidence of anything. |
| `events.missing_location_rate` | Missing location | proportion | derived | event_or_ingestion_time | Share of in-window events with no latitude/longitude. |
| `events.invalid_location_rate` | Invalid location | proportion | derived | event_or_ingestion_time | Among events that carry coordinates, the share whose location_validation_status is not 'valid'. |
| `events.missing_confidence_rate` | Missing confidence | proportion | derived | event_or_ingestion_time | Share of in-window events with no confidence value. |
| `events.late_arrival_rate` | Late-arriving events | proportion | derived | event_or_ingestion_time | Share of in-window events whose ingested_at is more than ANALYTICS_LATE_ARRIVAL_HOURS after observed_at. Computed over at most ANALYTICS_MAX_ROWS rows. |
| `events.ingestion_lag_p50_seconds` | Ingestion lag p50 | seconds | derived | event_or_ingestion_time | Median of ingested_at - observed_at (nearest-rank), seconds. Negative values (source clock ahead) are kept and counted as clock_skew. |
| `events.ingestion_lag_p95_seconds` | Ingestion lag p95 | seconds | derived | event_or_ingestion_time | 95th percentile of ingested_at - observed_at (nearest-rank), seconds. |

## observations

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `observations.count` | Observations | observations | fact | event_or_ingestion_time | Stored sensor observations whose selected timestamp falls in the window, after filters. |
| `observations.by_bucket` | Observations per interval | observations | fact | event_or_ingestion_time | Observation count per hour/day bucket of the selected time basis. |
| `observations.by_type` | Observations by type | observations | fact | event_or_ingestion_time | Count by observation_type (top 20 + other). |
| `observations.by_validation_status` | Observations by validation status | observations | fact | event_or_ingestion_time | Count by validation_status assigned at ingestion. |
| `observations.by_sensor` | Observations by sensor | observations | fact | event_or_ingestion_time | Count per sensor (top 20 by sensor name, then other). Not a ranking of sensor quality. |
| `observations.not_usable_rate` | Not-usable observations | proportion | derived | event_or_ingestion_time | Share of in-window observations whose validation_status is not valid or valid_with_warnings. |
| `observations.missing_value_rate` | Missing measurement value | proportion | derived | event_or_ingestion_time | Share of in-window observations with no measurement_value. |
| `observations.late_arrival_rate` | Late-arriving observations | proportion | derived | event_or_ingestion_time | Share with ingested_at more than ANALYTICS_LATE_ARRIVAL_HOURS after observed_at. |
| `observations.ingestion_lag_p50_seconds` | Ingestion lag p50 | seconds | derived | event_or_ingestion_time | Median of ingested_at - observed_at, seconds. |
| `observations.ingestion_lag_p95_seconds` | Ingestion lag p95 | seconds | derived | event_or_ingestion_time | 95th percentile of ingested_at - observed_at, seconds. |

## ingestion

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `ingestion.jobs_count` | Ingestion jobs | jobs | fact | job_start_time | Jobs whose started_at falls in the window (always job start time). |
| `ingestion.by_status` | Jobs by status | jobs | fact | job_start_time | Count by job status. |
| `ingestion.by_bucket` | Jobs per interval | jobs | fact | job_start_time | Jobs per bucket of started_at, split by outcome. |
| `ingestion.by_source` | Jobs by source | jobs | fact | job_start_time | Per-source job outcomes and record counts, plus the source's recorded last success. |
| `ingestion.failure_rate` | Job failure rate | proportion | derived | job_start_time | failed / (completed + completed_with_errors + failed) among finished jobs. Not reported (null) when fewer than ANALYTICS_MIN_FINISHED_JOBS jobs have finished. |
| `ingestion.partial_rate` | Jobs completed with errors | proportion | derived | job_start_time | completed_with_errors / finished jobs; same minimum denominator as failure_rate. |
| `ingestion.duration_p50_seconds` | Job duration p50 | seconds | derived | job_start_time | Median of completed_at - started_at over finished jobs, seconds. |
| `ingestion.duration_p95_seconds` | Job duration p95 | seconds | derived | job_start_time | 95th percentile of completed_at - started_at over finished jobs, seconds. |
| `ingestion.records_accepted` | Records accepted | records | fact | job_start_time | Sum of accepted_count over in-window jobs. |
| `ingestion.records_rejected` | Records rejected | records | fact | job_start_time | Sum of rejected_count over in-window jobs. |
| `ingestion.records_skipped` | Records skipped | records | fact | job_start_time | Sum of skipped_count over in-window jobs. |
| `ingestion.records_duplicate` | Duplicate records | records | fact | job_start_time | Sum of duplicate_count over in-window jobs (records recognised as already stored). |
| `ingestion.duplicate_rate` | Duplicate rate | proportion | derived | job_start_time | duplicate / (accepted + rejected + skipped + duplicate) over in-window jobs. Duplicates are expected with overlapping pulls and are not a fault by themselves. |
| `ingestion.raw_records` | Raw records received | records | fact | received_time | Raw records whose received_at falls in the window. |
| `ingestion.raw_invalid_rate` | Raw records failing validation | proportion | derived | received_time | Share of in-window raw records with validation_status 'invalid'. |
| `ingestion.raw_duplicate_rate` | Raw records flagged duplicate | proportion | derived | received_time | Share of in-window raw records with is_duplicate set. |

## fusion

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `fusion.correlations_by_review_status` | Correlations by review status | correlations | fact | created_time | Correlation candidates created in the window, by review_status. A correlation is an association, not proof of causation or identity. |
| `fusion.relationships_by_type_origin` | Relationships by type and origin | relationships | fact | created_time | Evidence relationships created in the window by relationship_type and origin (rule_based/model_assisted = inferred; analyst_created = explicitly recorded). |
| `fusion.relationships_inferred_share` | Inferred relationship share | proportion | derived | created_time | Share of in-window relationships whose origin is rule_based or model_assisted rather than analyst_created. |
| `fusion.conflicts_by_status` | Conflicts by status | conflicts | fact | created_time | Conflicts created in the window by review_status. |
| `fusion.conflicts_unresolved` | Unresolved conflicts | conflicts | fact | current | All conflicts currently in status 'unresolved' (a backlog, not windowed). |
| `fusion.jobs_by_status` | Fusion jobs by status | jobs | fact | job_start_time | Fusion jobs started in the window by status. |
| `fusion.time_to_review_p50_seconds` | Correlation time-to-review p50 | seconds | derived | review_time | Median of reviewed_at - created_at for correlations reviewed in the window, seconds. |

## sensors

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `sensors.by_lifecycle_status` | Sensors by lifecycle status | sensors | fact | current | Current count of sensors by lifecycle_status (not windowed). |
| `sensors.coverage` | Observation coverage per sensor | proportion | derived | event_or_ingestion_time | Observations received in the window divided by the observations expected from the sensor's nominal_sampling_interval_seconds (capped at 1). Null when no nominal interval is configured. This is data coverage, NOT uptime or availability. |
| `sensors.silent_count` | Sensors with no observations | sensors | derived | event_or_ingestion_time | Active/degraded sensors with zero stored observations in the window. A silent sensor may be offline, misconfigured, or simply have no data stored; it is not evidence of tampering. |
| `sensors.by_category` | Sensor groups by category | sensors | fact | event_or_ingestion_time | Sensor count and in-window observation count grouped by sensor category. |
| `sensors.anomalies_by_review_status` | Anomalies by review status | anomalies | fact | created_time | Recorded anomaly candidates created in the window by review_status. An anomaly is a statistical flag for review, not a finding. |
| `sensors.anomalies_by_severity` | Anomalies by severity | anomalies | fact | created_time | Recorded anomaly candidates created in the window by severity. |

## investigations

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `investigations.by_status` | Investigations by status | investigations | fact | current | Current count by status among investigations visible to the caller (restricted investigations the caller cannot open are excluded). |
| `investigations.created_count` | Investigations created | investigations | fact | created_time | Visible investigations whose created_at is in the window. |
| `investigations.closed_count` | Investigations closed | investigations | fact | closed_time | Visible investigations whose closed_at is in the window. |
| `investigations.created_by_bucket` | Created per interval | investigations | fact | created_time | Visible investigations created per bucket. |
| `investigations.closed_by_bucket` | Closed per interval | investigations | fact | closed_time | Visible investigations closed per bucket. |
| `investigations.time_to_close_p50_days` | Time to close p50 | days | derived | closed_time | Median of closed_at - created_at (days) for visible investigations closed in the window. Null when none closed. |
| `investigations.by_priority` | Open investigations by priority | investigations | fact | current | Current count of non-closed, non-archived visible investigations by priority. |
| `investigations.transitions` | Status transitions | transitions | fact | transition_time | Status-history rows in the window by target status. |
| `investigations.assignment_distribution` | Assignment distribution | investigations | fact | current | Open visible investigations per assignee (administrators only; listed alphabetically, deliberately not ranked, and not a productivity measure). |

## evidence

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `evidence.count` | Evidence items | items | fact | created_time | Evidence items created in the window that the caller may access (restricted items excluded for roles without access). More items does not mean stronger evidence. |
| `evidence.by_type` | Evidence by type | items | fact | created_time | Count by evidence_type. |
| `evidence.by_review_status` | Evidence by review status | items | fact | created_time | Count by review_status. |
| `evidence.missing_origin_rate` | Evidence without a recorded origin link | proportion | derived | created_time | Share of in-window evidence with no linked event, raw record, observation, media, detection, source or external reference. |
| `evidence.missing_integrity_hash_rate` | Evidence without an integrity hash | proportion | derived | created_time | Share of in-window evidence with no recorded integrity hash. A hash is an integrity check of stored content, not proof of authenticity. |
| `evidence.review_backlog` | Evidence awaiting review | items | fact | current | All accessible evidence currently unreviewed or in_review (backlog, not windowed). |
| `evidence.integrity_checks_by_result` | Integrity checks by result | checks | fact | check_time | Evidence integrity checks run in the window by result. |
| `evidence.notes_by_kind` | Analyst notes by kind | notes | fact | created_time | Investigation notes created in the window by note_kind, over visible investigations. |

## models

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `models.versions_by_lifecycle` | Model versions by lifecycle state | versions | fact | current | Visible model versions by lifecycle_state (current). |
| `models.evaluation_status` | Derived evaluation status | versions | fact | current | Per-version status derived by the MLOps registry (none, running, failed, stale, review_needed, passed). 'passed' is not a quality claim. |
| `models.runs_by_status` | Experiment runs by status | runs | fact | run_start_time | Experiment runs started in the window by status. |
| `models.run_duration_p50_seconds` | Run duration p50 | seconds | derived | run_start_time | Median experiment duration over succeeded/failed runs in the window, seconds. |
| `models.latest_evaluations` | Latest evaluations | runs | assessment | current | Most recent succeeded run per version with its stored metrics, sample count and dataset name/version (read from stored experiment runs via the MLOps service; metrics are never recomputed here, and runs on different datasets are not ranked against each other). |
| `models.signals_by_category` | Open model review signals | signals | fact | current | Unresolved model-quality review signals by category and severity. Drift, prediction drift and measured performance degradation are distinct categories. |
| `models.monitoring_coverage` | Monitoring coverage | versions | fact | current | Model versions with a current monitoring snapshot vs. in scope. |
| `models.inference_jobs_by_status` | Inference jobs by status | jobs | fact | created_time | Inference jobs created in the window by status. |
| `models.inference_failure_rate` | Inference failure rate | proportion | derived | created_time | failed / (completed + failed) among finished inference jobs; null below ANALYTICS_MIN_FINISHED_JOBS. |
| `models.inference_duration_p50_seconds` | Inference duration p50 | seconds | derived | created_time | Median finished_at - started_at over completed jobs, seconds. |
| `models.inference_duration_p95_seconds` | Inference duration p95 | seconds | derived | created_time | 95th percentile finished_at - started_at over completed jobs, seconds. |

## system

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `system.dependency_health` | Dependency health (now) | status | fact | current | Result of the readiness probes at generation time. A point-in-time check, not a trend and not an uptime percentage. |
| `system.jobs_by_status` | Background job outcomes | jobs | fact | job_start_time | Ingestion, fusion and inference jobs started in the window by status. |
| `system.requests_total` | API requests (this process) | requests | fact | process_lifetime | Requests counted by the in-process metrics registry since process start. Per-process; resets on restart; requires observability:read. |
| `system.server_error_rate` | API 5xx rate (this process) | proportion | derived | process_lifetime | 5xx responses / all responses since process start; null when no requests were counted. |
| `system.latency_upper_bound_p50_seconds` | API latency p50 (upper bound) | seconds | derived | process_lifetime | Upper bound of the histogram bucket containing the median since process start. |
| `system.latency_upper_bound_p95_seconds` | API latency p95 (upper bound) | seconds | derived | process_lifetime | Upper bound of the histogram bucket containing the 95th percentile since process start. |
| `system.lifecycle_requests_by_status` | Data-lifecycle requests | requests | fact | created_time | Lifecycle requests created in the window by status. |
| `system.reports_by_status` | Reports generated | reports | fact | created_time | Report runs created in the window by status and template. |

## geo

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `geo.coordinate_status` | Coordinate validity | records | fact | event_or_ingestion_time | Events and observations in the window split by whether they carry coordinates and their location_validation_status. |
| `geo.grid_cells` | Records per grid cell | records | fact | event_or_ingestion_time | Records with valid coordinates aggregated into square cells of the stated resolution (degrees). Cells with fewer than ANALYTICS_GEO_MIN_CELL_COUNT records are suppressed. Individual coordinates are never returned. |
| `geo.median_uncertainty_m` | Median location uncertainty | metres | derived | event_or_ingestion_time | Median location_uncertainty_m over in-window records that report it. Null when none do. |

## review_backlog

| Metric id | Label | Unit | Kind | Time basis | Definition |
|---|---|---|---|---|---|
| `review.backlog` | Review backlog | items | fact | current | Items currently awaiting a human decision, by queue (current state, not windowed). Each queue is shown only to callers who may read it. |
