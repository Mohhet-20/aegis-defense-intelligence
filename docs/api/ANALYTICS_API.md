# Analytics API - base `/api/v1`

| Method & path | Permission | Notes |
|---|---|---|
| `GET /model-outputs?output_type=detection_result\|risk_assessment&model_record_id&page&page_size` | analytics:read | Paged; `skipped_invalid` counts rows failing the schema |
| `GET /model-outputs/{type}/{id}` | analytics:read | Shared `ModelOutput` schema; 404 cross-org, 422 invalid stored record |
| `GET /model-outputs/{type}/{id}/explanation?method=` | analytics:read | `supported:false` + `limitation` when no faithful method applies; 422 unknown method |
| `POST /model-evaluations` | analytics:evaluate | Body: model_record_id, dataset_name/version, **is_synthetic**, samples, optional labels/positive_label/model_version. 201; 404 unknown model; 422 bad input / version mismatch; 500 + recorded `failed` run on internal error |
| `GET /model-evaluations` | analytics:read | Unified list: classification + detection + tracking runs |
| `GET /model-evaluations/{id}` | analytics:read | Includes `performance_claim`, definitions, warnings |
| `GET /assessment-scoring-rules` | assessment:read | Rules, defaults, bands, allowed inputs |
| `POST /assessments/{id}/score` | assessment:review | Body: rule_key, config_overrides. Appends a snapshot |
| `GET /assessments/{id}/scores` | assessment:read | Newest first |
| `POST /assessments/{id}/reviews` | assessment:review | decision, notes, change_reason, information_flags, score_snapshot_id |
| `GET /assessments/{id}/reviews` | assessment:read | Status, latest review/score, comparison, full history |

All routes are organization-scoped (cross-org returns 404). Interactive docs:
`/api/docs`.
