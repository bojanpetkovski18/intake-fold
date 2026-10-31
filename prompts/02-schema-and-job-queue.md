# M2: Database schema and job queue

**Branch:** `#0002-database-schema-and-job-queue`
**Goal:** the full data model and a queue that survives crashes and races.
**Estimate:** 8 h

**Context:** SPEC sections 8 and 10. D-006, D-014.
**Re-check:** SQLAlchemy and Alembic versions.

**Scope**
- SQLAlchemy models and Alembic migrations for every table in SPEC section 10.
- Append-only trigger on `audit_events` that blocks row updates and deletes.
- Small helpers to write `run_steps` and `audit_events`, used from M4 on.
- Queue module: enqueue with idempotency key, claim with `FOR UPDATE SKIP LOCKED`, lease heartbeat, succeed, fail with backoff and jitter, dead state, reclaim expired leases, requeue.
- Worker loop with a handler registry and graceful shutdown. An injectable clock.
- Seed script for vendors and fictional users.

**Out of scope:** real handlers, HTTP endpoints for jobs.

**Tests required**
- Migration up, down and up against real Postgres.
- Real race: many processes or threads claiming from one table, no job claimed twice.
- Backoff timing with a fake clock. Dead after `max_attempts`.
- Lease expiry reclaim. A killed worker's job runs again.
- Enqueue idempotency.
- Audit trigger blocks `UPDATE` and `DELETE`.
- Mutation check: remove `SKIP LOCKED` or the lock and confirm the race test fails.

**Acceptance criteria:** AC-04, AC-06, the queue half of AC-05, and the trigger half of AC-18.

**Python notes to flag:** SQLAlchemy 2 `Mapped[]` typing, session scoping, Alembic autogenerate limits.
