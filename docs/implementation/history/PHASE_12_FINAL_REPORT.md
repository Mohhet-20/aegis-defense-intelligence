# Phase 12 Final Report: Intelligence Copilot, Retrieval, Citations

All results below were observed in the build sandbox. Library versions there differ from the pins in `requirements.txt`.

## 1. Existing components reused

* Auth/RBAC (`Permission`, `ROLE_PERMISSIONS`, `require_permission`, `has_permission`, `AuthenticatedUser`), organization scoping, audit service, error shape and global `HTTPException` handler.
* `investigation_service.get_accessible` / `user_can_access` (restricted investigations), `evidence_registry_service.evidence_visible` (restricted evidence).
* `investigation_links_service.effective_records` (what is "in" an investigation), `investigation_timeline_service.build_entries`/`sort_entries`, `investigation_search_service.relationships` (recorded `contradicts` relationships), `investigation_notes` model/API (draft reports are saved as ordinary notes).
* `EvidenceRelationship`, `AssessmentEvidenceLink` (conflict sources), `timeutil`, `workspace_errors`, pagination primitives, the Phase 11 frontend primitives (`Card`, `Tabs`, `Pagination`, `LoadState`, `useLoad`, ...), `httpx` (already pinned).
* No existing search index, embedding library, LLM client or background-job runner existed, so none was reused.

## 2. Files and migration

Migration: `alembic/versions/96f00457bcd4_phase12_retrieval_index_and_copilot_.py` (5 new tables: `retrieval_documents`, `retrieval_chunks`, `retrieval_index_runs`, `copilot_conversations`, `copilot_messages`; no existing table altered). Tested upgrade -> downgrade -> upgrade on SQLite; `alembic check` reports no drift.

Backend, new: `app/retrieval/{__init__,text,lexical,metrics,providers}.py`, `app/models/retrieval.py`, `app/services/{retrieval_sources,retrieval_index_service,retrieval_search_service,retrieval_citation_service,copilot_service,copilot_conversation_service,retrieval_eval_service}.py`, `app/schemas/copilot.py`, `app/api/routes/copilot.py`, `tests/test_copilot_retrieval.py`.
Backend, modified: `app/core/config.py` (settings), `app/core/security.py` (3 permissions), `app/models/__init__.py`, `app/main.py` (router registration; the HTTPException handler now forwards exception headers so `Retry-After` reaches clients), `.env.example`.
Frontend, new: `types/copilot.ts`, `api/copilot.ts`, `components/copilot/CopilotBits.tsx`, `components/investigations/CopilotTab.tsx`, `pages/CopilotPage.tsx`. Modified: `api/client.ts` (exports `request`), `App.tsx` (route `/copilot`), `components/layout/AppShell.tsx` (nav), `pages/InvestigationDetailPage.tsx` ("Copilot" tab).
Docs: `docs/architecture/RETRIEVAL_COPILOT.md`, `docs/security/COPILOT_PRIVACY.md`, `docs/api/RETRIEVAL_COPILOT_API.md`, this report; updated `../PROJECT_STATUS.md`, `../MASTER_ROADMAP.md`, `README.md`, `STATUS.md`.

## 3. Search methods actually implemented

* Keyword search: SQL prefilter (organization, record types the role may read, filters, `LIKE` on up to 8 terms, 2000-candidate cap) followed by Okapi BM25 in Python, best chunk per record, pagination, live per-record authorization. Portable (no FTS5), so it also runs on Postgres.
* Metadata filters: record type, investigation scope, source, review/processing status, record-time range, document version.
* **Not implemented: semantic/embedding search and hybrid retrieval.** The API says so (`semantic_search.available=false`); there is no fake mode.

## 4. Provider integrations actually configured

**None.** `COPILOT_PROVIDER=none`, `EMBEDDING_PROVIDER=none`, `COPILOT_ALLOW_EXTERNAL=false` by default, and this environment has no key. Code exists for an optional Anthropic Messages API adapter (env-only credentials, timeout, bounded retries, strict JSON schema, secret-safe errors) and for an injectable provider; both were exercised **only with a fake provider and `httpx.MockTransport`**, never a live service. Generative answers are therefore unverified against any real model.

