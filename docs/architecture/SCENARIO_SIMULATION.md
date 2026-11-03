# Scenario Simulation, What-If Analysis and Synthetic Data (Phase 13)

This document describes what is actually implemented. **Everything produced by this feature is SIMULATED.** It comes from a
seeded model running on synthetic data under stated assumptions. It is not an observation of the real world, it is not evidence,
and it never modifies an assessment.

## What exists

| Capability | Status |
|---|---|
| Scenario definitions (draft / ready / archived), templates, immutable versions with lineage | Implemented |
| Typed, range-checked parameters; rejection of unknown, oversized or malformed configuration | Implemented |
| Synthetic time-series generator (deterministic, labelled, bounded) | Implemented |
| Three simulators: `threshold_detection`, `source_availability`, `duplicate_out_of_order` | Implemented and tested |
| Bounded synchronous execution with measured runtime, config snapshot, result hash | Implemented |
| Safe retry, idempotency keys, concurrent-run guard, stale-run expiry | Implemented |
| What-if comparison (1 baseline vs 1-3 alternatives) with attribution rules | Implemented |
| One-parameter-at-a-time sensitivity sweeps with seed repetitions | Implemented |
| JSON and Markdown exports labelled as simulated | Implemented |
| Retrieval/copilot integration (separate, labelled, opt-in type) | Implemented |
| Frontend workspace: list/builder, overview, runs + run details, compare, sensitivity | Implemented (type-checked and built; **not exercised in a browser**) |
| Simulators for model-evaluation comparison and assessment-parameter changes | **Not implemented** |
| Run cancellation, background/queued execution | **Not implemented** (runs are synchronous and short; there is nothing to cancel) |
| Confidence intervals | **Deliberately not computed** |

## Architecture

```
app/simulation/            pure Python, no database, no I/O, no network
  params.py                ParamSpec + strict validate_params
  stats.py                 quantile, summarize, relative_diff
  generator.py             seeded synthetic series + fault injection + header/hash
  simulators.py            REGISTRY of three Simulator objects; validate(); execute()
  analysis.py              compare_runs(), plan_sensitivity(), run_sensitivity()
  templates.py             hard-coded scenario templates (data only)
app/models/scenario.py     scenarios, scenario_runs, synthetic_datasets
app/services/scenario_service.py   org scoping, lifecycle, runs, export (flush only)
app/api/routes/scenarios.py        HTTP layer (RBAC, audit, single commit per action)
app/schemas/scenario.py            strict Pydantic schemas (unknown fields rejected)
```

The engine never imports anything named by a request or a database row. A simulator is selected by a string key looked up in a
hard-coded dictionary; an unknown key raises `unknown_simulator`. There is no plugin mechanism, no `eval`/`exec`, no shell and no
user-supplied SQL anywhere in this feature.

### Data model

* `scenarios` - the **definition**: lineage id, version, parent, title, question, category, template, simulator id and version,
  validated parameters, assumptions, limitations, seed, execution config (only `max_seconds`), status, optional context
  `investigation_id`, owner, and `latest_summary` (headline metrics of the last completed run, for display/search).
  Unique on (organization, lineage, version).
* `scenario_runs` - one row per execution: status (`running`, `completed`, `failed`), **immutable config snapshot**, simulator
  version, seed, dataset reference (header + hash, not the records), results, result SHA-256, safe error code/message,
  idempotency key, `retry_of_run_id`, start/finish timestamps and measured `runtime_ms`. Index on
  (organization, scenario, created_at); unique on (organization, scenario, idempotency key).
* `synthetic_datasets` - explicitly generated fixtures: generator id/version, parameters, seed, counts, up to 5,000 stored
  records, header, content hash, `is_synthetic` (always true). Stored in their own table; **never** in `observations`, `events`
  or any operational table.

Definitions and results are separate: re-running never overwrites a prior run, and a scenario in `ready` state cannot be edited.
To change a parameter you duplicate it, which creates `version + 1` in the same lineage (`parent_scenario_id` points at the source).

### Lifecycle

