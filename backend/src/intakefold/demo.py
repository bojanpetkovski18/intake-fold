"""Demo mode: a seed batch that the worker runs through the real pipeline, and a reset to it."""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from intakefold.clock import Clock
from intakefold.db.models import (
    AuditEvent,
    Batch,
    BatchSource,
    DeliveryAttempt,
    Document,
    Extraction,
    Invoice,
    Job,
    LineItem,
    Role,
    RuleResult,
    RunStep,
    WebhookDelivery,
)
from intakefold.db.seed import USERS, demo_passwords
from intakefold.documents.intake import Accepted, prepare_file, record_batch
from intakefold.documents.storage import Storage
from intakefold.eval.harness import load_labels
from intakefold.settings import Settings

log = structlog.get_logger()

# Labeled, so the mock has an answer for each file, and it mixes clean, faulty and duplicate.
DEMO_SET = "development"
# Everything a document leaves behind. Users, sessions and vendors are kept, so nobody is
# signed out. A test checks that every other table is listed here.
DOCUMENT_TABLES = tuple(
    model.__tablename__
    for model in (
        DeliveryAttempt,
        WebhookDelivery,
        AuditEvent,
        RunStep,
        Job,
        RuleResult,
        LineItem,
        Invoice,
        Extraction,
        Document,
        Batch,
    )
)


@dataclass(frozen=True)
class DemoAccount:
    email: str
    role: Role
    password: str


def demo_accounts(settings: Settings) -> list[DemoAccount]:
    passwords = demo_passwords(settings)
    return [
        DemoAccount(email, role, passwords[role].get_secret_value()) for email, _, role in USERS
    ]


def seed_demo_batch(
    engine: Engine, storage: Storage, clock: Clock, settings: Settings, *, actor: uuid.UUID | None
) -> int:
    """Uploads the demo set as one batch and queues it. Returns how many documents were new."""
    paths = [label.path for label in load_labels(settings.labels_dir, DEMO_SET)]
    demo_settings = settings.model_copy(update={"max_batch_files": len(paths)})
    prepared = [
        prepare_file(engine, storage, demo_settings, raw_filename=path.name, data=path.read_bytes())
        for path in paths
    ]
    _, results = record_batch(
        engine,
        storage,
        clock,
        demo_settings,
        user_id=actor,
        prepared=prepared,
        source=BatchSource.DEMO,
    )
    return sum(1 for result in results if isinstance(result, Accepted) and not result.deduplicated)


def seed_demo_if_empty(engine: Engine, storage: Storage, clock: Clock, settings: Settings) -> int:
    """For the seed command, which runs on every start: only a fresh database gets the batch."""
    with Session(engine) as session:
        if session.scalar(select(func.count()).select_from(Document)):
            return 0
    return seed_demo_batch(engine, storage, clock, settings, actor=None)


def reset_demo(
    engine: Engine, storage: Storage, clock: Clock, settings: Settings, *, actor: uuid.UUID
) -> int:
    with engine.begin() as connection:
        # Taken first, so no upload can commit between reading the keys and emptying the tables.
        connection.execute(text("LOCK TABLE documents IN ACCESS EXCLUSIVE MODE"))
        stored = connection.execute(
            select(Document.id, Document.storage_key, Document.page_count)
        ).all()
        # TRUNCATE is the one statement the audit trigger allows (D-034). Without CASCADE, a
        # new table that points at these makes this fail, instead of being emptied unseen.
        # The names come from the models above, never from a request.
        connection.execute(text(f"TRUNCATE {', '.join(DOCUMENT_TABLES)}"))
    # After the commit: a failed delete leaves a stray file, never a row without its file.
    for document_id, storage_key, page_count in stored:
        storage.delete(storage_key)
        for page in range(1, (page_count or 0) + 1):
            storage.delete(Storage.page_key(document_id, page))
    queued = seed_demo_batch(engine, storage, clock, settings, actor=actor)
    log.info("demo_reset", actor=str(actor), removed=len(stored), queued=queued)
    return queued
