# Retrieval and the Evidence-Grounded Copilot (Phase 12)

This document describes what is actually implemented. Nothing here claims capabilities that are not in the code.

## What exists

| Capability | Status |
|---|---|
| Derived retrieval index over existing records | Implemented |
| Keyword search (BM25) with filters, pagination, live authorization | Implemented |
| Semantic / embedding search | **Not implemented.** No embedding dependency or provider exists; the API reports `semantic_search.available=false`. No fake semantic mode. |
| Extractive, cited answers (no model) | Implemented (default) |
| Deterministic analyst tasks: investigation summary, chronology, side-by-side comparison, related records, report draft | Implemented (no model involved) |
| Model-written ("generative") answers | Adapter + schema validation implemented; **disabled by default** and no provider is configured in this repository. Tested only with an injected fake provider and an `httpx.MockTransport`. |
| Citations with live re-verification | Implemented |
| Conversations with deletion/retention | Implemented |
| Synthetic retrieval evaluation | Implemented |

## Architecture

```
records (authoritative)  ->  retrieval_sources.build_doc  ->  retrieval_index_service  ->  retrieval_documents / retrieval_chunks
                                                                                              |
user question -> retrieval_search_service (SQL prefilter -> BM25 -> LIVE authorization) <-----+
                      |
                      v
          copilot_service (extractive / deterministic; optional provider step)
                      |
                      v
        retrieval_citation_service (build + verify citations against live data)
```

Modules: `app/retrieval/{text,lexical,metrics,providers}.py` (pure), `app/models/retrieval.py`,
`app/services/{retrieval_sources,retrieval_index_service,retrieval_search_service,retrieval_citation_service,copilot_service,copilot_conversation_service,retrieval_eval_service}.py`,
`app/api/routes/copilot.py`, `app/schemas/copilot.py`.

### Indexed content types

`investigation`, `investigation_note` (latest body), `event`, `observation`, `assessment`, `assessment_review`, `evidence`
(report-type evidence is labelled `approved_report_document`), `data_source`, `media_asset`.

* Only fields already stored on the record are indexed (title, description, notes, assumptions, information gaps, review
  notes, attributes that are scalar, etc.). Nothing is generated.
* `media_asset` is **metadata only** (filename, type): there is no OCR/transcription, binary bytes are never indexed, and the
  document is stored with `status=unsupported` / `extraction_method=metadata_only`. Search results mark it `content_available=false`.
* `extract_text()` supports text/markdown/csv/json with binary detection and size limits, for future file uploads. It is not
  wired to any uploaded-file source yet (no such text-upload record type exists in the repository).
* Detection results, tracks and sensors are not indexed.

## Indexing and refresh

* One `retrieval_documents` row per (organization, record_type, record_id) (unique constraint) plus bounded `retrieval_chunks`
  (default 1200 chars, 120 overlap; character offsets into the indexed text are kept; headings become `section`).
* A `content_hash` over title/status/metadata/text makes re-indexing **idempotent**: unchanged records are a no-op; a changed
  record gets `version+1` and its chunks are replaced. Repeated runs never create duplicates.
* Empty text -> `status=empty`; extraction errors are recorded per record (`status=error`, message) and do not stop the run.
* A run is bounded by `RETRIEVAL_MAX_INDEX_RECORDS` and `RETRIEVAL_INDEX_TIMEOUT_SECONDS`; it ends `partial` if the budget is hit.
* Indexing is **explicit** (`POST /retrieval/index`, permission `retrieval:index`, synchronous). There is no background worker
  and no automatic re-index on record change. Staleness is reported by `GET /retrieval/index/status` and flagged per hit.
* Deleted records: the run marks the document `invalidated` and deletes its chunks immediately. A metadata tombstone is kept for
  `RETRIEVAL_TOMBSTONE_DAYS` (30) and then removed by `POST /retrieval/index/purge`.
* The index is a derived copy of text from records the organization already holds, stored in the same database; it adds no new
  external disclosure but means indexed text exists in a second table.

## Authorization model

Authorization is evaluated **at query time against the live record**, never from index metadata:

