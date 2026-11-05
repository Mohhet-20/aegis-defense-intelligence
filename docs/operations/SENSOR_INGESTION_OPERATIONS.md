# Sensor Ingestion Operations

Status: implemented, live-verified, `app/services/sensor_ingestion_service.py` at 89% test
coverage in the 507-test backend suite (92% overall).

## Execution model, stated plainly

A sensor batch (`submit_file_batch()` / `submit_synthetic_batch()` in
`sensor_ingestion_service.py`) runs **synchronously inside the API request** that submits it --
the same execution model `IngestionJob`/`FusionJob`/`InferenceJob`/`TrackingJob` already use.
There is still no background worker or message queue anywhere in this codebase; a 2000-record
batch (`settings.SENSOR_MAX_OBSERVATIONS_PER_BATCH`) holds the HTTP connection open for the
whole run. This is an accepted limitation carried forward unchanged, not something this layer
introduces or needs to solve on its own -- see `docs/operations/TRACKING_OPERATIONS.md`'s own
section version of the same gap.

Sensor batches deliberately reuse the **same** `IngestionJob`/`RawRecord` tables the
Event pipeline uses -- `RawRecord.event_id` simply stays `NULL` for every row this module
creates, and `IngestionJob.job_type` gets three new values: `sensor_json_batch`,
`sensor_csv_batch`, `sensor_synthetic`. This is "extend existing models rather than creating
competing duplicates," not an oversight -- there is no separate `SensorIngestionJob` table.

## The three adapters, behind one closed registry

`app/sensors/adapters/registry.py` is a **separate** closed allow-list from
`app.connectors.registry` (the Event-ingestion one) and from the CV adapter/tracker registries
before it -- never a dynamic import of a client-supplied string, the same discipline used
throughout the codebase.

| Adapter | `connector_type` | Reached via | Notes |
|---|---|---|---|
| `SyntheticSensorConnector` | `sensor_synthetic` | `get_connector_adapter_class("sensor_synthetic")`, `POST /sensor-ingestion/synthetic-batches` | Fully deterministic -- `seed`, `count`, `base_value`, `noise_amplitude`, `interval_seconds`, `start_at`, `value_overrides` (index -> absolute value), `skip_indices`. The same `seed` always produces byte-identical output. |
| `SensorCsvBatchConnector` | `sensor_csv_batch` | `get_file_adapter_class("csv")`, `POST /sensor-ingestion/batches` with `format=csv` | Header row must contain at least `sensor_id`, `measurement_type`, `value`, `observed_at`; extra columns pass through verbatim into `Observation.payload`. |
| `SensorJsonBatchConnector` | `sensor_json_batch` | `get_file_adapter_class("json")`, `POST /sensor-ingestion/batches` with `format=json` | Accepts a bare object, `{"observations": [...]}`, or a list of objects. |

No HTTP sensor connector is registered -- unrestricted network egress was deliberately not
added this layer. A future HTTP source can reuse
`app.connectors.http_connector.HttpApiConnector`'s existing SSRF-hardened fetch path; wiring one
up is deferred, see `docs/architecture/SENSOR_DATA_ARCHITECTURE.md`.

## Routes

| Route | Permission | Purpose |
|---|---|---|
| `POST /sensor-ingestion/batches` | `Permission.OBSERVATION_INGEST` | Real file (CSV/JSON) batch submission; `multipart/form-data` with `source_id`, `format`, `file`. |
| `POST /sensor-ingestion/synthetic-batches` | `Permission.OBSERVATION_INGEST` | Synthetic batch for demo/testing, same job pipeline as a real batch. |
| `GET /sensor-ingestion/batches` | `Permission.OBSERVATION_READ` | Paginated job list, optionally filtered by `source_id`. |
| `GET /sensor-ingestion/batches/{id}` | `Permission.OBSERVATION_READ` | One job's full accounting (`accepted_count`/`rejected_count`/`skipped_count`/`duplicate_count`/`error_summary`). |
| `GET /sensor-ingestion/batches/{id}/records` | `Permission.RAW_RECORD_READ` | Raw, pre-validation `RawRecord` rows for the job -- see below. |
| `POST /sensor-ingestion/batches/{id}/retry` | `Permission.OBSERVATION_INGEST` | Retries a `failed` or `completed_with_errors` job -- see "Retry policy" below. |

A batch exceeding `settings.MAX_UPLOAD_BYTES` (5 MB) is rejected with `413` before any parsing
happens (`BatchTooLargeError`); an unsupported `format` value is `400` (`UnsupportedBatchFormatError`).

## Record-level idempotency

