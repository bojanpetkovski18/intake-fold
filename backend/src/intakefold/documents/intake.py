import hashlib
import re
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from intakefold.audit.records import record_audit_event
from intakefold.clock import Clock
from intakefold.db.models import Batch, BatchSource, Document, DocumentStatus, new_id
from intakefold.documents.checks import UploadRefused, check_upload
from intakefold.documents.storage import Storage
from intakefold.jobs.queue import enqueue
from intakefold.settings import Settings

log = structlog.get_logger()

PROCESS_DOCUMENT = "process_document"
FILENAME_LENGTH = 255
UNSAFE_FILENAME_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Refused:
    filename: str
    code: str
    detail: str


@dataclass(frozen=True)
class Stored:
    """Checked and on disk, with no database row yet."""

    filename: str
    sha256: str
    media_type: str
    size_bytes: int
    page_count: int
    storage_key: str


@dataclass(frozen=True)
class Accepted:
    filename: str
    document_id: uuid.UUID
    deduplicated: bool


Prepared = Refused | Stored | Accepted
FileResult = Refused | Accepted


def display_filename(raw: str | None) -> str:
    """For showing to people only. It never becomes part of a path."""
    name = re.split(r"[/\\]", raw or "")[-1]
    return UNSAFE_FILENAME_CHARACTERS.sub("", name).strip()[:FILENAME_LENGTH] or "unnamed"


def prepare_file(
    engine: Engine, storage: Storage, settings: Settings, *, raw_filename: str | None, data: bytes
) -> Prepared:
    """Checks and stores one file. This is slow, so it runs outside any transaction."""
    filename = display_filename(raw_filename)
    sha256 = hashlib.sha256(data).hexdigest()
    existing = find_by_sha256(engine, sha256)
    if existing is not None:
        return Accepted(filename, existing, deduplicated=True)
    try:
        checked = check_upload(data, settings)
    except UploadRefused as refused:
        log.info("upload_refused", code=refused.code, size_bytes=len(data))
        return Refused(filename, refused.code, refused.detail)

    key = storage.new_original_key()
    storage.write(key, checked.content)
    return Stored(filename, sha256, checked.media_type, len(data), checked.page_count, key)


def find_by_sha256(engine: Engine, sha256: str) -> uuid.UUID | None:
    with Session(engine) as session:
        return session.scalar(select(Document.id).where(Document.sha256 == sha256))


def record_batch(
    engine: Engine,
    storage: Storage,
    clock: Clock,
    settings: Settings,
    *,
    user_id: uuid.UUID,
    prepared: list[Prepared],
) -> tuple[uuid.UUID | None, list[FileResult]]:
    """Commits documents and their jobs together, so a document always has its job."""
    results: list[FileResult] = []
    batch_id: uuid.UUID | None = None
    discarded: list[str] = []
    with Session(engine) as session, session.begin():
        if any(isinstance(item, Stored) for item in prepared):
            batch_id = new_id()
            session.add(
                Batch(
                    id=batch_id,
                    created_by=user_id,
                    source=BatchSource.UPLOAD,
                    doc_cap=settings.max_batch_files,
                    token_cap=settings.batch_token_cap,
                )
            )
            session.flush()
        for item in prepared:
            if not isinstance(item, Stored):
                results.append(item)
                continue
            assert batch_id is not None  # noqa: S101 - set above whenever an item is Stored
            document_id = insert_document(session, clock, batch_id, item, user_id)
            if document_id is None:
                # Another upload of the same bytes won the race; the unique index decided.
                discarded.append(item.storage_key)
                winner = session.scalar(select(Document.id).where(Document.sha256 == item.sha256))
                assert winner is not None  # noqa: S101 - the conflict means the row exists
                results.append(Accepted(item.filename, winner, deduplicated=True))
            else:
                results.append(Accepted(item.filename, document_id, deduplicated=False))
    for key in discarded:
        storage.delete(key)
    return batch_id, results


def insert_document(
    session: Session, clock: Clock, batch_id: uuid.UUID, item: Stored, user_id: uuid.UUID
) -> uuid.UUID | None:
    document_id = session.scalar(
        insert(Document)
        .values(
            id=new_id(),
            batch_id=batch_id,
            sha256=item.sha256,
            original_filename=item.filename,
            media_type=item.media_type,
            size_bytes=item.size_bytes,
            page_count=item.page_count,
            storage_key=item.storage_key,
            status=DocumentStatus.QUEUED,
            received_at=clock.now(),
        )
        .on_conflict_do_nothing(index_elements=[Document.sha256])
        .returning(Document.id)
    )
    if document_id is None:
        return None
    enqueue(
        session,
        kind=PROCESS_DOCUMENT,
        idempotency_key=f"{PROCESS_DOCUMENT}:{document_id}",
        payload={"document_id": str(document_id)},
        clock=clock,
    )
    record_audit_event(
        session, document_id=document_id, actor_user_id=user_id, action="document_uploaded"
    )
    return document_id