1. Organization isolation (every query is filtered by the caller's organization).
2. Per-type read permission (event -> `event:read`, observation, assessment/review, investigation/note, evidence/media -> `evidence:read`, data source -> `source:read`).
3. Record-level rules: restricted investigations (assigned user, member, administrator), notes follow their investigation (and their evidence's classification), restricted evidence follows `evidence_visible`.
4. A record that is deleted, in another organization, or not visible is **dropped** from results; direct-id requests return the same 404 as a missing record.

Consequences: revoking membership or restricting a record takes effect immediately without re-indexing. Counts of hidden items are never reported.

## Search and ranking

* Query is tokenized (lower-case, stopwords removed, compounds such as `harbor_photo.png` are kept whole and also split into parts),
  at most 8 distinct terms. A SQL `LIKE` prefilter over the chunk text selects up to `RETRIEVAL_MAX_CANDIDATES` (2000) candidates.
* Candidates are scored with Okapi BM25 (k1=1.5, b=0.75; N and average length from the organization's chunks; document frequency by
  per-term substring count, an approximation). Terms are OR-combined, so a record matching any term can appear; the matched terms are shown.
* One best chunk per record is returned with `matching_chunks`. Results are paginated (page size <= 50).
* Filters: record types, investigation (linked records + its notes + reviews of linked assessments), source id, review/processing
  status, record-time range (records with no recorded time never match a time filter), indexed document version.
* **Scores order results only.** They are not probabilities, not confidence, and say nothing about whether a record is true or reliable.
  The response includes this statement. If more than 2000 candidates match, results are flagged `candidates_truncated` (only the
  most recently indexed candidates are ranked).
* Known approximations: no stemming or synonyms, English stopwords only, no phrase queries, no typo tolerance.

## The copilot

Retrieval always runs first. Task types: `question`, `summarize_investigation`, `chronology`, `compare` (2-6 records), `related`, `report_draft`.

Every claim has a `kind`:

| kind | meaning |
|---|---|
| `source_statement` | verbatim text from a record (with its citation) |
| `record_summary` | assembled by the application from stored fields; no model |
| `generated_summary` | written by a language model (only when a provider is available) |
| `system_note` | a limitation or notice from the application |

Rules enforced in code: a question is "answered" only when the top results match at least half of the distinctive query terms
(otherwise the response is a limitation notice listing weak matches separately, with no claims); conflicts are listed side by side with
their recorded basis and `resolved: false`; conflicts involving a record the caller cannot read are omitted entirely; unknown
record times are shown as "not recorded"; ingestion/association times are labelled as such; nothing says a source is reliable.

Conflict sources: recorded `contradicts` relationships (not rejected) between linked events/evidence, and assessment evidence
links with role `contradicting`. The copilot does not detect new contradictions from text.

`report_draft` is **assembled from the summary and chronology**, labelled as a draft that is not model-generated, and returned as
editable Markdown. The UI lets the user edit, download, or save it as an analyst note; nothing is published automatically.

### Generative mode (optional)

When a provider is available, the model receives the question and delimited, numbered `SOURCE` blocks and must return JSON
`{claims:[{text,citation_ids}], uncertainty, followups}`. The response is validated against a strict schema; any failure (HTTP error,
timeout, malformed JSON, schema violation) falls back to the extractive answer with a visible notice. Validation flags:

* cited ids that were not retrieved -> `support=unverified` and the citation is discarded;
* claims with no citation -> `support=none` ("unsupported commentary");
* claims with little wording in common with their cited text -> `support=weak_overlap` (a lexical check, **not** proof of entailment).

Source excerpts stay in the response next to the model's claims.

## Citation format

```
{id, record_type, record_id, document_version, chunk_position, title, section, quote, source_time, link, status, status_note}
```

`quote` is a verbatim slice of the record's indexed body; `title`, `source_time` and `section` are stored values; nothing
(page numbers, locations) is invented. `link` is a frontend detail route (e.g. `/events/<id>`); following it goes through that
page's own authorization. Types without a dedicated page link to the nearest authorized list page.

Statuses: `verified`, `source_changed` (record changed; the old quote is not echoed), `unavailable` (missing/other organization),
`access_revoked` (title, quote and link withheld), `unverified` (not a retrieved source). `POST /copilot/citations/verify`
re-checks any citation against current data and permissions; opening a saved conversation does the same and withholds claim
text, conflicts, drafts and side-by-side excerpts that depended on a source the user can no longer read.

## Conversations

Per-user (others, including administrators, receive 404). Stored: question text, the structured answer, timestamps, task, mode.
Never indexed, never used as evidence or fed back into prompts. `DELETE` is a hard delete. Conversations idle longer than
`COPILOT_CONVERSATION_RETENTION_DAYS` (90) are removed by `POST /retrieval/index/purge` (there is no scheduler). Audit records
store lengths and counts, not question text.

Stored answers contain excerpts of records as they were when the question was asked. Re-opening re-verifies access, but the stored
JSON is retained until deletion/purge.

## Evaluation methodology

`POST /retrieval/evaluate` (`retrieval:evaluate`) runs the real chunker and BM25 over an in-memory **synthetic** corpus
(`synthetic_fixture_v1`: 9 documents, 7 queries, hand-written graded relevance labels, one no-answer query, two deliberately
contradicting documents, a second organization, a restricted document, an instruction-injection sample). Reported: precision@{1,3,5},
recall@{1,3,5}, nDCG@{1,3,5}, MRR; checks for no-answer limitation, contradicting sources staying distinct, other-organization and
restricted exclusion, and citations quoting existing fixture text. The output carries a disclaimer: these numbers regression-test the
code on toy data; they are not real-world accuracy and do not indicate any statement is true. The evaluation does not touch the
production index.

## Limitations and deferred work

* No semantic search; no embeddings; no reranking; no query expansion.
* No real language-model provider is configured or was exercised. The Anthropic adapter is code-complete but only tested with mocks.
* Indexing is manual and synchronous; no change-triggered refresh, background jobs or scheduled purge.
* No OCR/transcription of media; no uploaded-document text extraction pipeline wired to a source.
* Rate limiting is an in-process per-user sliding window (single process; resets on restart; not shared across workers).
* Support checks for generated claims are lexical only. The copilot cannot detect contradictions that nobody recorded.
* BM25 statistics are organization-wide approximations; very large organizations (>2000 candidate chunks per query) are truncated.
* No browser/UI automated tests; the frontend was type-checked, linted and built but not exercised in a browser.
