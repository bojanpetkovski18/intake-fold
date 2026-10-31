# M1: Repository, tooling, CI, app shell

**Branch:** `#0001-repository-tooling-and-ci`
**Goal:** a green baseline that later milestones cannot break.
**Estimate:** 7 h

**Context:** SPEC sections 11 and 14. D-003, D-004, D-005, D-006, D-007, D-020, D-021, D-025.
**Re-check:** Python patch release, all pins, image digests, GitHub Action SHAs, gitleaks and actionlint versions.

**Precondition:** the owner has settled repository visibility, the `main` and `dev` bootstrap, Git identity and the uv install.

**Scope**
- `.gitignore`, `.gitattributes` (LF), `.editorconfig`, `.env.example` with placeholders only, per-repository Git identity. Ignore `PROJECT-PLAYBOOK.md` unless the owner decides otherwise.
- Backend: `uv` project, Python pin, ruff, pyright strict, pytest, settings from the environment that fail fast, structured logging with trace IDs, problem-details errors, security headers, `GET /api/health`.
- Worker entry point that starts, logs and stops cleanly.
- Frontend: Vite, React, strict TypeScript, ESLint, Prettier, Vitest, app shell with layout, navigation and routing.
- `compose.yaml` with Postgres and a health check, on `127.0.0.1:5441`.
- CI on pull requests and pushes to `dev` and `main`: backend, frontend, secret scan of full history, actionlint, editorconfig check, `pip-audit`, `npm audit`. Actions pinned by SHA, read-only permissions, superseded runs cancelled.

**Out of scope:** database tables, auth, features.

**Tests required:** one unit test, one integration test against Postgres with Testcontainers, one component test.

**Acceptance criteria**
- Lint, types, tests and build pass locally and on the PR.
- A missing required setting stops start-up with a clear message.
- A deliberate type error and a deliberate lint error each fail their check.
- The health endpoint returns security headers and a trace ID.

**Verification:** run the chained local check. CI does not run on a branch push alone; until a PR exists, its result is unknown.