`draft` -> `ready` (requires at least one recorded assumption - the "review assumptions" step) -> `archived`.
Only `ready` scenarios can run. Run states are `running` -> `completed` | `failed`. There is no `cancelled` state because
cancellation is not implemented; the scenario state list in the specification (`running`, `cancelled`) is therefore reflected on
runs only (`running`), not on scenarios.

## Execution and resource controls

| Control | Value |
|---|---|
| Wall-clock budget per simulation | `SCENARIO_MAX_RUN_SECONDS` (20 s); scenario `execution_config.max_seconds` may only lower it (0.1-20) |
| Wall-clock budget per sensitivity sweep | `SCENARIO_MAX_SWEEP_SECONDS` (45 s) |
| Generated records per run | 20,000 (points x sources); `n_points` <= 5,000, `n_sources` <= 5 |
| Stored synthetic dataset records | 5,000 (count of all generated records is still recorded; `records_truncated` flag) |
| Serialized result size | `SCENARIO_MAX_RESULT_BYTES` (400,000); larger results are discarded and the run is `failed` (`resource_limit`) |
| Sweep | <= 4 parameters, <= 9 values each, <= 20 repetitions, <= 200 simulations in total |
| Compare | 1 baseline + 1-3 alternatives |
| Per organization | 500 scenarios, 200 datasets; per scenario 200 runs |
| Parameters per request | <= 64 keys, every key must exist in the simulator's spec |

Memory is bounded indirectly: record counts and sweep sizes are capped before anything is generated. There is no OS-level memory
limit or CPU sandbox; a worker process running a simulation is not isolated from the API process. This is documented as a known gap.

A run is committed as `running` before work starts (so concurrent requests see it) and updated to `completed`/`failed` afterwards.
If the process dies in between, the row stays `running`; the next run request marks any `running` row older than
`SCENARIO_STALE_RUN_SECONDS` (300 s) as `failed` with code `stale_run`. A stale or interrupted run is never reported as completed.
Unexpected exceptions are stored as `internal_error` with a generic message; exception text is never returned.

## Reproducibility guarantees

* Python's `random.Random` is seeded with strings built from the user seed and a purpose label, giving independent, deterministic
  streams that do not depend on the platform or on `PYTHONHASHSEED`.
* Same simulator version + same parameters + same seed => byte-identical result and the same `result_sha256` (tested via the API).
  A different seed gives a different dataset. The simulator version is part of the snapshot; a changed algorithm must bump it.
* **Nested fault sets:** a value is drawn for every slot regardless of the fault rates, so raising `missing_rate` removes more
  records from the *same* underlying series rather than drawing a new one. This keeps what-if comparisons about the parameter.
* Floats in metrics are rounded to 8 places; non-finite values become `null` ("undefined for this run"), never `0` or `NaN`.
* Timestamps (`generated_at`, `started_at`) are outside the content hash. `runtime_ms` is measured with a monotonic clock and is
  not part of the hash.

## Statistical interpretation

* **Comparison** describes how two simulated runs differ. It is an association within the experiment, never a real-world causal
  effect. Each alternative gets an attribution status: `identical_inputs`, `single_parameter` (exactly one parameter differs, same
  seed and simulator version), `multiple_inputs` (several parameters, a seed or a simulator version differ - no single input is credited), or `incomparable` (different simulators).
* Absolute difference is shown whenever both values exist; relative difference only when the baseline is non-zero. Otherwise the
  reason is returned ("baseline is 0, so a relative difference is undefined").
* **Sensitivity** is one-parameter-at-a-time: every other parameter stays at the scenario's value, so *interactions are not
  explored*. All tested values of a parameter reuse the same seeds (common random numbers). The "effect range" is the max minus
  min of the mean of the chosen metric across tested values - a statement about this simulation over the tested range.
  `exceeds_baseline_seed_variability` (effect range > 2 x baseline across-seed standard deviation) is a **rough heuristic, not a statistical test**.
* **Spread across seeds** (sd, min, max; p10/p50/p90 only when n >= 5) is variability of the simulated outcome. It is not
  uncertainty about the real world, and **no confidence interval is computed anywhere** because none is justified: the
  repetitions are draws from the model, not a sample of reality.

