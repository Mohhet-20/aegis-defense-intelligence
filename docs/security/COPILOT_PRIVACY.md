# Copilot: Provider Configuration, Privacy and External Processing

## Default posture

Out of the box (`COPILOT_PROVIDER=none`, `COPILOT_ALLOW_EXTERNAL=false`) **no data leaves the deployment** and no language model
is called. Search, extractive answers, summaries, chronologies, comparisons and report drafts all work locally. The API and UI state
plainly that generative answers are unavailable and why.

## Configuration (environment only)

| Variable | Default | Purpose |
|---|---|---|
| `COPILOT_PROVIDER` | `none` | `none` or `anthropic` |
| `COPILOT_ALLOW_EXTERNAL` | `false` | Must be `true` for any external call |
| `COPILOT_API_KEY` | empty | Credential; environment only, never stored in the database, never returned by any endpoint, never logged |
| `COPILOT_MODEL` | empty | Required for `anthropic` |
| `COPILOT_BASE_URL` | `https://api.anthropic.com` | Messages API endpoint |
| `COPILOT_TIMEOUT_SECONDS` / `COPILOT_MAX_RETRIES` | 20 / 1 | Per-call timeout; bounded retries (<=3) on timeouts, 408/429/5xx/529 only |
| `COPILOT_MAX_OUTPUT_TOKENS`, `COPILOT_CONTEXT_CHUNKS` | 1200 / 8 | Output and context bounds |
| `COPILOT_MAX_QUESTION_CHARS` | 2000 | Question length cap |
| `COPILOT_RATE_LIMIT_PER_MINUTE` | 20 | Per-user, per-endpoint-group limit (in-process) |
| `COPILOT_CONVERSATION_RETENTION_DAYS` | 90 | Idle conversations older than this are removed by the purge endpoint |
| `EMBEDDING_PROVIDER` | `none` | No embedding provider is implemented; leave `none` |
| `RETRIEVAL_*` | see `config.py` | Chunk size, document/query/result/candidate/index bounds, tombstone days |

## What is sent when a provider is enabled

If (and only if) all of `COPILOT_PROVIDER=anthropic`, `COPILOT_ALLOW_EXTERNAL=true`, `COPILOT_API_KEY` and `COPILOT_MODEL` are set,
each **question** task sends to the configured endpoint:

* the user's question text, and
* up to `COPILOT_CONTEXT_CHUNKS` text passages (record types, record times and the passage text) from records **the requesting user is
  authorized to read**, selected by keyword retrieval.

Not sent: user identifiers, organization identifiers, credentials, conversation history, or any record the user cannot read.
Deterministic tasks (summary, chronology, compare, related, report draft) never call a provider.

The administrator enabling this is responsible for confirming that sending record text to the provider is permitted by their data
handling obligations and the provider's terms (retention, training, residency, sub-processors), none of which this software can
assess. Record excerpts may include sensitive operational information. Keep `COPILOT_ALLOW_EXTERNAL=false` if in doubt.

## Untrusted content and model output

* Retrieved text is treated as **data, never instructions**. It is placed inside delimited `SOURCE` blocks; the delimiter tokens
  are stripped from record text so a record cannot close the block; the system prompt states the rule explicitly.
* Records that contain instruction-like phrases are flagged in the response (`uncertainty`) and are otherwise inert.
* Model output is parsed only as JSON against a fixed schema (<=20 claims, bounded lengths). It is never executed, evaluated,
  or used to build SQL, shell commands, file paths, or privileged actions. The model has no tools.
* Prompt injection cannot change permissions: authorization is computed by the server from the authenticated user and the live
  record, independent of any text.
* This reduces, but cannot eliminate, the chance that a model's wording is misleading. Generated statements are labelled and
  lexically checked against their citations; users must verify against the cited record.

## Logging and audit

* Prompts, model responses, questions and API keys are **not logged**. Provider failures log only a short category (e.g. `HTTP 500`,
  `ConnectTimeout`); response bodies, which may echo a key, are never logged or surfaced.
* Audit actions: `retrieval.search`, `retrieval.document_read` (including denied), `retrieval.index_run`, `retrieval.purge`,
  `retrieval.evaluate`, `copilot.ask`, `copilot.conversation_open`, `copilot.conversation_delete`. Metadata holds lengths, counts,
  task/mode/status and record-type lists, not question or result text.

## Retention

* Retrieval index: derived data; a deleted source record invalidates its document at the next index run (chunks removed
  immediately; tombstone kept 30 days, then purged on request).
* Conversations: stored until the owner deletes them or the purge endpoint removes those idle beyond the retention window.
  Stored answers contain record excerpts as of answer time. There is no scheduler; purge is an explicit administrator action.
