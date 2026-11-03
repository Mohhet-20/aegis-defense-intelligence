# Publishing AEGIS to a private GitHub repository

Written for the repository owner. Nothing in this guide has been executed: as of 2026-10-19 the
repository has **no remote**, nothing has been pushed, `main` is untouched, and no tag or release
exists. Replace `<OWNER>` and `<REPO>` with your GitHub account (or organization) and repository name.
Commands are PowerShell, run from the repository root; they work unchanged in Git Bash.

**Before you start:** the licence is decided (MIT, `LICENSE`), and all work up to 1.0.0-rc.2 is
committed (latest commits listed by `git log`); step 2 is needed only for changes made after that.

## 1. Review the final state

```powershell
git status                        # expect: on branch release/final-stabilization
git log --oneline -16             # stabilization + rc.2 commits above main's baseline 8c1aaa3
git diff --stat                   # should be empty (everything committed)
git remote -v                     # expect: nothing (no remote yet)
backend\.venv\Scripts\python.exe scripts\verify_release.py --quick    # PASS/FAIL/NOT RUN/BLOCKED summary
```

## 2. Review and commit any further work (owner approval)

```powershell
git add -A
git status --short                # confirm the list: no .env, *.db, media_storage, node_modules, dist
git diff --cached --stat
backend\.venv\Scripts\detect-secrets-hook.exe --baseline .secrets.baseline (git ls-files)   # Git Bash: git ls-files -z | xargs -0 backend/.venv/Scripts/detect-secrets-hook.exe --baseline .secrets.baseline
git commit -m "Consolidation pass: PostgreSQL fixes, CSP, code splitting, frontend tests, release tooling and docs"
```

If the secret hook reports a new finding, inspect it (file:line is printed; the value is not), fix or
mark a reviewed false positive with `detect-secrets scan > .secrets.baseline`, and re-run.

## 3. Create an empty repository

For a showcase the repository will end up **Public**. Creating it **Private** first and switching to
public once CI is green (step 10) means nobody sees a red first run. Choose one:

- **Web:** <https://github.com/new> → name `<REPO>` → **Private** (or Public) → do **not** add a README, license or
  .gitignore (they would conflict with the existing history) → Create.
- **GitHub CLI** (not installed on the verification machine; install from <https://cli.github.com>):
  `gh auth login`, then `gh repo create <OWNER>/<REPO> --private` (no `--push`, no `--source`).

## 4. Add the remote without overwriting anything

```powershell
git remote -v                                     # if "origin" already exists, STOP and inspect it
git remote add origin https://github.com/<OWNER>/<REPO>.git
git remote -v                                     # verify the URL before pushing
```

If `origin` exists and points elsewhere, add the new one under another name (`git remote add github
https://github.com/<OWNER>/<REPO>.git`) and use that name below. Never `git remote set-url` over a remote
you have not inspected.

## 5. Push the branches (no force)

```powershell
git push -u origin main                           # the Phase 14 baseline -- the base for the pull request
git push -u origin release/final-stabilization    # the release candidate; this triggers CI
```

Do not use `--force`. Local archives and recovery bundles live outside the repository on purpose; never add them.

## 6. Watch GitHub Actions

Web: repository → **Actions** → workflow **CI** → the run for `release/final-stabilization`. The jobs:
`backend` (Python 3.12 / 3.13 / 3.14), `postgres`, `frontend`, `security`, `containers`.
With the CLI: `gh run list --branch release/final-stabilization`, `gh run watch`, `gh run view --log-failed`.

The workflow has never run before, so expect first-run issues. The most likely ones:
`containers` (the Docker images have never been built), Python 3.12/3.13 (only 3.14 was tested locally),
and `postgres` timing (the full suite takes about 50 minutes on a laptop; the CI job runs a subset).

## 7. Resolve CI failures

Reproduce locally where possible (`scripts\verify_release.py`, the commands in `.github/workflows/ci.yml`),
fix on the release branch, commit, `git push`. Never weaken a test to make CI pass; record anything you
accept as a known risk in `docs/security/KNOWN_RISKS.md`. Update `docs/operations/RELEASE_VERIFICATION.md`
with the first green run's link -- that is the first real evidence that CI and the containers work.

## 8. Merge to `main` -- only after review

```powershell
gh pr create --base main --head release/final-stabilization --title "Release candidate 1.0.0-rc.3"   # or open the PR on the web
```

Review the diff, confirm every CI job is green, then merge on the web (a merge commit keeps the
stabilization history intact). Recommended repository settings: branch protection on `main` requiring
the CI checks; **Settings → Code security → Private vulnerability reporting** on (referenced by `SECURITY.md`);
Dependabot alerts on.

## 9. Tag a release -- only after CI is green

```powershell
git switch main; git pull
git tag -a v1.0.0-rc.3 -m "AEGIS 1.0.0-rc.3 (release candidate)"
git push origin v1.0.0-rc.3
gh release create v1.0.0-rc.3 --prerelease --title "AEGIS 1.0.0-rc.3" --notes-file CHANGELOG.md    # or via the web
```

## 10. Make it public and showcase it

1. **Settings → General → Danger Zone → Change visibility → Public** (your decision; everything in the
   history has been scanned for secrets and personal data, but read `git log` once yourself).
2. Repository page → **About** (gear icon): a one-line description (e.g. *"Full-stack analyst platform:
   FastAPI + React, real object detector, 1,400+ tests"*), the live-demo URL as **Website**, and topics
   such as `fastapi`, `react`, `typescript`, `computer-vision`, `opencv`, `postgresql`, `full-stack`.
3. Deploy the free demo: [`PUBLIC_DEMO.md`](PUBLIC_DEMO.md). Then in `README.md` replace the commented
   live-demo placeholder near the top with the link, and add the CI badge:
   `[![CI](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml/badge.svg)](https://github.com/<OWNER>/<REPO>/actions/workflows/ci.yml)`.
4. On your GitHub profile, **Customize your pins** → pin the repository.
5. Settings → Code security: turn on **Private vulnerability reporting**, Dependabot alerts and
   secret scanning (free for public repositories).
