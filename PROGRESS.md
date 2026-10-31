# Progress

Last updated 2026-10-31. **Phase 0 is approved. No application code exists. Next: M1.**

## Milestones

Estimates are planning guesses, not measurements. Total: about 104 hours.

| # | Milestone | Depends on | Estimate | Status |
|---|---|---|---|---|
| 0 | Phase 0 planning | none | done | Approved 2026-10-31 |
| 1 | Repository, tooling, CI, app shell | 0 | 7 h | Not started |
| 2 | Database schema and job queue | 1 | 8 h | Not started |
| 3 | Identity and security base | 2 | 5 h | Not started |
| 4 | Upload and documents API | 3 | 7 h | Not started |
| 5 | Fictional document generator and labeled set | 1 | 7 h | Not started |
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
| The GitHub repository is public, and the playbook starts repositories as private until the scan | Owner has not chosen to change it. Full scan in M14 either way; remind the owner before M1 pushes code |
| The GitHub repository is named `file-fold`; the project is Intakefold | Owner's rename, optional |
| Python is not installed on the host | uv installs the pinned interpreter in M1 |
| The API key is not needed until M15 | Owner stores it in local `.env` when authorizing a run |

## Next step

Start M1 on `#0001-repository-tooling-and-ci`, from `dev`.