Unlike `TrackingJob`/`InferenceJob`, a sensor batch submission carries no job-level
`idempotency_key` -- idempotency here is **record-level**, keyed on `external_id` (the
connector-supplied id, or `record["external_id"]`, or a content-fingerprint fallback). A record
whose `external_id` was already seen earlier in the *same* batch, or already produced an
`Observation` for this `source_id` in a *previous* job, is written as a duplicate `RawRecord`
(`is_duplicate=True`, `duplicate_of_raw_record_id` pointing at the original) and counted in
`duplicate_count` -- it never produces a second `Observation`. Resubmitting the exact same file
twice is therefore safe: the second run's accepted/rejected counts read `0`, not a crash or a
silently-doubled dataset.

Separately, every record in a batch produces exactly one `RawRecord` (the quarantine/provenance
reference) and, only if `app/sensors/quality.evaluate_observation()` judged it accepted, exactly
one `Observation` -- never silently dropped. An unknown `sensor_id`
(`quality_flags: ["unknown_sensor"]`) or a batch submitted against a `retired` sensor
(`["sensor_retired"]`) is rejected per-record, not batch-wide: one bad record in a 2000-record
batch never aborts the rest (`_process_batch()`'s per-record `try`/`except` guarantees this).

## Retry policy

Only `SENSOR_RETRYABLE_JOB_TYPES = {"sensor_synthetic"}` is retryable, and only while
`job.status in ("failed", "completed_with_errors")`. A file-upload batch (`sensor_json_batch`/
`sensor_csv_batch`) is **never** retryable -- `retry_job()` raises `ValueError` ("a file-upload
batch requires re-submitting the file") because the original file bytes were never persisted. A
synthetic job is retried by re-reading `job.provenance["synthetic_config"]` and calling
`submit_synthetic_batch()` again with it; if that key is missing (e.g. the job failed
*validating* its own config before any provenance was recorded), retry is refused with "original
synthetic configuration was not preserved on this job -- cannot retry." A retry always produces
a **new** `IngestionJob` row with `retry_count` incremented -- the failed job's own row is never
mutated.

## Inspecting a job's raw records before validation

`GET /sensor-ingestion/batches/{id}/records` (`Permission.RAW_RECORD_READ`, deliberately gated
separately from `OBSERVATION_READ`) returns the job's `RawRecord` rows -- the exact payload as
received, `validation_status` (`valid`/`invalid`), `validation_errors`/`validation_warnings`,
and duplicate flags -- optionally filtered by `validation_status`. This is the only way to see
*why* a specific record was rejected; a rejected record's payload is never silently discarded.

## The seed script's behavior

`scripts/seed.py` runs one deterministic synthetic batch through the real
`sensor_ingestion_service.submit_synthetic_batch()` -- not hand-inserted rows -- so the seeded
demo data exercises the same quality/validation path a live batch would: 20 records, `seed=42`,
`base_value=22.0`, `noise_amplitude=1.2`, `interval_seconds=60.0`, against the environmental
sensor's `temperature_c` operating range (`max: 45.0`), with `value_overrides={"19": 61.0}`
deliberately injecting one out-of-range reading so `anomaly_service.run_checks()` (run
immediately after, in the same script) has a genuine detection to find. Both steps are guarded
by a single idempotency check -- an existing `IngestionJob` row with `job_type="sensor_synthetic"`
for the organization -- so re-running `seed.py` never duplicates the batch or the anomaly check.
Confirmed output from an actual run: `Seeded synthetic sensor batch: job=... accepted=20
rejected=0` / `Seeded anomaly check: created=4 already_known=0`.

## The naive/aware datetime fix

`_as_aware_utc()` in `sensor_ingestion_service.py` attaches `timezone.utc` to a datetime read
back from SQLite as naive, before comparing it against a freshly parsed (already-aware)
incoming record timestamp -- the same fix pattern already established as `_as_aware_utc` in
`app/services/user_service.py`. It was found via a real crash (`TypeError: can't compare
offset-naive and offset-aware datetimes`) seeding a second sensor batch against a sensor with
existing history, and is covered by a dedicated regression test in `tests/test_sensor_ingestion.py`.

## Known operational gaps (stated honestly, not hidden)

- No background worker: a very large batch means a correspondingly long synchronous request,
  same gap as each layer's job tables.
- No job-level idempotency key for file batches -- only the record-level `external_id` dedup
  above. A client wanting at-most-once job *submission* semantics must de-duplicate on its own
  side before calling `POST /sensor-ingestion/batches`.
- No HTTP/network sensor connector is registered (see "The three adapters" above).
- A file-upload batch cannot be retried through this API at all; the client must re-submit the
  original file.