## Retrieval, copilot and investigation integration

* A scenario may reference an investigation as context. The caller must be able to access that investigation (restricted
  investigations follow membership); afterwards the scenario is visible only to people who can access the investigation.
  Linking does **not** add the scenario to the investigation's evidence, timeline or assessments.
* `scenario` is an indexable retrieval type with a title prefixed `[SIMULATED]` and a banner line in its text. It is **excluded
  from every default search and copilot answer**; callers must pass `record_type=scenario` / `record_types:["scenario"]`.
  When a citation is a scenario the answer carries an uncertainty note: the content is hypothetical and not evidence.
  Runs and synthetic datasets are never indexed.
* Nothing in this feature writes to assessments, observations, events or evidence (asserted by tests that compare table counts and
  assessment rows before/after).

## Supported simulators

### `threshold_detection` v1.0.0 - Threshold anomaly detection under data-quality assumptions

Generates a synthetic series with injected spikes, noise and gaps, applies a rolling-median/MAD threshold detector, and scores it against the injected ground truth.

| Parameter | Type | Default | Range / choices | Unit | Meaning |
|---|---|---|---|---|---|
| `n_points` | int | 200 | 10 to 5000 | samples | Samples per source on the true timeline. |
| `noise_sd` | float | 1.0 | 0 to 100000.0 | value units | Standard deviation of Gaussian measurement noise for source 0. |
| `missing_rate` | float | 0.0 | 0 to 0.95 | fraction | Probability a sample is never received. |
| `outlier_rate` | float | 0.02 | 0 to 0.3 | fraction | Probability a received sample is an injected spike. |
| `outlier_magnitude` | float | 10.0 | 0 to 1000000.0 | value units | Size of an injected spike (sign random). |
| `duplicate_rate` | float | 0.0 | 0 to 0.5 | fraction | Probability a sample is delivered twice. |
| `baseline` | float | 20.0 | -1000000.0 to 1000000.0 | value units | Mean level of the underlying signal. |
| `amplitude` | float | 5.0 | 0 to 1000000.0 | value units | Amplitude of the sinusoidal component. |
| `period_points` | int | 100 | 4 to 5000 | samples | Sinusoid period. |
| `threshold_k` | float | 4.0 | 0.5 to 20 | x scale | Flag when the deviation exceeds this many robust standard deviations. |
| `window` | int | 21 | 3 to 201 | records | Rolling window length (odd values recommended). |
| `min_scale` | float | 0.1 | 0.0001 to 1000 | value units | Floor for the robust scale so flat stretches do not flag everything. |
| `deduplicate` | bool | True |  |  | Drop duplicate deliveries (by sequence number) before detecting. |

**Metrics**

| Metric | Unit | Meaning |
|---|---|---|
| `records_evaluated` | records | Records the detector saw (source 0). |
| `records_missing` | records | Samples never delivered (all sources). |
| `anomalies_injected` | records | Ground-truth injected spikes among evaluated records. |
| `true_positives` | records | Injected spikes that were flagged. |
| `false_positives` | records | Normal records that were flagged. |
| `false_negatives` | records | Injected spikes that were missed. |
| `true_negatives` | records | Normal records not flagged. |
| `precision` | fraction | TP/(TP+FP); undefined if nothing was flagged. |
| `recall` | fraction | TP/(TP+FN); undefined if no anomalies were injected. |
| `f1` | fraction | Harmonic mean of precision and recall; undefined if either is. |
| `flagged_fraction` | fraction | Share of evaluated records flagged. |

**Assumptions**

- Anomalies are isolated symmetric spikes of fixed size.
- Noise is Gaussian and independent between samples.
- The underlying signal is a smooth sinusoid, so a rolling median tracks it.

**Limitations**

- Scores describe this detector on this synthetic model only; they do not predict performance on real sensor data.
- Real anomalies are rarely isolated fixed-size spikes.

### `source_availability` v1.0.0 - Source availability and data freshness

