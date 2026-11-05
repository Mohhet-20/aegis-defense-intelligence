# Organization (tenant) isolation

**Model:** one database, row-level `organization_id`, enforced **in application code**. There is no database-level row security, no per-tenant schema and no composite foreign key tying child rows to a parent's organization. Isolation is therefore only as strong as every query and every referenced-id check — which is why tested it exhaustively instead of assuming it.

## Rules
1. The caller's `organization_id` is read from the authenticated user's DB row. It is never accepted from a client.
2. List / search / export / retrieval queries filter by it; single-record lookups filter by it **and** return the same 404 as for a missing id.
3. **Referenced ids in write requests** (e.g. a sensor's `source_id`/`asset_id`, an evidence item's `event_id`, a device's `site_id`, an investigation's `linked_event_ids`) must belong to the caller's organization. Helpers: `require_in_org`, `require_all_in_org`, `reject_foreign_ids` in `app/core/tenancy.py`.
4. Stored files (media) are opened only through `GET /media/{id}/content`, which looks the asset up by organization first, then verifies the SHA-256 of the bytes.
5. Retrieval/citations are re-authorized against the live record at query time; a deleted or foreign record yields no result.
6. Audit rows are readable only within their organization; system-level rows (`organization_id` NULL — e.g. a login attempt for an unknown identifier) are not exposed through any API.

## What was tested
* **Brute-force read sweep:** an authenticated administrator of a second organization called every `GET`/`DELETE` route that has path parameters with real ids from the first organization (up to 4 ids per table; 5 724 requests, local seeded database). Result: **0 server errors; 0 cross-organization reads.** The only 2xx answers were the caller's own user record and the global model registry (below).
* **Write-side association probe:** body-only `POST/PATCH/PUT` routes were called with the first organization's ids. This found real defects (below).
* Regression tests: `tests/test_security_tenancy.py`.

## Defects found and fixed
| # | Defect | Fix |
|---|---|---|
| 1 | `GET /audit` returned rows with `organization_id IS NULL` to **every** organization's administrator (failed-login attempts for unknown identifiers, including whatever was typed in the username box). | Strictly org-scoped; NULL-org rows are not served. |
| 2 | `POST /sensors` / `PATCH /sensors/{id}` accepted another organization's `source_id` / `asset_id`. | Validated with `require_in_org`. |
| 3 | `POST /evidence` accepted another organization's `event_id`, `raw_record_id`, `observation_id`. | Validated. |
| 4 | `POST /devices` accepted another organization's `site_id`. | Validated. |
| 5 | Investigation create/update accepted another organization's event ids in `linked_event_ids`. | Foreign ids rejected; ids that exist nowhere are still tolerated (legacy JSON lists contain dangling ids — rejecting them would break existing data). |

## Deliberate exception
`ModelRecord` (the computer-vision model registry) has **no** `organization_id`; it is a platform-wide registry, readable by any authenticated user with `model:read`, writable only with `model:manage` (administrator). Anything that must be tenant-private must not be stored there.

## Inconsistent / legacy data
No migration rewrites organization references. If you suspect rows with a missing or mismatched `organization_id`, run a read-only check before enabling stricter constraints, e.g. for evidence → event: `SELECT e.id FROM evidence_items e JOIN events v ON v.id = e.event_id WHERE e.organization_id <> v.organization_id;`. Do not "fix" such rows by deleting them; decide per row (move, or null the reference) and audit it. DB-level composite constraints were **not** added: they require every parent table to expose `(id, organization_id)` as a unique key and a data back-fill, which is a separate migration project (see `KNOWN_RISKS.md`).
