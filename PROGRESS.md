# Progress

Last updated 2026-10-31. **M5 is pushed for review. Next: M6, after the owner merges into `dev`.**

## Milestones

Estimates are planning guesses, not measurements. Total: about 104 hours.

| # | Milestone | Depends on | Estimate | Status |
|---|---|---|---|---|
| 0 | Phase 0 planning | none | done | Approved 2026-10-31 |
| 1 | Repository, tooling, CI, app shell | 0 | 7 h | Merged; CI green on PR, `main` and `dev` |
| 2 | Database schema and job queue | 1 | 8 h | Merged |
| 3 | Identity and security base | 2 | 5 h | Merged |
| 4 | Upload and documents API | 3 | 7 h | Merged |
| 5 | Fictional document generator and labeled set | 1 | 7 h | Pushed; CI result unknown until a PR exists |
| 6 | Extraction: mock, Claude, schema, repair, injection defense | 4, 5 | 10 h | Not started |
| 7 | Validation rules and routing | 6 | 6 h | Not started |
| 8 | Sign-in and inbox screens | 3, 4 | 6 h | Not started |
| 9 | Review screen | 7, 8 | 9 h | Not started |
| 10 | Webhook delivery, sink and CSV export | 7 | 7 h | Not started |
| 11 | Run log, audit trail and metrics | 9, 10 | 6 h | Not started |
| 12 | Evaluation harness | 7 | 6 h | Not started |
| 13 | Polish, accessibility and demo mode | 11, 12 | 8 h | Not started |
| 14 | End-to-end test, Docker, README and portfolio kit | 13 | 9 h | Not started |
| 15 | Real-model measurement (owner-gated) | 12 | 3 h plus API spend | Blocked until the owner authorizes it; blocks nothing |

## Changes from the owner's expected plan

- **Added M3, identity,** per D-002.
- **Split the front end:** M8 gives sign-in and inbox a home, so M9 can focus on the review screen.
- **Separated M15, real-model measurement,** so a paid key never holds up the other milestones. M12 builds and tests the harness with the mock.
- **Created `run_steps` and `audit_events` in M2,** and write to them from M4 on. M11 adds the reading side. Retrofitting logging is how it ends up incomplete.
- **M1 includes the app shell** and one real test at each level, so CI protects everything after it.
- **Pre-release scan is in M14,** and the repository's public status is flagged now.

## Measured results

None yet. Every number used in the README or portfolio kit must have a row here.

| What | Value | Method | Model | Date | Machine |
|---|---|---|---|---|---|

## Known issues

| Issue | Plan |
|---|---|
| The repository is public by the owner's choice, ahead of the M14 scan | gitleaks scans full history on every CI run. Full scan including personal data stays in M14 |
| `minimatch` advisory (moderate, 11 npm audit lines, dev tooling only) | Re-check at each milestone start. Remove when ESLint moves to a fixed version, or take an override with owner approval. See D-028 |
| Python 3.15.0 is behind 3.15.1 and 3.15.2 | Check their release notes, and bump after 2026-11-04 |
| Local `.env` files need the new `DEMO_*_PASSWORD` values before seeding | Copy them from `.env.example` and change them |
| Session cookie defaults to Secure, and the local http demo may need `ALLOW_INSECURE_COOKIES` | Decide in M14 (D-041) |
| PR #4 (M3) went to `main`, not `dev`. `dev` now has M3 through M4, and `main` has no M4 | Settled for `dev`. A later release brings `main` up to date |
| M8's requeue must return a failed document to `queued` | Handle in M8 (D-046) |
| No time limit on a single PDFium render | Revisit in M6 (D-047) |
| Rules in M7 must agree with `expected_routing` in the labels | Test against the labels in M7 (D-051) |
| The API key is not needed until M15 | Owner stores it in local `.env` when authorizing a run |
| `TRUNCATE` bypasses the audit trigger, by design for the demo reset | Owner to confirm the reading of AC-18 in D-034 |

## Next step

Owner opens a PR for `#0005-document-generator-and-labeled-set` against `dev`, checks CI, and merges. Then M6.
