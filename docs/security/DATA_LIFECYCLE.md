# Data Lifecycle and Retention (Phase 14)

Implemented in `app/services/lifecycle_service.py`, `app/models/lifecycle.py`, routes under `/api/v1/lifecycle`.
UI: Admin > Lifecycle.

## Workflow
1. **Request** (`LIFECYCLE_REQUEST`): creates a `lifecycle_requests` row with a dry-run impact snapshot taken at request time.
2. **Review** (`LIFECYCLE_APPROVE`): approve or reject. With `LIFECYCLE_REQUIRE_SEPARATE_APPROVER=True` (default) the approver must be a different administrator than the requester.
3. **Execute**: only approved requests run. Impact is re-evaluated at execution; blockers stop it.
Statuses: `pending, approved, rejected, executed, cleanup_pending, failed, cancelled`.
A preview endpoint gives the dry run without creating a request. Every step is audited. Bulk size is capped by `LIFECYCLE_MAX_BATCH`.

## Resource semantics
| Type | Operation | Notes |
|---|---|---|
| scenario | archive only | Retrieval index entry invalidated on archive |
| scenario_run | delete | Eligible by age (`LIFECYCLE_SCENARIO_RUN_RETENTION_DAYS`) |
| synthetic_dataset | delete | Blocked while a run references it (`LIFECYCLE_SYNTHETIC_DATASET_RETENTION_DAYS`) |
| copilot_conversation | delete | `COPILOT_CONVERSATION_RETENTION_DAYS` |
| media_asset | delete if unreferenced | DB row removed and committed first, then file removed |
| evidence, investigation, assessment, event, raw_record | **protected** | Cannot be deleted via lifecycle; supersede/archive through their own workflows |
| audit_record | **protected, report-only** | `AUDIT_RETENTION_DAYS` produces an eligibility report; nothing is deleted |
| credentials | **protected** | |

No unconditional cascade exists anywhere in this workflow.

## Failure handling
- DB deletion is transactional; failure -> status `failed`, error recorded, not reported as success.
- Media: if the file cannot be removed after the DB commit, status becomes `cleanup_pending` (not `executed`); re-executing retries the file removal only.
- A file removed before a failed DB commit is avoided by ordering (DB first).

## Not covered
- Derived caches/indexes other than the scenario retrieval index are not systematically swept.
- No scheduler runs lifecycle automatically; requests are manual.
- Backups are outside this system; deleted data may persist in backups.
- Audit retention deletion is intentionally not implemented.
