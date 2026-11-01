import uuid
from functools import partial

import structlog
from sqlalchemy import Engine, String, cast, func, update
from sqlalchemy.orm import Session

from intakefold.audit.records import run_step
from intakefold.clock import Clock
from intakefold.db.models import Document, DocumentStatus, Job, JobStatus
from intakefold.documents.intake import PROCESS_DOCUMENT
from intakefold.documents.rendering import RenderFailed, render_pages
from intakefold.documents.storage import Storage
from intakefold.jobs.queue import ClaimedJob
from intakefold.worker.loop import Handler, PermanentJobError

log = structlog.get_logger()

RESUMABLE = (DocumentStatus.QUEUED, DocumentStatus.PROCESSING)


def build_handlers(engine: Engine, storage: Storage, clock: Clock) -> dict[str, Handler]:
    return {PROCESS_DOCUMENT: partial(process_document, engine, storage, clock)}


def process_document(engine: Engine, storage: Storage, clock: Clock, job: ClaimedJob) -> None:
    document_id = uuid.UUID(str(job.payload["document_id"]))
    with Session(engine) as session, session.begin():
        document = session.get(Document, document_id, with_for_update=True)
        if document is None:
            raise PermanentJobError("document_not_found")
        if document.status not in RESUMABLE:
            log.info("document_already_finished", document_id=str(document_id))
            return
        document.status = DocumentStatus.PROCESSING
        storage_key, media_type = document.storage_key, document.media_type
        page_count = document.page_count or 0

    with run_step(
        engine,
        clock,
        document_id=document_id,
        job_id=job.id,
        attempt=job.attempts,
        step="render",
    ):
        try:
            pages = render_pages(storage.read(storage_key), media_type, page_count)
            for number, page in enumerate(pages, start=1):
                storage.write(storage.page_key(document_id, number), page)
        except RenderFailed:
            raise PermanentJobError("render_failed") from None

    # M6 replaces this step with extraction, and the document stays `processing` until then.
    with run_step(
        engine,
        clock,
        document_id=document_id,
        job_id=job.id,
        attempt=job.attempts,
        step="extract_placeholder",
    ):
        pass


def fail_documents_of_dead_jobs(engine: Engine, clock: Clock) -> None:
    """One path for every way a job dies, including a worker killed on its last attempt."""
    statement = (
        update(Document)
        .where(
            Document.status.in_(RESUMABLE),
            Job.kind == PROCESS_DOCUMENT,
            Job.status == JobStatus.DEAD,
            Job.payload["document_id"].astext == cast(Document.id, String),
        )
        .values(
            status=DocumentStatus.FAILED,
            status_reasons=func.jsonb_build_array(Job.last_error),
            finished_at=clock.now(),
        )
    )
    with engine.begin() as connection:
        failed = connection.execute(statement).rowcount
    if failed:
        log.warning("documents_failed", count=failed)
