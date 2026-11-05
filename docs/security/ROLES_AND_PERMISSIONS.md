# Roles and permissions

_Generated from `app/core/security.py` (`ROLE_PERMISSIONS`) -- regenerate with `python scripts/gen_permission_matrix.py`. The code is authoritative; this file is a snapshot._

Four fixed roles; the role→permission table is defined in code and is **not** editable through the API. Administrator holds every permission (`set(Permission)`), so any permission added in future is automatically administrator-only until explicitly granted to another role.

| Permission | Administrator | Analyst | Investigator | Viewer |
|---|:-:|:-:|:-:|:-:|
| `analytics:evaluate` | ✔ | ✔ |  |  |
| `analytics:read` | ✔ | ✔ | ✔ | ✔ |
| `anomaly:read` | ✔ | ✔ | ✔ | ✔ |
| `anomaly:review` | ✔ | ✔ | ✔ |  |
| `assessment:manage` | ✔ | ✔ | ✔ |  |
| `assessment:read` | ✔ | ✔ | ✔ | ✔ |
| `assessment:review` | ✔ | ✔ | ✔ |  |
| `asset:manage` | ✔ | ✔ |  |  |
| `asset:read` | ✔ | ✔ | ✔ | ✔ |
| `audit:read` | ✔ |  |  |  |
| `conflict:manage` | ✔ | ✔ | ✔ |  |
| `conflict:read` | ✔ | ✔ | ✔ | ✔ |
| `correlation:manage` | ✔ | ✔ |  |  |
| `correlation:read` | ✔ | ✔ | ✔ | ✔ |
| `data:export` | ✔ | ✔ |  |  |
| `data_quality:read` | ✔ | ✔ | ✔ | ✔ |
| `detection:review` | ✔ | ✔ | ✔ |  |
| `device:manage` | ✔ | ✔ |  |  |
| `device:read` | ✔ | ✔ | ✔ | ✔ |
| `edge_conflict:manage` | ✔ | ✔ | ✔ |  |
| `edge_conflict:read` | ✔ | ✔ | ✔ | ✔ |
| `edge_sync:manage` | ✔ | ✔ |  |  |
| `edge_sync:read` | ✔ | ✔ | ✔ | ✔ |
| `evaluation:read` | ✔ | ✔ | ✔ | ✔ |
| `evaluation:run` | ✔ | ✔ |  |  |
| `event:read` | ✔ | ✔ | ✔ | ✔ |
| `evidence:manage` | ✔ | ✔ | ✔ |  |
| `evidence:read` | ✔ | ✔ | ✔ | ✔ |
| `fleet_analytics:read` | ✔ | ✔ | ✔ | ✔ |
| `fleet_site:manage` | ✔ | ✔ |  |  |
| `fleet_site:read` | ✔ | ✔ | ✔ | ✔ |
| `fusion:read` | ✔ | ✔ | ✔ | ✔ |
| `fusion:run` | ✔ | ✔ |  |  |
| `geospatial:export` | ✔ | ✔ |  |  |
| `geospatial:manage` | ✔ | ✔ |  |  |
| `geospatial:read` | ✔ | ✔ | ✔ | ✔ |
| `graph:read` | ✔ | ✔ | ✔ | ✔ |
| `inference:read` | ✔ | ✔ | ✔ | ✔ |
| `inference:run` | ✔ | ✔ |  |  |
| `infra_alert:manage` | ✔ | ✔ |  |  |
| `infra_alert:read` | ✔ | ✔ | ✔ | ✔ |
| `ingestion:read` | ✔ | ✔ | ✔ | ✔ |
| `ingestion:run` | ✔ | ✔ |  |  |
| `investigation:export` | ✔ | ✔ | ✔ |  |
| `investigation:manage` | ✔ | ✔ | ✔ |  |
| `investigation:read` | ✔ | ✔ | ✔ | ✔ |
| `lifecycle:approve` | ✔ |  |  |  |
| `lifecycle:read` | ✔ |  |  |  |
| `lifecycle:request` | ✔ |  |  |  |
| `media:manage` | ✔ | ✔ |  |  |
| `media:read` | ✔ | ✔ | ✔ | ✔ |
| `mlops:approve` | ✔ |  |  |  |
| `mlops:monitor` | ✔ | ✔ |  |  |
| `mlops:read` | ✔ | ✔ | ✔ | ✔ |
| `mlops:register` | ✔ | ✔ |  |  |
| `mlops:review` | ✔ | ✔ |  |  |
| `mlops:run` | ✔ | ✔ |  |  |
| `model:manage` | ✔ |  |  |  |
| `model:read` | ✔ | ✔ | ✔ | ✔ |
| `observability:read` | ✔ |  |  |  |
| `observation:ingest` | ✔ | ✔ |  |  |
| `observation:read` | ✔ | ✔ | ✔ | ✔ |
| `raw_record:read` | ✔ | ✔ | ✔ |  |
| `relationship:manage` | ✔ | ✔ | ✔ |  |
| `relationship:read` | ✔ | ✔ | ✔ | ✔ |
| `report:generate` | ✔ | ✔ | ✔ |  |
| `reporting:read` | ✔ | ✔ | ✔ | ✔ |
| `retrieval:evaluate` | ✔ | ✔ |  |  |
| `retrieval:index` | ✔ | ✔ |  |  |
| `retrieval:read` | ✔ | ✔ | ✔ | ✔ |
| `risk:read` | ✔ | ✔ | ✔ | ✔ |
| `risk:review` | ✔ | ✔ | ✔ |  |
| `scenario:read` | ✔ | ✔ | ✔ | ✔ |
| `scenario:run` | ✔ | ✔ |  |  |
| `scenario:write` | ✔ | ✔ |  |  |
| `security:read` | ✔ |  |  |  |
| `sensor:manage` | ✔ | ✔ |  |  |
| `sensor:read` | ✔ | ✔ | ✔ | ✔ |
| `sensor_quality:review` | ✔ | ✔ | ✔ |  |
| `source:manage` | ✔ | ✔ |  |  |
| `source:read` | ✔ | ✔ | ✔ | ✔ |
| `track:annotate` | ✔ | ✔ | ✔ |  |
| `tracking:read` | ✔ | ✔ | ✔ | ✔ |
| `tracking:run` | ✔ | ✔ |  |  |
| `tracking_evaluation:read` | ✔ | ✔ | ✔ | ✔ |
| `tracking_evaluation:run` | ✔ | ✔ |  |  |
| `user:manage` | ✔ |  |  |  |
| `user:read` | ✔ | ✔ | ✔ | ✔ |

## Notes

* **Read / create / modify / export / admin are separate permissions** where the data warrants it: e.g. `event:read` vs `data:export`, `geospatial:read` vs `geospatial:export`, `investigation:manage` vs `investigation:export`, `media:read` vs `media:manage`, `scenario:read`/`write`/`run`.
* Added `security:read` (security-configuration report) and `lifecycle:read`/`request`/`approve`; all four are administrator-only by default.
* `audit:read` and `user:manage` are administrator-only. `user:read` is held by every role (list/get users **in the caller's organization** only).
* A permission never widens *record* access: per-record rules (organization scope, restricted investigations, retrieval re-authorization) still apply on top.
* Device endpoints do not use roles at all; they authenticate with `X-Device-Id` + `X-Device-Api-Key` (see `EDGE_DEVICE_SECURITY.md`).
