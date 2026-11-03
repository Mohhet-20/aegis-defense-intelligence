# Phase 14 Final Report -- Security, Authorization, Tenant Isolation, Audit Governance, Privacy and Lifecycle

## 1. Initial audit findings
Route coverage: 253 permission-gated routes, 2 auth-only, 3 device-authenticated, 4 intentionally public. A cross-org GET/DELETE sweep
(5724 calls) found 0 server errors and 0 cross-org reads. Defects found: NULL-org audit rows served; sensors/evidence/devices/investigations
accepted foreign-organization referenced ids; disabled-account oracle and login timing difference; raw login identifier stored in audit;
no session revocation; no password policy/change flow; no last-admin protection; unbounded upload reads; permissive CORS and always-on docs;
client-controlled request id; python-jose advisory PYSEC-2026-4298 (no fix).

## 2. Files and migrations changed
Migration `a14c0de5ec01` (revises `980f1f55cbaa`, single head): `users.token_version`, `users.password_changed_at`, `lifecycle_requests`,
audit update/delete triggers (SQLite executed; Postgres SQL not executed). New backend modules: `core/passwords.py`, `core/security_config.py`,
`core/tenancy.py`, `core/uploads.py`, `middleware/hardening.py`, `models/lifecycle.py`, `services/lifecycle_service.py`, `schemas/lifecycle.py`,
routes `lifecycle.py`, `security_admin.py`; modified config, security, user/audit services, auth/users/audit/media/ingestion/sensor/evidence/
edge/investigation/geospatial routes, `main.py`, connectors url_safety, `seed.py`, `requirements.txt` (PyJWT 2.15.0 replaces python-jose).
Scripts: `security_checks.py`, `gen_permission_matrix.py`. Tests: `test_security_p14_{auth,tenancy,governance}.py`. Frontend: governance types/API,
Access, Lifecycle, Security config pages, rewritten Audit Explorer, routes/nav. Docs: 10 files in `docs/security/`, status/roadmap/README/.env.example.

## 3. Authorization and isolation
Denied-access auditing (`authz.denied`), new permissions (security read, lifecycle read/request/approve), foreign-reference rejection on create/update
(404 for foreign, dangling legacy ids tolerated), org-only audit queries, per-user session revocation after password change/reset/role change/disable,
password policy, last-admin and self-lockout protection, constant-time-ish unknown-user login, media re-authorization and hash check.

## 4. Audit and lifecycle
Audit filters/detail/actions endpoints, metadata redaction, ORM immutability guard + DB triggers (not tamper-proof; DBAs can alter), user create/update
audited in the same transaction (fail-closed). Lifecycle request -> separate-approver approval -> execute with dry-run; protected types; media file
cleanup with `cleanup_pending`; audit retention report-only.

## 5. Checks and tests executed
Full backend suite: **1152 passed** (87 s, `-n 4`; baseline at Phase 13 was 1052). Migration upgrade/downgrade/upgrade on SQLite OK.
`security_checks.py`: pip-audit (direct pins) 0 vulnerable; bandit 2 medium B608 (reviewed false positives); detect-secrets 13 candidates (reviewed);
`npm audit --omit=dev` 2 moderate; container scan skipped. Frontend `tsc -b`, eslint (0 errors, 2 pre-existing warnings) and `vite build` passed in a
copy of the frontend earlier in this session; they were not re-run after the final doc-only edits. No browser click-through was performed.
Environment caveat: tests ran on SQLAlchemy 2.0.54 rather than the pinned 2.1.4.

## 6. Unresolved
See `docs/security/KNOWN_RISKS.md`: no refresh rotation/MFA; tokens in JS storage; no RLS/composite tenant FKs; audit not tamper-proof; Postgres
triggers unexecuted; other services still commit before auditing; global model registry; no encryption at rest; dev-tooling npm vulnerabilities;
transitive Python deps and containers not scanned.

## 7. Remaining operational steps
Set a strong `SECRET_KEY` and explicit CORS before production start; configure TLS/proxy and `TRUST_FORWARDED_HEADERS` appropriately; replace compose
dev credentials; run migration on Postgres and verify triggers; schedule lifecycle review; run scanners in CI with a container scan.

## 8. Recommended Phase 15
Close the top KNOWN_RISKS items: refresh-token rotation (and optional MFA), Postgres validation with composite tenant constraints/RLS, audit hash chaining
or external shipping, finishing audit-before-commit ordering across remaining services, and CI-integrated container/dependency scanning.
