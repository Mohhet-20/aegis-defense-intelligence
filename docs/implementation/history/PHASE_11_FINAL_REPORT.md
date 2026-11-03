# Phase 11 Final Report -- Investigations, Evidence Provenance, Timelines, Review

## 1. Existing components reused
`Investigation`, `Evidence`, `EvidenceRelationship`, `MediaAsset` + `app/cv/storage.py` (controlled, traversal-checked
reads), `Assessment`/`AssessmentReview`, `AuditRecord` + `audit_service`, RBAC (`require_permission`), `paginate`/`Page`,
frontend primitives (`Card`, `Tabs`, `DataTable`, `Pagination`, `StatusPill`, `ApiErrorView`...). Legacy
`linked_event_ids` / `evidence_refs` are still read as links.

## 2. Files changed
Backend new: `models/investigation_workspace.py`; services `investigation_links_service`, `evidence_registry_service`,
`investigation_timeline_service`, `investigation_notes_service`, `investigation_search_service`,
`investigation_export_service`, `workspace_errors`, `timeutil`; `schemas/investigation_workspace.py`;
`api/routes/investigation_workspace.py`; migration `6e2842cef39a`; `tests/test_investigation_workspace.py`.
Backend modified: `models/investigation.py`, `models/evidence.py`, `models/__init__.py`, `services/investigation_service.py`,
`services/evidence_service.py` (new types need a URI), `schemas/investigation.py`, `schemas/evidence.py` (additive fields),
`api/routes/investigations.py`, `core/security.py` (+`INVESTIGATION_EXPORT`), `main.py`.
Frontend new: `types/workspace.ts`, `components/investigations/*` (useLoad, InvestigationBits, OverviewTab, EvidenceTab,
EvidencePanel, TimelineTab, NotesTab, SearchTab). Modified: `api/client.ts` (`api.workspace`), `pages/InvestigationsPage.tsx`,
`pages/InvestigationDetailPage.tsx`.
Docs: new `architecture/INVESTIGATION_WORKSPACE.md`, `api/INVESTIGATION_WORKSPACE_API.md`, this report; updated
`../PROJECT_STATUS.md`, `../MASTER_ROADMAP.md`, `API_REFERENCE.md`, `README.md`.

## 3. Migration
`6e2842cef39a` (down_revision `75b9cd8a733e`): 6 tables; new columns on `investigations` and `evidence_items` (batch mode,
named FKs, server defaults). Upgrade/downgrade/upgrade verified on a scratch SQLite DB; `alembic check` clean. Not run
against PostgreSQL.

## 4. APIs and workflows
28 new route handlers (see `docs/api/INVESTIGATION_WORKSPACE_API.md`): lifecycle, members, links, evidence
register/verify/provenance/review/supersede, timeline, search, relationships, notes (+revisions), export, audit, dashboard.
UI: dashboard with filters/sort/pagination and summary tiles; detail workspace with Overview (metadata, transitions,
team, links, export, audit), Evidence (register + detail panel with provenance, integrity, annotations), Timeline explorer,
Notes & review, Search & relationships. Loading, empty, error and permission-denied states use real API responses.

## 5. Tests actually executed
* `pytest tests/test_investigation_workspace.py tests/test_investigations.py`: 42 passed.
* Full backend suite (`pytest -n 2`): **873 passed, 0 failed** in 76 s (836 prior + 37 new).
* Frontend: `tsc -b` clean; `eslint` 0 errors, 2 pre-existing warnings; `vite build` succeeded (chunk-size warning only).
* Caveat: run on library versions that differ from the pins in `requirements.txt` (pinned versions were not installable in
  the sandbox). Coverage not measured. The frontend was not exercised in a browser and has no unit tests.

New tests cover lifecycle/invalid transitions/history, restricted access and members, duplicate links and evidence reuse,
cross-org attempts (link, register, verify, provenance, timeline, export), hash recording, match/mismatch/missing-original,
no-recorded-hash honesty, provenance, supersession, timeline ordering/filters/unknown times/ties, note revisions and
409 on stale versions, review questions, search filters/pagination, relationships not promoted, export JSON/ZIP/manifest
hashes/reproducibility/omissions/size limits, audit events (no note bodies), rollback of a failed multi-record operation,
dashboard visibility, malformed identifiers.

## 6. Security checks
Org-scoped lookups at the service layer for every referenced record; cross-org and restricted-investigation access returns
404; owner/members validated against the organization; role checks on every write; export has its own permission and is
audited; media read only through the controlled storage key; export includes media only if its hash still matches;
sensitive text kept out of audit metadata; output rendered as React text (no raw HTML); bounded pagination and size limits.

## 7. Remaining gaps
No retention/deletion workflow; no browser test of the UI and no frontend unit tests; no PostgreSQL run; the timeline/search
are in-memory per request (capped at 5000 entries); exports are unsigned; media capture time is not recorded by the
platform; a reviewer sign-off workflow beyond evidence status and review questions is not built; the older
`PATCH /evidence/{id}` can still edit text evidence (later integrity checks then report a mismatch -- by design, supersede is
the clean path); a list-page search over all investigations' notes is not provided.

## 8. Recommended Phase 12
Phase 12, Intelligence Copilot and Retrieval: retrieve over investigation records only through
`investigation_service.get_accessible` and `evidence_visible`, cite record ids, label model-generated text, never write
to evidence, and add a retention policy task alongside.
