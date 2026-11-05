# Security Baseline — AEGIS,

What's actually implemented and verified, versus what's
planned (Security and Governance). Every claim below is
checked against the actual code in this repository, not aspirational.

## Authentication

- **IMPLEMENTED**: bcrypt password hashing (`passlib[bcrypt]`), JWT
  access tokens (30 min default expiry) and refresh tokens (7 days),
  signed with `SECRET_KEY` (HS256). `SECRET_KEY` has a `dev-only`
  placeholder default and must be overridden via environment variable
  for any non-local deployment — `.env.example` documents this.
- **IMPLEMENTED**: account lockout after `MAX_FAILED_LOGIN_ATTEMPTS`
  (default 5) failed logins, for `ACCOUNT_LOCKOUT_MINUTES` (default 15).
  A disabled (`is_active=False`) account cannot log in regardless of
  password correctness.
- **IMPLEMENTED**: rate limiting on `/auth/login` via `slowapi`
  (`RATE_LIMIT_AUTH`, default 10/minute per client IP).
- **NOT IMPLEMENTED**: token revocation before expiry (no blocklist) —
  see `ARCHITECTURE_DECISIONS.md`'s JWT trade-off note. **NOT
  IMPLEMENTED**: SSO/OIDC, MFA.

## Authorization

- **IMPLEMENTED**: every protected route depends on
  `require_permission(Permission.X)`, checked server-side against the
  authenticated user's role via `ROLE_PERMISSIONS`. Verified by tests
  that call routes directly with a token for a role that should be
  rejected, and assert a `403`, not just by inspecting the code.
- **NOT IMPLEMENTED**: per-row/tenant authorization (see
  "Tenant isolation" in `ARCHITECTURE_DECISIONS.md` — the security-governance work).

## Secret management

- **IMPLEMENTED**: `.env.example` contains placeholders only, no real
  secret. `.env` (the real, local file) is gitignored. `SECRET_KEY` is
  read from environment/`.env`, never hardcoded in a way that would
  reach source control.
- **NOT IMPLEMENTED**: an external secrets manager (Vault/KMS) — not
  justified at this layer's single-instance, local-dev-by-default
  scope.

## Input validation

- **IMPLEMENTED**: every API request body is a typed Pydantic schema;
  FastAPI rejects malformed JSON/missing required fields with a `422`
  before a route handler runs. Coordinate ranges, enum values, and
  string lengths are validated at the schema layer.

## Upload validation (ingestion pipeline)

- **IMPLEMENTED**: file-type allowlist (`.json`, `.csv` only), a
  configured max upload size, structural validation of each record
  before it's mapped to an `Event`, and per-record error reporting
  rather than an all-or-nothing failure. See `MODULE_CATALOG.md`
  module 5.

## SQL injection prevention

- **IMPLEMENTED**: all database access goes through SQLAlchemy's ORM/
  query builder with bound parameters — no string-formatted SQL exists
  anywhere in this codebase. No raw-SQL endpoint exists, and none is
  planned.

## Cross-origin restrictions

- **IMPLEMENTED**: `CORSMiddleware` configured with an explicit
  allowlist (`CORS_ALLOWED_ORIGINS` in settings, defaulting to the
  local Vite dev server origin only) — not `allow_origins=["*"]`.

## Sensitive logging

- **IMPLEMENTED**: the structured logging setup never logs a request
  body, password, or token value. Ingestion logs record counts
  (accepted/rejected/duplicate) and per-record *error reasons*, never
  the raw uploaded payload (Section 10, requirement 14).

## Error disclosure

- **IMPLEMENTED**: a global exception handler returns a generic JSON
  error shape (`{"detail": ..., "request_id": ...}`) for unhandled
  exceptions — never a Python stack trace to the client. The real
  traceback goes to the server-side structured log only, tagged with
  the same request ID the client sees.

## Audit history

- **IMPLEMENTED**: `AuditRecord` writes on every user/source/
  investigation/ingestion-job mutation, with actor, action, target,
  outcome, timestamp, and request-correlation ID. No API route exists
  to update or delete an `AuditRecord` — not "blocked by permission,"
  genuinely absent from the router.
- **Explicit distinction (Section 16 requirement)**: this is an
  **append-oriented application audit log**, not a cryptographically
  tamper-evident one. There is no hash-chaining, no write-once storage
  backend, and no cryptographic signing of audit entries. A database
  administrator with direct DB access could alter rows; this system
  does not defend against that threat model. If a tamper-evident
  requirement ever applies, it needs its own dedicated implementation
  and its own test proving the property — not a claim resting on "it's
  append-only in the application layer."

## Data retention, backup strategy

- **NOT IMPLEMENTED** beyond noting the gap: no retention policy
  enforcement, no automated backup. Reserved (governance)
  and (production readiness/backup documentation). Recorded
  here rather than silently absent.

## Least privilege / production configuration

- **IMPLEMENTED**: `Settings.ENVIRONMENT` distinguishes `development`
  from `production`; a startup check in `app/main.py` refuses to start
  with `ENVIRONMENT=production` while `SECRET_KEY` still equals the
  `dev-only` placeholder, specifically to prevent Section 16's
  "do not disable authentication globally to simplify development"
  failure mode from reaching a real deployment unnoticed.
- No production credentials are committed anywhere in this repository.
  No default administrator account exists with a known password in
  any non-local-seed context — the seed script creates a development
  admin account only when run explicitly, and prints (never logs
  silently) the generated password once, with a clear
  "development only" label.

## What's reserved

Advanced authorization (attribute-based or row-level), formal retention
policy enforcement, a documented backup/restore procedure, and a
broader security hardening pass (dependency scanning, a documented
threat model) are explicitly the scope, not silently dropped.

## Update
Authorization, isolation, audit governance, lifecycle, environment and known-risk documentation now lives in the other files of this directory; start with `KNOWN_RISKS.md`.
