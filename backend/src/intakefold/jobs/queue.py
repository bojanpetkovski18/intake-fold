"""PostgreSQL job queue with leases: at-least-once delivery, so handlers must be idempotent."""

import random
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import ColumnElement, Engine, and_, case, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from intakefold.clock import Clock
from intakefold.db.models import Job, JobStatus

DEFAULT_MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 300.0
LAST_ERROR_LENGTH = 500


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: uuid.UUID
    kind: str
    payload: dict[str, object]
    attempts: int
    max_attempts: int
    worker_id: str


@dataclass(frozen=True, slots=True)
class Enqueued:
    job_id: uuid.UUID
    created: bool


def enqueue(
    session: Session,
    *,
    kind: str,
    idempotency_key: str,
    payload: Mapping[str, object],
    clock: Clock,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Enqueued:
    """Adds to the caller's transaction, so a job commits with the change that caused it."""
    created = session.scalar(
        insert(Job)
        .values(
            id=uuid.uuid7(),
            kind=kind,
            payload=dict(payload),
            idempotency_key=idempotency_key,
            status=JobStatus.QUEUED,
            max_attempts=max_attempts,
            run_after=clock.now(),
        )
        .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
        .returning(Job.id)
    )
    if created is not None:
        return Enqueued(created, created=True)
    existing = session.scalar(select(Job.id).where(Job.idempotency_key == idempotency_key))
    if existing is None:  # The other insert is not committed and rolled back meanwhile.
        raise RuntimeError(f"Job {idempotency_key!r} vanished during enqueue.")
    return Enqueued(existing, created=False)


def claim(engine: Engine, worker_id: str, lease: timedelta, clock: Clock) -> ClaimedJob | None:
    """Takes the next due job. The transaction ends here, so no lock outlives this call."""
    now = clock.now()
    next_job = (
        select(Job.id)
        .where(Job.status == JobStatus.QUEUED, Job.run_after <= now)
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .cte("next_job")
    )
    statement = (
        update(Job)
        .where(Job.id == next_job.c.id)
        .values(
            status=JobStatus.RUNNING,
            # Counted at claim, so a job that kills its worker still runs out of attempts.
            attempts=Job.attempts + 1,
            locked_by=worker_id,
            locked_until=now + lease,
            updated_at=now,
        )
        .returning(Job.id, Job.kind, Job.payload, Job.attempts, Job.max_attempts)
    )
    with engine.begin() as connection:
        row = connection.execute(statement).one_or_none()
    if row is None:
        return None
    return ClaimedJob(row.id, row.kind, row.payload, row.attempts, row.max_attempts, worker_id)


def _still_owned(job: ClaimedJob) -> ColumnElement[bool]:
    # The attempt number fences off a worker whose lease expired and was given to another.
    return and_(
        Job.id == job.id,
        Job.status == JobStatus.RUNNING,
        Job.locked_by == job.worker_id,
        Job.attempts == job.attempts,
    )


def heartbeat(engine: Engine, job: ClaimedJob, lease: timedelta, clock: Clock) -> bool:
    """Extends the lease. False means the job was lost and the worker should not trust it."""
    now = clock.now()
    with engine.begin() as connection:
        updated = connection.execute(
            update(Job)
            .where(_still_owned(job))
            .values(locked_until=now + lease, updated_at=now)
            .returning(Job.id)
        ).first()
    return updated is not None


def succeed(engine: Engine, job: ClaimedJob, clock: Clock) -> bool:
    with engine.begin() as connection:
        updated = connection.execute(
            update(Job)
            .where(_still_owned(job))
            .values(
                status=JobStatus.SUCCEEDED,
                locked_by=None,
                locked_until=None,
                last_error=None,
                updated_at=clock.now(),
            )
            .returning(Job.id)
        ).first()
    return updated is not None


def backoff_delay(attempt: int, rng: random.Random) -> timedelta:
    """Half fixed, half random, so failed jobs do not all return at the same moment."""
    ceiling = min(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1), BACKOFF_MAX_SECONDS)
    return timedelta(seconds=ceiling / 2 + rng.uniform(0, ceiling / 2))


def fail(
    engine: Engine,
    job: ClaimedJob,
    error: str,
    clock: Clock,
    rng: random.Random,
    *,
    retryable: bool = True,
) -> JobStatus | None:
    """Queues a retry or marks the job dead. None means it was already lost to another worker.

    `error` is stored and shown in the UI, so it must never contain document content.
    """
    now = clock.now()
    exhausted = not retryable or job.attempts >= job.max_attempts
    status = JobStatus.DEAD if exhausted else JobStatus.QUEUED
    with engine.begin() as connection:
        updated = connection.execute(
            update(Job)
            .where(_still_owned(job))
            .values(
                status=status,
                run_after=now if exhausted else now + backoff_delay(job.attempts, rng),
                locked_by=None,
                locked_until=None,
                last_error=error[:LAST_ERROR_LENGTH],
                updated_at=now,
            )
            .returning(Job.id)
        ).first()
    return status if updated is not None else None


def reclaim_expired(engine: Engine, clock: Clock) -> int:
    """Returns jobs whose worker vanished to the queue, or to the dead state if out of attempts."""
    now = clock.now()
    expired = (
        select(Job.id)
        .where(Job.status == JobStatus.RUNNING, Job.locked_until < now)
        .with_for_update(skip_locked=True)
        .cte("expired")
    )
    statement = (
        update(Job)
        .where(Job.id == expired.c.id)
        .values(
            status=case(
                (Job.attempts >= Job.max_attempts, JobStatus.DEAD),
                else_=JobStatus.QUEUED,
            ),
            run_after=now,
            locked_by=None,
            locked_until=None,
            last_error="lease_expired",
            updated_at=now,
        )
        .returning(Job.id)
    )
    with engine.begin() as connection:
        return len(connection.execute(statement).all())


def requeue(engine: Engine, job_id: uuid.UUID, clock: Clock) -> bool:
    """Gives a dead job a fresh set of attempts."""
    now = clock.now()
    with engine.begin() as connection:
        updated = connection.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.DEAD)
            .values(
                status=JobStatus.QUEUED,
                attempts=0,
                run_after=now,
                last_error=None,
                updated_at=now,
            )
            .returning(Job.id)
        ).first()
    return updated is not None
