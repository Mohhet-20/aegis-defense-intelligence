# Contributing to AEGIS

## Ground rules

1. **Defensive scope only.** No autonomous targeting, weapon control, engagement
   recommendations or automated harmful action. Model output stays advisory and reviewable;
   never present a score or appearance as proof of intent.
2. **No fabricated data or results.** Synthetic and simulated records must be labelled. Don't
   claim a test, migration or deployment passed unless you ran it.
3. **Server-side authorization.** Every protected operation checks permissions and organization
   in the backend. Hiding a button is UX, not security.
4. **Never commit secrets** (`.env`, keys, tokens), databases, `media_storage/` or build output.

## Setup

Follow the README quick start; details in `docs/guides/LOCAL_DEVELOPMENT.md`.
Python 3.12+ and Node.js 20+.

## Before opening a pull request

```bash
cd backend
python -m pytest -q
ruff check --select E9,F63,F7,F82 app tests scripts     # the CI lint gate (pip install ruff)
ruff check --select F401,F811,F841 --exclude __init__.py app scripts
python scripts/gen_config_reference.py --check          # if you touched app/core/config.py

cd ../frontend
npm run lint
npm test                                                # Vitest component/unit tests
npm run build
```

Or run everything available locally in one go (PASS / FAIL / NOT RUN / BLOCKED per check):
`backend/.venv/bin/python scripts/verify_release.py` (Windows: `backend\.venv\Scripts\python.exe scripts\verify_release.py`).
If you touched queries with dates or time zones, also run the suite on a disposable PostgreSQL
database whose session zone is not UTC (`TEST_DATABASE_URL=... PGTZ=Asia/Kolkata python -m pytest -q`).

If you changed the schema, also run on a scratch database:

```bash
DATABASE_URL=sqlite:///./scratch.db alembic upgrade head
DATABASE_URL=sqlite:///./scratch.db alembic check        # must say "No new upgrade operations detected"
DATABASE_URL=sqlite:///./scratch.db alembic downgrade -1 && DATABASE_URL=sqlite:///./scratch.db alembic upgrade head
```

If you changed pages or routes, run `scripts/e2e_route_walk.py` against a seeded development
database (see its docstring) and keep `navigation.ts` in step with `App.tsx` -- a contract test
fails on routes missing from the navigation.

## Conventions

- **Backend:** routes in `app/api/routes/` stay thin; logic lives in `app/services/`. Every
  query that touches tenant data filters by `organization_id`. Errors use the shared
  `{detail, request_id}` shape and never echo submitted values or stack traces.
- **Migrations:** one Alembic revision per schema change; never edit an applied revision; use
  `batch_alter_table` for SQLite-compatible alterations; never "fix" a migration by deleting a
  database.
- **Frontend:** API calls go through `src/api/client.ts`; types in `src/types/`; every page has
  loading, empty and error states; reuse `components/ui/Primitives.tsx`.
- **Tests:** synthetic fixtures and isolated databases only. Add a regression test with every
  bug fix. Never weaken an assertion to make a test pass.
- **Docs:** update `docs/implementation/PROJECT_STATUS.md`, `CHANGELOG.md` and
  `docs/security/KNOWN_RISKS.md` when behaviour, verification status or risks change.

## Commits

Small, focused commits with a message that says what changed and why. Mention migrations and
configuration changes explicitly.