Simulates several sources that each emit periodic updates, fail and recover (two-state Markov outages) and deliver with delay; reports delivery and data-age statistics against a freshness requirement.

| Parameter | Type | Default | Range / choices | Unit | Meaning |
|---|---|---|---|---|---|
| `n_sources` | int | 3 | 1 to 10 | sources | Simulated sources. |
| `duration_hours` | float | 24.0 | 0.1 to 168 | h | Simulated duration. |
| `update_interval_s` | float | 60.0 | 10 to 3600 | s | Seconds between expected updates. |
| `failure_rate_per_hour` | float | 0.2 | 0 to 60 | 1/h | Mean outage starts per source-hour while up. |
| `mean_outage_minutes` | float | 15.0 | 0.5 to 1440 | min | Mean outage duration. |
| `mean_delay_s` | float | 5.0 | 0 to 3600 | s | Mean exponential delivery delay. |
| `freshness_threshold_s` | float | 180.0 | 1 to 86400 | s | A source is 'fresh' when its newest data is at most this old. |

**Metrics**

| Metric | Unit | Meaning |
|---|---|---|
| `updates_expected` | updates | Updates scheduled across sources. |
| `updates_received` | updates | Updates delivered. |
| `received_fraction` | fraction | Received / expected. |
| `outage_count` | outages | Outages started across sources. |
| `longest_outage_s` | s | Longest single outage. |
| `mean_delay_s` | s | Mean delivery delay of received updates. |
| `mean_age_s` | s | Mean age of the newest data per source, sampled each minute. |
| `p95_age_s` | s | 95th percentile of that age (empirical). |
| `mean_fraction_sources_fresh` | fraction | Average share of sources meeting the freshness threshold. |
| `fraction_time_any_source_fresh` | fraction | Share of minutes with at least one fresh source. |

**Assumptions**

- Outages are memoryless (exponential up/down durations) and independent between sources.
- Delivery delay is exponential and independent of outages.
- Sources are identical in their failure behaviour.

**Limitations**

- Real outages are correlated (shared networks, power, weather); independence here usually understates simultaneous loss.
- Results describe this model, not any actual deployment.

### `duplicate_out_of_order` v1.0.0 - Duplicate and out-of-order input effects

Compares naive arrival-order processing with duplicate removal plus a bounded reorder buffer, reporting record counts, ordering violations and spurious coincident-event pairs.

| Parameter | Type | Default | Range / choices | Unit | Meaning |
|---|---|---|---|---|---|
| `n_points` | int | 200 | 10 to 5000 | samples | Samples per source on the true timeline. |
| `n_sources` | int | 1 | 1 to 5 | sources | Number of simulated sources measuring the same underlying signal. |
| `duplicate_rate` | float | 0.0 | 0 to 0.5 | fraction | Probability a sample is delivered twice. |
| `out_of_order_rate` | float | 0.0 | 0 to 0.5 | fraction | Probability a sample is held back so it arrives after later samples. |
| `mean_delay_seconds` | float | 0.0 | 0 to 86400 | s | Mean of the exponential delivery delay. |
| `timestamp_skew_seconds` | float | 0.0 | -3600 to 3600 | s | Constant error in the reported timestamps of the last source. |
| `missing_rate` | float | 0.0 | 0 to 0.95 | fraction | Probability a sample is never received. |
| `interval_seconds` | float | 60.0 | 1 to 3600 | s | True time between samples. |
| `reorder_buffer_s` | float | 300.0 | 0 to 86400 | s | Records arriving later than this after their event time bypass the reorder buffer and are dropped. |
| `correlation_window_s` | float | 60.0 | 1 to 3600 | s | Two records within this event-time gap count as a coincident pair. |

**Metrics**

