"""Runs the rules on a stored invoice and commits the routing decision."""

import uuid
from datetime import date

import structlog
from sqlalchemy import ColumnElement, Engine, delete, func, select
from sqlalchemy.orm import Session

from intakefold.audit.records import record_audit_event
from intakefold.clock import Clock
from intakefold.db.models import Document, DocumentStatus, Invoice, LineItem, Vendor
from intakefold.db.models import RuleResult as RuleResultRow
from intakefold.settings import Settings
from intakefold.validation.normalize import normalize_vendor
from intakefold.validation.routing import Decision, Signals, route
from intakefold.validation.rules import InvoiceFacts, LineFacts, run_rules, thresholds_from

log = structlog.get_logger()

# Not counted as earlier documents: rejected ones, and any that have not been routed yet.
NOT_COMPARED = (DocumentStatus.QUEUED, DocumentStatus.PROCESSING, DocumentStatus.REJECTED)


def facts_of(invoice: Invoice, lines: list[LineItem]) -> InvoiceFacts:
    return InvoiceFacts(
        document_type=invoice.document_type.value,
        vendor_name=invoice.vendor_name,
        invoice_number=invoice.invoice_number,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        currency=invoice.currency,
        subtotal=invoice.subtotal,
        tax_total=invoice.tax_total,
        adjustments_total=invoice.adjustments_total,
        total=invoice.total,
        lines=tuple(LineFacts(line.quantity, line.unit_price, line.amount) for line in lines),
    )


def serialize_vendor(session: Session, normalized_vendor: str) -> None:
    # Held to the end of this transaction, so two copies of one invoice are routed in turn.
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(normalized_vendor, 0))))


def same_invoice(invoice: Invoice) -> ColumnElement[bool] | None:
    if invoice.normalized_invoice_number is not None:
        return Invoice.normalized_invoice_number == invoice.normalized_invoice_number
    if invoice.issue_date is None or invoice.total is None:
        return None
    return (
        Invoice.normalized_invoice_number.is_(None)
        & (Invoice.issue_date == invoice.issue_date)
        & (Invoice.total == invoice.total)
    )


def find_duplicate(session: Session, invoice: Invoice) -> uuid.UUID | None:
    match = same_invoice(invoice)
    if match is None or invoice.normalized_vendor is None:
        return None
    return session.scalar(
        select(Invoice.document_id)
        .join(Document, Document.id == Invoice.document_id)
        .where(
            Invoice.document_id != invoice.document_id,
            Invoice.normalized_vendor == invoice.normalized_vendor,
            Document.status.not_in(NOT_COMPARED),
            match,
        )
        .order_by(Document.received_at, Document.id)
        .limit(1)
    )


def known_vendor_ids(session: Session) -> dict[str, uuid.UUID]:
    known: dict[str, uuid.UUID] = {}
    for vendor in session.scalars(select(Vendor)):
        known[vendor.normalized_name] = vendor.id
        for alias in vendor.aliases:
            known[normalize_vendor(alias)] = vendor.id
    return known


def validate_document(
    engine: Engine, clock: Clock, settings: Settings, document_id: uuid.UUID
) -> Decision:
    today: date = clock.now().date()
    with Session(engine) as session, session.begin():
        document = session.get_one(Document, document_id, with_for_update=True)
        invoice = session.scalars(select(Invoice).where(Invoice.document_id == document_id)).one()
        lines = list(
            session.scalars(
                select(LineItem)
                .where(LineItem.invoice_id == invoice.id)
                .order_by(LineItem.position)
            )
        )
        if invoice.normalized_vendor is not None:
            serialize_vendor(session, invoice.normalized_vendor)

        duplicate = find_duplicate(session, invoice)
        vendor_id = known_vendor_ids(session).get(invoice.normalized_vendor or "")
        results = run_rules(
            facts_of(invoice, lines),
            today=today,
            limits=thresholds_from(settings),
            duplicate_of=str(duplicate) if duplicate else None,
            vendor_known=vendor_id is not None,
        )
        decision = route(
            results,
            Signals(
                document_type=invoice.document_type.value,
                overall_confidence=invoice.overall_confidence.value,
                uncertain_fields=tuple(invoice.uncertain_fields),
                contains_embedded_instructions=invoice.contains_embedded_instructions,
            ),
        )

        session.execute(delete(RuleResultRow).where(RuleResultRow.document_id == document_id))
        session.add_all(
            RuleResultRow(
                document_id=document_id,
                extraction_id=invoice.extraction_id,
                rule=result.rule,
                outcome=result.outcome,
                reason_code=result.reason_code,
                detail=result.detail,
            )
            for result in results
        )
        invoice.vendor_id = vendor_id
        document.status = decision.status
        document.status_reasons = decision.reasons
        document.finished_at = clock.now()
        record_audit_event(
            session,
            document_id=document_id,
            actor_user_id=None,
            action="document_routed",
            new_value=decision.status.value,
        )
    log.info("document_routed", status=decision.status.value, reasons=decision.reasons)
    return decision
