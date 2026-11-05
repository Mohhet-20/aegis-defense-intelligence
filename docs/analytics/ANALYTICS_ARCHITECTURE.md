# Analytics, dashboards and reporting architecture

## Layers
1. **Metric catalog** (`app/reporting/definitions.py`): 93 metric ids, each with label, definition, unit, kind (fact / derived / assessment / configured) and time basis. Published at `GET /reporting/metrics`; rendered as tooltips in the UI and embedded in every report. Full table: `METRIC_DEFINITIONS.md`.
2. **Sections** (`app/services/analytics_service.py`): events, observations, ingestion, fusion, sensors, investigations, evidence, models, system, geo, review_backlog. Each returns one envelope: `section, status, definition_version, generated_at, window, filters, sample_counts, freshness, values, tables, caveats, drilldown`. `Section.value/table` refuse an id that is not in the catalog.
3. **Consumers**: the executive dashboard, the analyst and operations dashboards, and the report builder all call the same section functions, so a number on a dashboard and the same number in a report share one definition and one code path (tested).

## Time semantics
* All instants are UTC. Windows are half-open: `start <= t < end`. A record exactly at `end` belongs to the next window.
* `time_basis=event` windows on `observed_at` (source-reported); `ingestion` windows on `ingested_at` (when AEGIS stored it). They are never mixed in a series.
* Job metrics use job start time, raw records use received time, workflow metrics use created/closed/reviewed time (each metric states its basis).
* Bounds: window ≤ `ANALYTICS_MAX_WINDOW_DAYS` (366), ≤ 400 buckets, end ≤ 1 day in the future. Auto bucket = hour for ≤ 72 h, else day.
* Late arrivals: `ingested_at - observed_at > ANALYTICS_LATE_ARRIVAL_HOURS` is reported as a rate and lag percentiles; negative lag (source clock ahead) is kept and counted in a caveat.

## Missing, zero, small and stale
* A count is a true zero only as "no stored records". Rates with no denominator are `null` + reason; job rates below `ANALYTICS_MIN_FINISHED_JOBS` are `null` ("insufficient_sample").
* Sections report `status`: `ok`, `partial` (omitted/truncated content), `empty`, `not_authorized`. `freshness` says how old the newest record is and flags `stale` beyond `ANALYTICS_STALE_HOURS`.
* Percentiles are computed in Python over at most `ANALYTICS_MAX_ROWS` rows (most recent first) and say so when truncated.

## Authorization and isolation
* `reporting:read` opens the API; each section additionally requires the permission of the data it reads (event:read, observation:read, data_quality:read, fusion:read, sensor:read+observation:read, investigation:read, evidence:read, mlops:read, geospatial:read). Without it the section returns no numbers.
* `organization_id` comes from the authenticated user and is in every query before aggregation.
* Restricted investigations the caller cannot open and restricted evidence a role may not read are excluded from counts, not merely hidden.
* Assignee distribution is administrator-only, alphabetical and labelled not-a-ranking.

## Interpretation rules (what the numbers do not mean)
* Anomalies and volume changes are prompts for review, never evidence of malicious activity.
* Correlations are associations; relationship origin (rule/model vs analyst) is shown separately.
* Evidence counts do not indicate strength; missing origin/hash rates are documentation gaps.
* Sensor "coverage" = stored observations / expected from nominal interval (capped at 1). It is **not uptime**; no uptime or queue-depth telemetry exists, so none is shown.
* Model figures are stored experiment metrics (never recomputed); results on different datasets are not ranked; drift ≠ degradation.
* Geo: valid coordinates only, binned to 0.1° cells, cells with fewer than `ANALYTICS_GEO_MIN_CELL_COUNT` suppressed, no individual coordinates returned. No targeting logic.
* No composite or threat score exists anywhere.

## Reports
Templates: platform_activity, ingestion_quality, sensor_coverage, investigation_summary, evidence_provenance, model_evaluation, system_reliability, geospatial_summary, custom (choose sections). Formats: JSON, CSV (tidy long format, formula-injection protected), HTML (self-contained, escaped, no scripts). **PDF is not supported.** Each document separates `automatic_findings` (deterministic rules over the envelopes), `analyst_commentary` (author's plain text, unverified) and `ai_generated_text` (always null in this version; no model provider is required or used).

Lifecycle: `running` → `completed` only after the file is written to a temp file, hashed and atomically renamed; any failure → `failed` with sanitized error and no file; after retention → `expired` (row kept, file deleted). Reads: private (creator + administrators) or organization (readers need REPORTING_READ and every permission the report required). Others receive 404. Audit: `report.generated`, `report.generation_failed`, `report.downloaded`, `report.expired`, `report.integrity_mismatch`, `analytics.viewed`.

## Storage and export hardening
Files live under `REPORT_STORAGE_ROOT` (default `<CV_MEDIA_STORAGE_ROOT>/reports/<org>/<run-id>.<ext>`), never served statically; the on-disk name derives from the run id and format only. Download name is `aegis-<template>-<date>-<id8>.<ext>`; `Content-Disposition: attachment`, `nosniff`, `no-store`, restrictive CSP. Download re-hashes the file and refuses it on mismatch. The SHA-256 is an integrity check of stored bytes only, not authenticity. Size cap `REPORT_MAX_ARTIFACT_BYTES`; notes cap `REPORT_MAX_NOTES_CHARS`.

## Performance
Aggregates are grouped SQL (no per-row loops except bounded percentile/geo fetches; no N+1). Migration `c16r3p0rt01` adds composite indexes on (organization_id, observed_at / ingested_at / started_at / received_at / created_at) for the windowed tables.

## Troubleshooting
* *Numbers differ between two people*: restricted records or section permissions differ; the caveats say so.
* *Recent window looks low*: event-time windows grow as late records arrive; compare with ingestion time.
* *Rate shows "insufficient sample"*: fewer than the minimum finished jobs.
* *Report "failed"*: see `error_category` (`too_large`, `generation_failed`, `validation`); narrow the window or sections. *Download 409*: expired, failed, missing file, or hash mismatch (audited).
* *Disk growth*: run `POST /reporting/reports/purge-expired` (administrator) or lower `REPORT_RETENTION_DAYS`.
