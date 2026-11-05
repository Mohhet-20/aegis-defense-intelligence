# Simulated vs. Operational Data: Controls

| Concern | Control | Verified by |
|---|---|---|
| Synthetic data inserted as real observations | Datasets live only in `synthetic_datasets`; the generator and simulators are pure functions with no database access; no code path writes `observations`, `events`, `evidence` or `assessments` | tests compare operational table counts and assessment rows before/after generation, runs, sweeps and indexing |
| Labelling | `synthetic: true` + `label` on every scenario/run/dataset/comparison/export response; each generated record has `synthetic: true`; dataset header and run `dataset_ref` carry it; `is_synthetic` column; export banner and `X-AEGIS-Synthetic` header; `[SIMULATED]` title in the search index; persistent banner on every scenario page | API tests; frontend banner component |
| Simulations mistaken for evidence in search/copilot | `scenario` is excluded from default search and answers; opt-in by type only; answers citing a scenario add an uncertainty note; runs/datasets are never indexed | tests |
| Arbitrary code / SQL / shell | Simulators chosen by key from a hard-coded registry; parameters validated against typed specs; unknown keys, wrong types, non-finite numbers, out-of-range values rejected; `execution_config` accepts only `max_seconds`; templates are data | tests with `os.system`, `__import__`, SQL and shell strings |
| Cross-organization leakage | every query filters by the caller's organization; foreign ids return the same 404 as missing ids; comparisons, retries, exports and datasets covered | tests (14 endpoints with an outsider token) |
| Restricted investigations | scenario visibility follows investigation access; lists, details, exports, runs, retrieval and documents hide them | tests |
| Resource exhaustion | record, sweep, repetition, run-history, scenario and dataset caps; per-run and per-sweep time budgets checked inside loops; result-size cap | tests |
| Path traversal / unsafe export | exports are built in memory; the filename comes from the scenario id only; `format` is whitelisted; ids with `../` are plain not-found | tests |
| Leaking internals | unexpected exceptions are stored as `internal_error` with a generic message | test with a raising simulator |
| Auto-modifying assessments | no code path touches assessments; the copilot describes scenario content as hypothetical | tests |

## Controls that are NOT implemented

* No OS-level CPU/memory isolation or separate worker process for simulations.
* No cancellation or queueing.
* No per-user rate limit on scenario endpoints (the concurrent-run guard and caps are the only throttles).
* Stored synthetic datasets and run results are plain database JSON; there is no retention/purge job for them.
