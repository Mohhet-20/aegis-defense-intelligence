# Architecture Decisions — AEGIS

Decisions made during Phase 1 and the reasoning behind them. Written as
a living record — later phases append to this file rather than
replacing it, and a later phase that reverses a decision here should
say so explicitly rather than silently contradicting it.

## Modular monolith, not microservices

One FastAPI process, one database, one React SPA. Section 5 explicitly
rules out Kubernetes/Kafka/Redis/vector databases/microservices "before
a concrete implementation requirement justifies them," and there is no
such requirement at Phase 1. Module boundaries inside the monolith
(Section 6) are enforced by convention — separate files, explicit
imports, no module reaching into another's internals — not by process
isolation. If a later phase needs a genuinely separate process (e.g. a
compute-heavy inference worker in Phase 4), that's a deliberate decision
to be made then, with a reason recorded here, not a default.

## SQLite by default, Postgres-capable by configuration

`DATABASE_URL` defaults to a local SQLite file. This is Section 5's
explicit "SQLite as an optional local-development or test mode" allowance
— it lets the whole project run with zero external setup for anyone
cloning the repo, while `DATABASE_URL=postgresql+psycopg2://...` switches
to Postgres with no code changes. The schema is written to avoid
SQLite-incompatible constructs (no Postgres-only column types, no
features that would make the Alembic migration chain fork by database
backend), so the same migration history applies to both. If a later
phase introduces a genuinely Postgres-only feature, that constraint gets
written down here and in `docs/project/limitations.md`, not discovered
by a confused user later.

## SQLAlchemy 2.0 typed ORM + Alembic from the first migration

Models use SQLAlchemy 2.0's `Mapped[...]`/`mapped_column()` typed style.
Alembic is wired up from the very first schema, not added retroactively
— `alembic upgrade head` against a fresh database is part of this
phase's actual verification (see `PROJECT_STATUS.md` "Commands
executed"), not a promise to add later.

## JWT bearer tokens, not server-side sessions

Section 9 allows either "secure cookie-based sessions or an appropriate
authentication design." JWT access + refresh tokens were chosen because
the frontend is a separate SPA talking to a versioned JSON API
(`/api/v1`), and a stateless bearer token avoids needing a server-side
session store (which would be the first thing pulling in Redis or an
equivalent, which Section 5 says not to add without a concrete reason).
The trade-off, stated honestly: a JWT can't be server-side revoked
before its expiry without a token-blocklist mechanism, which doesn't
exist yet. Expiry is kept short (30 minutes access / 7 days refresh) as
the mitigation; a real revocation list is future work if a concrete
need for it appears.

## RBAC as a route dependency, not frontend-only checks

`require_permission(...)` is a FastAPI dependency checked on the server
for every protected route. The frontend also hides UI it knows the
user can't use (so the product doesn't dangle buttons that will 403),
but that's a UX nicety, never the enforcement — Section 9 explicitly
forbids relying on frontend-only role checks, and every permission
check in this codebase has a corresponding test that calls the route
directly, bypassing the frontend entirely, to prove the server itself
rejects it.

## Four roles, explicit permissions, not a role-string scattered through code

`administrator`, `analyst`, `investigator`, `viewer` (Section 9) map to
an explicit `Permission` enum (`app/core/security.py`) and a
`ROLE_PERMISSIONS` table, the same pattern used successfully in an
earlier version of this kind of platform: routes depend on a
*permission*, never directly on a role name, so adding a fifth role
later means editing one table, not every route.

## Request correlation IDs via middleware, structured logging

Every request gets an `X-Request-ID` (generated if the caller doesn't
supply one), attached to the request state and echoed in the response
header and in every log line for that request — Section 8 requires
correlation IDs and Section 19 requires "request correlation" as a
first-class concern, not an afterthought bolted onto error responses
only.

## Tenant isolation: modeled, not yet enforced

`Organization` exists and every org-scoped model carries an
`organization_id` column, but Section 7 says explicitly: "only
introduce tenant isolation if it is actually enforced across data
access and authorization." Phase 1 ships a single default organization
and does **not** yet filter every query by the caller's
`organization_id` — that enforcement is Phase 14's job (Security and
Governance), and claiming it exists now would violate Rule 3 (no fake
functionality). This is recorded here and in
`docs/project/limitations.md` rather than silently implied by the
column's existence.