## 5. API and frontend functionality

Backend (13 handlers): capabilities; search; document/chunk detail; index trigger; index status; purge; synthetic evaluation; ask (6 tasks); citation verify; conversation create/list/get/delete. Audit events, Pydantic validation (unknown fields rejected, bounded sizes), per-user in-process rate limit with `Retry-After`, predictable 404/422/429.
Frontend: `/copilot` page with Ask (conversation thread, capability/provider-unavailable banners, rate-limit and failure states), Search (filters, excerpts, metadata, record links, selection), Compare (side-by-side excerpts, unresolved conflicts shown distinctly, related records), Conversations (reopen with citation re-check, delete with confirmation), Index & evaluation (admin/analyst). Investigation "Copilot" tab: scoped search, summarize, chronology, compare selected, ask, editable report draft (download Markdown or save as an analyst note). All data comes from the real endpoints; claims are labelled source text / record summary / model-written / notice.

## 6. Tests actually run

* Backend full suite: **919 passed, 0 failed** (873 prior + 46 new in `tests/test_copilot_retrieval.py`).
* New tests cover: idempotent indexing and versioning; refresh of changed records; deletion -> invalidation -> tombstone purge; metadata-only media; text extraction/chunking/metrics units; search ranking, excerpts, links, filters, pagination, validation (empty/oversized/invalid filters); cross-organization exclusion of search, direct ids, copilot and index status; restricted evidence hidden from viewers; **revoked investigation membership blocks search, document detail, scoped search and summaries without re-indexing**; role permissions; extractive answers whose citations independently verify; unanswerable questions yield limitation notices; malicious instructions in records stay inert (delimiter stripping, system/user separation, no privilege change); generative-path validation with a fake provider (unknown ids, uncited and weakly supported claims); six provider-failure/malformed-output variants never fabricate; adapter retry/timeout/no-secret-leak behaviour with a mock transport; citation statuses (verified, source_changed, unavailable, access_revoked, unverified); saved conversations withhold revoked content, are private even from administrators, delete hard, are never indexed; retention purge; summary/chronology/compare/report/related tasks incl. conflicts shown unresolved and hidden when a side is unreadable; audit rows contain no question text or secrets; 429 behaviour; evaluation endpoint.
* Frontend (in a copy at `$HOME/fe_build`): `tsc --noEmit` clean; `eslint` 0 errors (the same 2 pre-existing warnings); `vite build` succeeds.
* **Not run:** any live LLM/embedding call; any browser/UI interaction test (the new screens were type-checked and built but never rendered in a browser); Postgres; load/performance tests.

## 7. Known limitations

* Keyword-only; no stemming/synonyms/phrase search; OR semantics with ranking; BM25 statistics are organization-wide approximations; >2000 candidate chunks per query are truncated (flagged).
* Indexing is manual and synchronous. There is no change-triggered refresh, no background worker, and no scheduled purge; stale documents are flagged but not auto-refreshed. A deleted record is hidden immediately (live check) but its tombstone persists until purge.
* No OCR/transcription; media is metadata-only; `extract_text` is not yet wired to any uploaded-document source.
* The copilot cannot discover contradictions nobody recorded; it reports `contradicts` relationships and contradicting assessment links as recorded.
* Generated-claim support check is lexical overlap only; it is not entailment checking.
* Rate limiting is per-process memory (not shared across workers; reset on restart).
* Stored conversation answers contain record excerpts as of answer time and persist until deleted/purged.
* Evaluation numbers are from 9 synthetic documents / 7 queries and only regression-test the code.
* `record_type`-specific detail pages do not exist for observations, evidence and media; their citation links go to the nearest list page.

## 8. Recommended Phase 13

Build on the retrieval/citation services rather than adding a second search path: (a) add change-triggered/background indexing with a job record and a scheduled purge, (b) wire uploaded text documents (`extract_text`) into a real document record type, (c) add an embedding adapter behind the existing interface only if a vetted dependency/provider is chosen, with hybrid ranking evaluated on labelled non-synthetic data, (d) add browser-level tests for the copilot screens, and (e) move rate limiting to shared storage if multiple workers are deployed.
