import uuid
from functools import partial

import structlog
from sqlalchemy import Engine, String, cast, delete, func, select, update
from sqlalchemy.orm import Session

from intakefold.audit.records import run_step
from intakefold.clock import Clock
from intakefold.db.models import (
    Confidence,
    Document,
    DocumentStatus,
    DocumentType,
    Extraction,
    ExtractionOutcome,
    Invoice,
    Job,
    JobStatus,
    LineItem,
)
from intakefold.documents.intake import PROCESS_DOCUMENT
from intakefold.documents.rendering import RenderFailed, render_pages
from intakefold.documents.storage import Storage
from intakefold.extraction.prompt import PROMPT_VERSION
from intakefold.extraction.schema import SCHEMA_VERSION, ExtractedDocument, to_decimal
from intakefold.extraction.types import (
    DocumentInput,
    ExtractionRejected,
    ExtractionResult,
    Extractor,
)
from intakefold.generator.vendors import normalized_name
from intakefold.jobs.queue import ClaimedJob
from intakefold.worker.loop import Handler, PermanentJobError

log = structlog.get_logger()

RESUMABLE = (DocumentStatus.QUEUED, DocumentStatus.PROCESSING)


FAILURE_REASONS = {
    ExtractionOutcome.INVALID: "extraction_invalid",
    ExtractionOutcome.REFUSED: "extraction_refused",
    ExtractionOutcome.INPUT_TOO_LARGE: "input_too_large",
    ExtractionOutcome.BUDGET_EXCEEDED: "budget_exceeded",
}


def build_handlers(
    engine: Engine, storage: Storage, clock: Clock, extractor: Extractor
) -> dict[str, Handler]:
    return {PROCESS_DOCUMENT: partial(process_document, engine, storage, clock, extractor)}


def process_document(
    engine: Engine, storage: Storage, clock: Clock, extractor: Extractor, job: ClaimedJob
) -> None:
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
        sha256, batch_id = document.sha256, document.batch_id
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

    if already_extracted(engine, document_id):
        log.info("extraction_reused", document_id=str(document_id))
        return

    with run_step(
        engine,
        clock,
        document_id=document_id,
        job_id=job.id,
        attempt=job.attempts,
        step="extract",
    ) as details:
        try:
            result = extractor.extract(
                DocumentInput(document_id, batch_id, sha256, media_type, storage.read(storage_key))
            )
        except ExtractionRejected as error:
            raise PermanentJobError(error.code) from None
        details.extractor = result.extractor
        details.model = result.model
        if result.usage is not None:
            details.input_tokens = result.usage.input_tokens
            details.output_tokens = result.usage.output_tokens
            details.cache_read_tokens = result.usage.cache_read_tokens
            details.cache_write_tokens = result.usage.cache_write_tokens
        details.estimated_cost_usd = result.estimated_cost_usd

    store_result(engine, clock, document_id, result)


def already_extracted(engine: Engine, document_id: uuid.UUID) -> bool:
    """A redelivered job must not pay for the same extraction twice."""
    with Session(engine) as session:
        found = session.scalar(
            select(Extraction.id).where(
                Extraction.document_id == document_id,
                Extraction.outcome == ExtractionOutcome.SUCCEEDED,
                Extraction.prompt_version == PROMPT_VERSION,
            )
        )
    return found is not None


def store_result(
    engine: Engine, clock: Clock, document_id: uuid.UUID, result: ExtractionResult
) -> None:
    with Session(engine) as session, session.begin():
        attempts = session.scalar(
            select(func.count())
            .select_from(Extraction)
            .where(Extraction.document_id == document_id)
        )
        extraction = Extraction(
            document_id=document_id,
            attempt=(attempts or 0) + 1,
            extractor=result.extractor,
            model=result.model,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            outcome=result.outcome,
            raw_output=result.raw_output,
        )
        session.add(extraction)
        session.flush()
        if result.data is not None:
            replace_invoice(session, document_id, extraction.id, result.data)
            return
        # Successes wait for routing in M7. A failed extraction goes straight to a person.
        document = session.get_one(Document, document_id)
        document.status = DocumentStatus.NEEDS_REVIEW
        document.status_reasons = [FAILURE_REASONS[result.outcome]]
        document.finished_at = clock.now()


def replace_invoice(
    session: Session,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    data: ExtractedDocument,
) -> None:
    session.execute(delete(Invoice).where(Invoice.document_id == document_id))
    invoice = Invoice(
        document_id=document_id,
        extraction_id=extraction_id,
        document_type=DocumentType(data.document_type),
        vendor_name=data.vendor_name,
        invoice_number=data.invoice_number,
        issue_date=data.issue_date,
        due_date=data.due_date,
        currency=data.currency,
        subtotal=to_decimal(data.subtotal),
        tax_total=to_decimal(data.tax_total),
        adjustments_total=to_decimal(data.adjustments_total),
        total=to_decimal(data.total),
        overall_confidence=Confidence(data.overall_confidence),
        uncertain_fields=[field.value for field in data.uncertain_fields],
        contains_embedded_instructions=data.contains_embedded_instructions,
        normalized_vendor=normalized_name(data.vendor_name) if data.vendor_name else None,
        normalized_invoice_number=(
            data.invoice_number.strip().upper() if data.invoice_number else None
        ),
    )
    session.add(invoice)
    session.flush()
    session.add_all(
        LineItem(
            invoice_id=invoice.id,
            position=position,
            description=item.description,
            quantity=to_decimal(item.quantity),
            unit_price=to_decimal(item.unit_price),
            amount=to_decimal(item.amount),
        )
        for position, item in enumerate(data.line_items, start=1)
    )


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
