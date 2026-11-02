"""Reading the trail back: a document's run log, and metrics over all documents. All in SQL."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, Engine, Numeric, cast, extract, func, literal, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from intakefold.db.models import (
    AuditEvent,
    Batch,
    BatchSource,
    Document,
    DocumentStatus,
    Extraction,
    RunStep,
    User,
)

NOT_PROCESSED = (DocumentStatus.QUEUED, DocumentStatus.PROCESSING)
WENT_TO_REVIEW = (DocumentStatus.NEEDS_REVIEW, DocumentStatus.APPROVED, DocumentStatus.REJECTED)
NO_EXTRACTOR = "none"
SHARE_PLACES = 4


@dataclass(frozen=True)
class AuditEntry:
    action: str
    field: str | None
    old_value: str | None
    new_value: str | None
    actor_name: str | None  # None means the system.
    created_at: datetime


@dataclass(frozen=True)
class RunLog:
    steps: list[RunStep]
    events: list[AuditEntry]


@dataclass(frozen=True)
class MetricsRow:
    extractor: str
    processed: int
    auto_approved: int
    went_to_review: int
    failed: int
    auto_approved_share: Decimal
    review_share: Decimal
    failure_share: Decimal
    average_seconds: Decimal | None


def run_log(engine: Engine, document_id: uuid.UUID) -> RunLog | None:
    with Session(engine) as session:
        if session.get(Document, document_id) is None:
            return None
        steps = list(
            session.scalars(
                select(RunStep)
                .where(RunStep.document_id == document_id)
                .order_by(RunStep.started_at, RunStep.id)
            )
        )
        rows = session.execute(
            select(AuditEvent, User.display_name)
            .outerjoin(User, User.id == AuditEvent.actor_user_id)
            .where(AuditEvent.document_id == document_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        ).all()
        events = [
            AuditEntry(
                action=event.action,
                field=event.field,
                old_value=event.old_value,
                new_value=event.new_value,
                actor_name=name,
                created_at=event.created_at,
            )
            for event, name in rows
        ]
        return RunLog(steps, events)


def share(part: ColumnElement[int], whole: ColumnElement[int]) -> ColumnElement[Decimal]:
    # Each group has at least one document, so the division is safe; NUMERIC keeps it exact.
    return func.round(cast(part, Numeric) / cast(whole, Numeric), SHARE_PLACES)


def metrics(engine: Engine) -> list[MetricsRow]:
    """One row per extractor. Evaluation batches are left out: metrics describe real runs."""
    latest = (
        select(Extraction.document_id, Extraction.extractor)
        .ext(distinct_on(Extraction.document_id))
        .order_by(Extraction.document_id, Extraction.attempt.desc())
        .subquery()
    )
    ended = (
        select(RunStep.document_id, func.max(RunStep.finished_at).label("ended_at"))
        .group_by(RunStep.document_id)
        .subquery()
    )
    extractor = func.coalesce(latest.c.extractor, literal(NO_EXTRACTOR)).label("extractor")
    processed: ColumnElement[int] = func.count()
    auto: ColumnElement[int] = func.count().filter(Document.status == DocumentStatus.AUTO_APPROVED)
    review: ColumnElement[int] = func.count().filter(Document.status.in_(WENT_TO_REVIEW))
    failed: ColumnElement[int] = func.count().filter(Document.status == DocumentStatus.FAILED)
    seconds: ColumnElement[Decimal] = func.avg(
        extract("epoch", ended.c.ended_at - Document.received_at)
    )
    statement = (
        select(
            extractor,
            processed,
            auto,
            review,
            failed,
            share(auto, processed),
            share(review, processed),
            share(failed, processed),
            func.round(cast(seconds, Numeric), 1),
        )
        .select_from(Document)
        .join(Batch, Batch.id == Document.batch_id)
        .outerjoin(latest, latest.c.document_id == Document.id)
        .outerjoin(ended, ended.c.document_id == Document.id)
        .where(Document.status.not_in(NOT_PROCESSED), Batch.source != BatchSource.EVAL)
        .group_by(extractor)
        .order_by(extractor)
    )
    with Session(engine) as session:
        return [MetricsRow(*row) for row in session.execute(statement)]