| Metric | Unit | Meaning |
|---|---|---|
| `records_received` | records | Records delivered (including duplicates). |
| `unique_events_delivered` | records | Distinct (source, sequence) records delivered. |
| `duplicates_delivered` | records | Duplicate deliveries injected. |
| `out_of_order_records_naive` | records | Records whose event time is earlier than an already-seen record of the same source. |
| `out_of_order_fraction_naive` | fraction | That count / records received. |
| `late_beyond_buffer` | records | Records dropped by the bounded buffer as too late. |
| `duplicates_removed` | records | Duplicates removed by cleaning. |
| `records_after_cleaning` | records | Records remaining after cleaning. |
| `naive_event_count_error` | records | Received minus unique delivered (overcount from duplicates). |
| `naive_correlated_pairs` | pairs | Coincident pairs counted on raw arrivals. |
| `cleaned_correlated_pairs` | pairs | Coincident pairs after cleaning. |
| `spurious_pairs_from_duplicates` | pairs | Pairs created only by duplicate deliveries. |
| `events_lost_to_late_arrival` | records | Unique events lost because they arrived beyond the buffer. |

**Assumptions**

- Duplicates are exact copies delivered up to 30 s later.
- Skewed timestamps affect only the last source and are not corrected by cleaning.
- Lateness is judged by arrival minus reported event time.

**Limitations**

- Counts coincident pairs only; it does not run the platform's correlation rules.
- Synthetic data; see generator limitations.



**Generator parameters**

| Parameter | Type | Default | Range | Unit | Meaning |
|---|---|---|---|---|---|
| `n_points` | int | 200 | 10 to 5000 | samples | Samples per source on the true timeline. |
| `n_sources` | int | 1 | 1 to 5 | sources | Number of simulated sources measuring the same underlying signal. |
| `interval_seconds` | float | 60.0 | 1 to 3600 | s | True time between samples. |
| `baseline` | float | 20.0 | -1000000.0 to 1000000.0 | value units | Mean level of the underlying signal. |
| `amplitude` | float | 5.0 | 0 to 1000000.0 | value units | Amplitude of the sinusoidal component. |
| `period_points` | int | 100 | 4 to 5000 | samples | Sinusoid period. |
| `drift_per_point` | float | 0.0 | -10 to 10 | value units/sample | Linear drift added per sample. |
| `noise_sd` | float | 1.0 | 0 to 100000.0 | value units | Standard deviation of Gaussian measurement noise for source 0. |
| `source_noise_spread` | float | 0.0 | 0 to 5 |  | Source i has noise_sd*(1+spread*i): lower-reliability later sources. |
| `source_bias_spread` | float | 0.0 | 0 to 10000.0 | value units | Source i adds a constant bias of spread*i (conflicting sources). |
| `missing_rate` | float | 0.0 | 0 to 0.95 | fraction | Probability a sample is never received. |
| `mean_delay_seconds` | float | 0.0 | 0 to 86400 | s | Mean of the exponential delivery delay. |
| `outlier_rate` | float | 0.02 | 0 to 0.3 | fraction | Probability a received sample is an injected spike. |
| `outlier_magnitude` | float | 10.0 | 0 to 1000000.0 | value units | Size of an injected spike (sign random). |
| `duplicate_rate` | float | 0.0 | 0 to 0.5 | fraction | Probability a sample is delivered twice. |
| `out_of_order_rate` | float | 0.0 | 0 to 0.5 | fraction | Probability a sample is held back so it arrives after later samples. |
| `timestamp_skew_seconds` | float | 0.0 | -3600 to 3600 | s | Constant error in the reported timestamps of the last source. |
| `incomplete_metadata_rate` | float | 0.0 | 0 to 1 | fraction | Probability a record is missing its unit/sensor_type metadata. |

## Known gaps and future improvements

* No simulator for model-evaluation comparisons or assessment-parameter changes, no sensor-quality degradation/recovery state model.
* No cancellation, queue or background worker; a long run holds one request open (bounded by the time budget).
* No OS-level CPU/memory isolation; limits are logical (counts, sizes, time checks inside loops).
* Idempotency-key races: two simultaneous requests with the same key may yield a 409 for one of them instead of a replay.
* Rate limiting is not applied to scenario endpoints beyond the run guard and caps above.
* Exports are generated on request and returned in the response; nothing is written to the server filesystem.
* The frontend was type-checked, linted and built, but not exercised in a browser.
