"""What people see and do about dead jobs. The queue itself stays unaware of documents."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, String, cast, select, tuple_
from sqlalchemy.orm import Session

from intakefold.audit.records import record_audit_event
from intakefold.clock import Clock
from intakefold.db.models import Document, DocumentStatus, Job, JobStatus
from intakefold.jobs.queue import requeue_statement


@dataclass(frozen=True)
class DeadJob:
    id: uuid.UUID
    kind: str
    attempts: int
    max_attempts: int
    last_error: str | None
    updated_at: datetime
    document_id: uuid.UUID | None
    filename: str | None


@dataclass(frozen=True)
class DeadJobPage:
    items: list[DeadJob]
    next_position: tuple[datetime, uuid.UUID] | None


class JobNotFound(Exception):
    pass


class JobNotDead(Exception):
    pass


def list_dead_jobs(
    engine: Engine, *, limit: int, after: tuple[datetime, uuid.UUID] | None
) -> DeadJobPage:
    statement = (
        select(Job, Document.id, Document.original_filename)
        .outerjoin(Document, Job.payload["document_id"].astext == cast(Document.id, String))
        .where(Job.status == JobStatus.DEAD)
        .order_by(Job.updated_at.desc(), Job.id.desc())
        .limit(limit + 1)
    )
    if after is not None:
        statement = statement.where(tuple_(Job.updated_at, Job.id) < after)
    with Session(engine) as session:
        rows = session.execute(statement).all()
        items = [
            DeadJob(
                id=job.id,
                kind=job.kind,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                last_error=job.last_error,
                updated_at=job.updated_at,
                document_id=document_id,
                filename=filename,
            )
            for job, document_id, filename in rows[:limit]
        ]
    position = (items[-1].updated_at, items[-1].id) if len(rows) > limit else None
    return DeadJobPage(items, position)


def retry_dead_job(engine: Engine, job_id: uuid.UUID, actor: uuid.UUID, clock: Clock) -> None:
    """Requeues the job and reopens its document together, so neither is left behind."""
    with Session(engine) as session, session.begin():
        job = session.get(Job, job_id, with_for_update=True)
        if job is None:
            raise JobNotFound
        if job.status is not JobStatus.DEAD:
            raise JobNotDead
        raw_id = job.payload.get("document_id")
        session.expire(job)
        session.execute(requeue_statement(job_id, clock.now()))
        if raw_id is None:
            return
        document = session.get_one(Document, uuid.UUID(str(raw_id)))
        document.status = DocumentStatus.QUEUED
        document.status_reasons = []
        document.finished_at = None
        record_audit_event(
            session, document_id=document.id, actor_user_id=actor, action="job_requeued"
        )
