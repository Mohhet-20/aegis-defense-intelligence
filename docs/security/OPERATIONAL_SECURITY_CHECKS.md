# Operational Security Checks (Phase 14)

Run `python backend/scripts/security_checks.py` (reports skipped scanners rather than hiding them).

| Check | Tool | Result in this run |
|---|---|---|
| Python dependency vulnerabilities | pip-audit (`--no-deps`, direct pins only) | Clean after replacing python-jose with PyJWT 2.15.0 (python-jose PYSEC-2026-4298, no fix; PyJWT 2.10.1 advisories fixed in 2.14/2.15). Transitive dependencies were **not** audited because a full resolve failed in the sandbox |
| Static analysis | bandit (medium+) | 2 medium B608 in `app/edge/local_store.py`, reviewed: SQL assembled from fixed identifiers; values parameterised. Treated as false positives |
| Secret detection | detect-secrets | `--all-files` over the whole tree: 45 candidates; `security_checks.py` (tests and migration revision ids excluded): 13. All reviewed as non-secrets (placeholders, dev compose credentials, key-name strings, cache tags) -- note docker-compose dev credentials are real-looking defaults, see KNOWN_RISKS |
| Frontend dependencies | `npm audit --omit=dev` | After `npm audit fix` (react-router-dom 6.30.6): 2 moderate remain. Dev toolchain (tailwind: braces, postcss-selector-parser) has findings needing a breaking Tailwind 4 upgrade |
| Migration validation | alembic upgrade -> downgrade -> upgrade on SQLite | Passed (downgrade preserves data) |
| Container configuration | none | **Not run** (no scanner/Docker available) |

A clean scan is not proof of security: these tools only detect known patterns and known advisories.
Backend tests were run against SQLAlchemy 2.0.54 (the sandbox could not install the pinned 2.1.4).
