# Retrieval and Copilot API

Base path `/api/v1`. All endpoints require authentication, enforce organization isolation, validate input with Pydantic
(unknown body fields are rejected), and return the platform error shape `{detail, request_id}`. Unauthorized, other-organization and
missing records all return **404**. Per-user rate limiting (`COPILOT_RATE_LIMIT_PER_MINUTE`) returns **429** with `Retry-After`.

## Permissions

| Permission | administrator | analyst | investigator | viewer |
|---|---|---|---|---|
| `retrieval:read` (search, documents, ask, citations, own conversations) | yes | yes | yes | yes |
| `retrieval:index` (index, status, purge) | yes | yes | no | no |
| `retrieval:evaluate` | yes | yes | no | no |

`retrieval:read` never widens access: each result is additionally filtered by the record's own read permission and record-level rules.

## Endpoints

| Method / path | Permission | Notes |
|---|---|---|
| `GET /retrieval/capabilities` | read | keyword/semantic/generation availability + reasons, allowed record types, limits, `can_index`, `can_evaluate` |
| `GET /retrieval/search` | read | `q` (<=500 effective chars; 422 if empty), repeated `record_type`, `investigation_id`, `source_id`, `review_status`, `time_from`, `time_to`, `document_version`, `page`, `page_size` (<=50). Returns hits with excerpt, matched terms, BM25 `score`, version, `stale`, `content_available`, `link`, plus `method` (states semantic=false and that scores are not probabilities) |
| `GET /retrieval/documents/{record_type}/{record_id}` | read | indexed document with chunks and offsets; 404 if not visible |
| `POST /retrieval/index` | index | body `{record_types?, investigation_id?}`; synchronous, bounded; returns run counts/errors |
| `GET /retrieval/index/status` | index | counts by status/type, chunk count, stale documents, last run, recent errors |
| `POST /retrieval/index/purge` | index | removes expired tombstones and conversations past retention |
| `POST /retrieval/evaluate` | evaluate | synthetic-fixture metrics (see RETRIEVAL_COPILOT.md) |
| `POST /copilot/ask` | read | body `{task, question?, investigation_id?, record_types?, record_refs?, conversation_id?, save=true, title?, report_title?}`; returns `{answer, conversation_id, message_id}` |
| `POST /copilot/citations/verify` | read | 1-50 citations; returns each with a current `status` (revoked/unavailable citations carry no title, quote or link) |
| `POST/GET /copilot/conversations`, `GET/DELETE /copilot/conversations/{id}` | read | owner only; GET re-verifies citations against current access; DELETE is a hard delete (204) |

### Task requirements

`question` needs `question` (<=2000 chars). `summarize_investigation`, `chronology`, `report_draft` need `investigation_id` (404 if the
caller cannot access it). `compare` needs 2-6 distinct `record_refs`. `related` needs exactly one.

### Answer shape

`{task, mode: extractive|generative|deterministic, status, generation:{available,provider,reason,notice}, claims[{id,text,kind,citation_ids,support,support_ratio}], citations[...], uncertainty[], missing_information[], conflicts[{description,left_citation_ids,right_citation_ids,basis,resolved}], followups[], records_used[], retrieval{...}, generated_at}` plus task extras (`side_by_side`, `differences`, `shared_terms`, `draft_markdown`).

Provider failure never yields a fabricated answer: the response is the extractive answer with `generation.notice` explaining the failure.
