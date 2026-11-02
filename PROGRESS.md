# Progress

Last updated 2026-11-02. **M14 is pushed for review. Next: the owner merges, click-tests Codespaces, and decides on M15 and the release.**

## Milestones

Estimates are planning guesses, not measurements. Total: about 104 hours.

| # | Milestone | Depends on | Estimate | Status |
|---|---|---|---|---|
| 0 | Phase 0 planning | none | done | Approved 2026-10-31 |
| 1 | Repository, tooling, CI, app shell | 0 | 7 h | Merged; CI green on PR, `main` and `dev` |
| 2 | Database schema and job queue | 1 | 8 h | Merged |
| 3 | Identity and security base | 2 | 5 h | Merged |
| 4 | Upload and documents API | 3 | 7 h | Merged |
| 5 | Fictional document generator and labeled set | 1 | 7 h | Merged |
| 6 | Extraction: mock, Claude, schema, repair, injection defense | 4, 5 | 10 h | Merged |
| 7 | Validation rules and routing | 6 | 6 h | Merged |
| 8 | Sign-in and inbox screens | 3, 4 | 6 h | Merged |
| 9 | Review screen | 7, 8 | 9 h | Merged with M10 |
| 10 | Webhook delivery, sink and CSV export | 7 | 7 h | Merged |
| 11 | Run log, audit trail and metrics | 9, 10 | 6 h | Merged |
| 12 | Evaluation harness | 7 | 6 h | Merged; `dev` now contains `main` |
| 13 | Polish, accessibility and demo mode | 11, 12 | 8 h | Merged |
| 14 | End-to-end test, Docker, README and portfolio kit | 13 | 9 h | Pushed for review |
| 15 | Real-model measurement (owner-gated) | 12 | 3 h plus API spend | Blocked until the owner authorizes it; blocks nothing |

## Changes from the owner's expected plan

- **Added M3, identity,** per D-002.
- **Split the front end:** M8 gives sign-in and inbox a home, so M9 can focus on the review screen.
- **Separated M15, real-model measurement,** so a paid key never holds up the other milestones. M12 builds and tests the harness with the mock.
- **Created `run_steps` and `audit_events` in M2,** and write to them from M4 on. M11 adds the reading side. Retrofitting logging is how it ends up incomplete.
- **M1 includes the app shell** and one real test at each level, so CI protects everything after it.
- **Pre-release scan is in M14,** and the repository's public status is flagged now.

## Measured results

Every number used in the README or portfolio kit must have a row here. None of these is extraction accuracy: no real-model run has happened (M15).

"Owner's machine" is the owner's Windows 11 machine with Docker Desktop (engine 29.8.2, Compose 5.5.1).

| What | Value | Method | Model | Date | Machine |
|---|---|---|---|---|---|
| Backend tests | 663 passed, 310 of them integration tests against PostgreSQL | `bash scripts/check.sh`; `pytest --collect-only -m integration` | Mock | 2026-11-02 | Owner's machine, and a `node:24.22.1-bookworm` Linux container |
| Front-end tests | 127 passed, with axe on 24 screen states | `bash scripts/check.sh` (Vitest) | None | 2026-11-02 | Owner's machine, and the Linux container |
| End-to-end journey | 3 of 3 runs passed in a row, no retries, 6.7 to 8.9 s each | `bash scripts/check.sh` (`scripts/e2e.sh`), Chromium from Playwright 1.64.1 | Mock | 2026-11-02 | Owner's machine; also passed with `E2E_RUNNER=container` |
| Browser accessibility audit | 116 axe runs, 0 violations, across 9 contexts (5 widths, light and dark, 200% zoom) | M13 audit, `docs/AUDIT.md` | Mock | 2026-11-02 | Owner's machine |
| Fresh clone to a working app | 112 s from `docker compose up --build` to `/api/demo` answering 200 | Clone into a temp folder, an empty buildx builder for a cold build cache, follow the README | Mock | 2026-11-02 | Owner's machine |
| Dev container start | 4 min 13 s from `devcontainer up` to the stack healthy | `@devcontainers/cli` 0.89.0 from a fresh clone | Mock | 2026-11-02 | Owner's machine |
| Image sizes | backend 385 MB, web 90.7 MB | `docker image ls` | None | 2026-11-02 | Owner's machine |
| Production bundle | JS 385.19 kB (119.16 kB gzip), CSS 7.90 kB | `vite build` output in the web image build | None | 2026-11-02 | Owner's machine |

## Known issues

| Issue | Plan |
|---|---|
| The repository is public by the owner's choice | The M14 scan of the full history found no secrets or personal data beyond the owner's name and GitHub username (D-086) |
| `minimatch` advisory (moderate, 11 npm audit lines, dev tooling only) | Re-check at each milestone start. Remove when ESLint moves to a fixed version, or take an override with owner approval. See D-028 |
| Python 3.15.0 is behind 3.15.1 and 3.15.2, which carry security fixes (`docs/RESEARCH.md`, M14) | Bump the images and `.python-version` when 3.15.2 clears the floor on 2026-11-08 |
| Local `.env` files need the new `DEMO_*_PASSWORD` values before seeding | Copy them from `.env.example` and change them |
| `main` lacks M12 and M13; `dev` contains everything on `main` | A release brings `main` up to date. Setting `dev` as the default branch prevents PRs landing on `main` |
| The Vite dev server needs `ALLOW_INSECURE_COOKIES=true` and its origin in `ALLOWED_ORIGINS` | Local setup only |
| No time limit on a single PDFium render | Revisit in M6 (D-047) |
| Move to `anthropic` 2.x before any real run | After 2026-11-04, in M15 (D-052) |
| Fallback with structured outputs is unconfirmed | First test in M15, with a switch to turn it off (D-054) |
| Extraction limits and the batch token cap are not measured | Replace with real figures in M15 (D-048, D-055) |
| Local databases need migration `0002` | `alembic upgrade head` |
| The sink forgets seen event IDs on restart | Demo only (D-069) |
| The API key is not needed until M15 | Owner stores it in local `.env` when authorizing a run |
| No page scores or load test (playbook Phase 7) | Not in the M14 brief, and not done. Only the bundle and image sizes are measured |
| Screen readers, Firefox and Safari not run in the M13 audit | Chromium plus axe only; see `docs/AUDIT.md` |
| Codespaces not yet started on GitHub | Tested with the dev container CLI; the owner click-tests after merge (D-081) |
| SPEC section 12 lists the inbox without the new export panel | Owner's call (D-082) |
| The dev container's Docker engine and Compose are the feature's latest, not pinned | D-081 |

## Next step

Owner opens a PR for `#0014-e2e-docker-readme-and-portfolio-kit` against `dev`, checks CI (now including the e2e job), and merges. Then, owner actions: open the repository in Codespaces once, and decide on M15 (real-model measurement) and the release steps in the playbook's section 16.
