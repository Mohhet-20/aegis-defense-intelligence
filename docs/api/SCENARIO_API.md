# Scenario Simulation API

Base path `/api/v1`. All endpoints require authentication, enforce organization isolation, validate input with Pydantic
(unknown body fields are rejected with 422) and return the platform error shape `{detail, request_id}`.
Other-organization, missing, and unauthorized (restricted-investigation) records all return **404** with the same message.
Every scenario, run, dataset, comparison and export carries `synthetic: true` and a `label` stating that it is SIMULATED.

## Permissions

| Permission | administrator | analyst | investigator | viewer |
|---|---|---|---|---|
| `scenario:read` (discovery, list/get, runs, run detail, versions, compare, datasets, export) | yes | yes | yes | yes |
| `scenario:write` (create, validate, edit draft, ready, duplicate, archive, generate datasets) | yes | yes | no | no |
| `scenario:run` (run, sensitivity, retry) | yes | yes | no | no |

`scenario:read` never widens access: a scenario linked to a restricted investigation is visible only to people who can access that investigation.

## Endpoints

| Method / path | Permission | Notes |
|---|---|---|
| `GET /simulation/simulators` | read | registered simulators with parameter docs (type, range, default, unit, description), metric docs with units, assumptions, limitations, generator parameters, global limits, and a `not_implemented` list |
| `GET /simulation/templates` | read | hard-coded templates (data only) |
| `POST /scenarios/validate` | write | `{simulator_id, params, execution_config}` -> `{valid, errors[{param,message}], params, assumptions, limitations}`; persists nothing |
| `POST /scenarios` | write | 201. `{title, template_id? or simulator_id, params, assumptions, limitations, seed, execution_config, question, description, category, investigation_id}`. Template parameters are the base and `params` override. 422 on any invalid value; 404 if the investigation is not accessible; 409 at the organization limit |
| `GET /scenarios` | read | filters `status`, `category`, `simulator_id`, `q` (title), `investigation_id`, `latest_only`; `page`, `page_size` <= 100 |
| `GET /scenarios/{id}` | read | |
| `PATCH /scenarios/{id}` | write | draft only (409 otherwise); params are merged then re-validated |
| `POST /scenarios/{id}/ready` | write | draft -> ready; 422 if no assumption has been recorded |
| `POST /scenarios/{id}/duplicate` | write | 201. New draft `version = max + 1` in the same lineage; optional `title`, `description`, `params` overrides, `seed` |
| `POST /scenarios/{id}/archive` | write | |
| `GET /scenarios/{id}/versions` | read | all versions in the lineage, ascending |
| `GET /scenarios/{id}/runs` | read | summaries only (no results/snapshot); filters `status`, `kind`; newest first |
| `POST /scenarios/{id}/runs` | run | 201 `RunDetail`. Body `{seed?}`. Optional `Idempotency-Key` header (<= 100 chars): a repeat returns **200** with the original run and `idempotent_replay: true`. 409 if the scenario is not ready, a run is in progress, or the history cap is reached |
| `POST /scenarios/{id}/sensitivity` | run | 201 `RunDetail` with `run_kind: sensitivity`. Body `{sweep:[{param, values? or min,max,steps}], repetitions, metric, seed?}`. The plan is validated before any run row is created (422, no row) |
| `GET /scenario-runs/{run_id}` | read | full run: config snapshot, dataset reference, results, hash, timings, error |
| `POST /scenario-runs/{run_id}/retry` | run | only for `failed` runs (409 otherwise); creates a **new** run with `retry_of_run_id`; the failed run is untouched |
| `POST /scenario-comparisons` | read | `{baseline_run_id, alternative_run_ids[1..3]}`; completed *simulation* runs only (sensitivity runs and unfinished runs -> 422) |
| `GET /scenarios/{id}/export?format=json\|markdown` | read | attachment named `scenario-<id>.json\|md`; header `X-AEGIS-Synthetic: true`; other formats -> 422 |
| `POST /synthetic-datasets` | write | 201. `{name, params, seed}`; size guards -> 422; 409 at the organization limit |
| `GET /synthetic-datasets` | read | summaries |
| `GET /synthetic-datasets/{id}?limit=` | read | header + first `limit` (<= 500) records, every record `synthetic: true` |

## Run detail shape

`{id, scenario_id, scenario_version, run_kind, status, simulator_id, simulator_version, seed, config_snapshot, dataset_ref, results, result_sha256, error_code, error_message, retry_of_run_id, started_at, completed_at, runtime_ms, idempotency_key, requested_by_user_id, idempotent_replay, synthetic, label}`

* `status` is `completed` only when the simulator returned normally and the result passed size limits. Otherwise `failed` with a
  safe `error_code` (`invalid_parameters`, `numerical_error`, `resource_limit`, `stale_run`, `internal_error`, ...) and `results: null`.
* `runtime_ms` is a measured monotonic-clock duration, `null` only while a run has not finished.
* `results` (simulation): `{label, synthetic, metrics, preview (<= 500 rows), notes, dataset_header}`; (sensitivity): see `docs/architecture/SCENARIO_SIMULATION.md`.

## Comparison shape

`{baseline, alternatives[{run_id, label, warnings, parameter_changes[{param,baseline,alternative}], held_constant[{param,value}], seed_changed, comparable, attribution{status,statement}, metrics[{name,unit,baseline,alternative,absolute_diff,relative_diff,comparable,reason}]}], assumptions, limitations, caveats, synthetic, label}`

## Audit actions

`scenario.create`, `scenario.update`, `scenario.ready`, `scenario.duplicate`, `scenario.archive`, `scenario.run` (also retries), `scenario.sensitivity`, `scenario.compare`, `scenario.export`, `dataset.generate`.
Metadata holds ids, status, counts, error code and runtime - not parameter values or result metrics.

## Retrieval integration

`record_type=scenario` is accepted by `GET /retrieval/search`, `/retrieval/index`, `/retrieval/documents/scenario/{id}` and `POST /copilot/ask` (`record_types`).
It is never part of a default search. See `docs/architecture/SCENARIO_SIMULATION.md`.
