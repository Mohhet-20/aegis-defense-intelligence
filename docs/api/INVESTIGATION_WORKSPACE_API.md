# Investigation Workspace API

Base `/api/v1`. All routes are organization-scoped; a record from another organization or a restricted investigation
the caller cannot see returns 404. Errors use `{detail, request_id}`; conflicts (invalid transition, stale note version,
duplicate link) are 409; validation is 422.

Permissions: read = `investigation:read`; write = `investigation:manage` (evidence registration also needs
`evidence:manage`); integrity verify / evidence review / supersede = `evidence:manage`; export = `investigation:export`
(administrator, analyst, investigator; not viewer). Viewers can read everything they are allowed to see.

| Method | Path | Notes |
|---|---|---|
| GET | `/investigations` | filters `status`, `priority`, `q`, `tag`, `assigned_user_id`, `reviewer_user_id`, `include_archived`, `sort_by` (created_at, updated_at, title, priority, status), `sort_dir`; `page`/`page_size` (bounded). Archived hidden unless asked. |
| POST / GET / PATCH | `/investigations`, `/investigations/{id}` | PATCH status goes through the transition rules |
| POST | `/investigations/{id}/transition` `{to_status, reason}`; `/close`; `/archive` | 409 on invalid transition; closing needs a reason |
| GET | `/investigations/{id}/status-history` | append-only |
| GET/POST/DELETE | `/investigations/{id}/members[/{user_id}]` | roles `reviewer`, `member` |
| GET/POST/DELETE | `/investigations/{id}/links[/{link_id}]` | `record_type` in event, observation, assessment, data_source, sensor, media_asset, evidence, detection_result, track |
| GET/POST | `/investigations/{id}/evidence` | POST registers or reuses evidence and links it |
| GET | `/evidence/{id}/provenance`, `/evidence/{id}/integrity-checks` | |
| POST | `/evidence/{id}/verify-integrity`, `/review-status`, `/supersede` | |
| GET | `/investigations/{id}/timeline` | `start`, `end`, `record_type[]`, `time_kind[]`, `source_id`, `include_unknown_times`, `page`, `page_size`(<=200) |
| GET | `/investigations/{id}/search` | `q`, `record_type[]`, `source_id`, `start`, `end`, `evidence_status`, `review_status`, `data_quality`, `tag` |
| GET | `/investigations/{id}/relationships` | origin + review status; not promoted |
| GET/POST/PATCH | `/investigations/{id}/notes[/{note_id}]`, `GET .../revisions`, `GET .../note-kinds` | PATCH requires `expected_version` |
| POST | `/investigations/{id}/export` | `format=json|zip`, `include_media` (zip only) |
| GET | `/investigations/{id}/audit` | audit records for the investigation |
| GET | `/investigation-dashboard/summary` | counts by status/priority, open review questions, recent activity (respects restricted access) |

Audit actions: `investigation.create|update|transition|member_add|member_role_change|member_remove|link_add|link_remove|
note_create|note_update|export`, `evidence.register|verify_integrity|review_status_change|supersede`. Note bodies and
evidence content are not written to audit metadata.
