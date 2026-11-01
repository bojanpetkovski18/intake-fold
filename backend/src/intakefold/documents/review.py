"""What a reviewer can do to a document. Every change is versioned and audited."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from intakefold.audit.records import record_audit_event
from intakefold.clock import Clock
from intakefold.db.models import (
    Confidence,
    Document,
    DocumentStatus,
    DocumentType,
    Invoice,
    LineItem,
    RuleOutcome,
    RuleResult,
)
from intakefold.settings import Settings
from intakefold.validation.apply import evaluate
from intakefold.validation.normalize import normalize_invoice_number, normalize_vendor
from intakefold.validation.rules import (
    DATE_PLAUSIBLE,
    KNOWN_VENDOR,
    LINE_ITEMS_TOTAL,
    NOT_DUPLICATE,
    REQUIRED_FIELDS,
    TOTAL_RECONCILES,
)

log = structlog.get_logger()

SCALAR_FIELDS = (
    "document_type",
    "vendor_name",
    "invoice_number",
    "issue_date",
    "due_date",
    "currency",
    "subtotal",
    "tax_total",
    "adjustments_total",
    "total",
)
LINE_FIELDS = ("description", "quantity", "unit_price", "amount")
RULE_FIELDS = {
    REQUIRED_FIELDS: (),  # Depends on what is missing, so see fields_of_rule.
    LINE_ITEMS_TOTAL: ("line_items", "subtotal"),
    TOTAL_RECONCILES: ("subtotal", "tax_total", "adjustments_total", "total"),
    DATE_PLAUSIBLE: ("issue_date", "due_date"),
    NOT_DUPLICATE: ("vendor_name", "invoice_number"),
    KNOWN_VENDOR: ("vendor_name",),
}


class DocumentNotFound(Exception):
    pass


class VersionConflict(Exception):
    pass


class NotReviewable(Exception):
    pass


class OverrideRequired(Exception):
    pass


class NothingToApprove(Exception):
    pass


@dataclass(frozen=True)
class CorrectedLine:
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None


@dataclass(frozen=True)
class Correction:
    document_type: DocumentType
    vendor_name: str | None
    invoice_number: str | None
    issue_date: date | None
    due_date: date | None
    currency: str | None
    subtotal: Decimal | None
    tax_total: Decimal | None
    adjustments_total: Decimal | None
    total: Decimal | None
    line_items: tuple[CorrectedLine, ...]


@dataclass(frozen=True)
class ReviewRecord:
    document: Document
    invoice: Invoice | None
    lines: list[LineItem]
    rules: list[RuleResult]


def fields_of_rule(rule: str, invoice: Invoice) -> tuple[str, ...]:
    if rule != REQUIRED_FIELDS:
        return RULE_FIELDS.get(rule, ())
    required = ["vendor_name", "issue_date", "currency", "total"]
    if invoice.document_type is DocumentType.INVOICE:
        required.append("invoice_number")
    return tuple(name for name in required if getattr(invoice, name) in (None, ""))


def load_review(engine: Engine, document_id: uuid.UUID) -> ReviewRecord:
    with Session(engine) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNotFound
        invoice = session.scalar(select(Invoice).where(Invoice.document_id == document_id))
        lines: list[LineItem] = []
        if invoice is not None:
            lines = list(
                session.scalars(
                    select(LineItem)
                    .where(LineItem.invoice_id == invoice.id)
                    .order_by(LineItem.position)
                )
            )
        rules = list(
            session.scalars(
                select(RuleResult)
                .where(RuleResult.document_id == document_id)
                .order_by(RuleResult.id)
            )
        )
        return ReviewRecord(document, invoice, lines, rules)


def lock_for_review(session: Session, document_id: uuid.UUID, version: int) -> Document:
    document = session.get(Document, document_id, with_for_update=True)
    if document is None:
        raise DocumentNotFound
    if document.version != version:
        raise VersionConflict
    if document.status is not DocumentStatus.NEEDS_REVIEW:
        raise NotReviewable
    return document


def audit_text(value: object) -> str | None:
    return None if value is None else str(value)


def apply_scalars(
    session: Session, invoice: Invoice, correction: Correction, actor: uuid.UUID
) -> bool:
    changed = False
    for name in SCALAR_FIELDS:
        old, new = getattr(invoice, name), getattr(correction, name)
        if old == new:  # Decimal equality: 110.0000 to 110.00 is not a correction.
            continue
        setattr(invoice, name, new)
        changed = True
        record_audit_event(
            session,
            document_id=invoice.document_id,
            actor_user_id=actor,
            action="field_corrected",
            field=name,
            old_value=audit_text(old),
            new_value=audit_text(new),
        )
    return changed


def apply_lines(
    session: Session,
    invoice: Invoice,
    lines: list[LineItem],
    corrected: tuple[CorrectedLine, ...],
    actor: uuid.UUID,
) -> bool:
    changed = False
    for index in range(max(len(lines), len(corrected))):
        old = lines[index] if index < len(lines) else None
        new = corrected[index] if index < len(corrected) else None
        for name in LINE_FIELDS:
            before = getattr(old, name) if old is not None else None
            after = getattr(new, name) if new is not None else None
            if before == after:
                continue
            changed = True
            record_audit_event(
                session,
                document_id=invoice.document_id,
                actor_user_id=actor,
                action="field_corrected",
                field=f"line_items[{index + 1}].{name}",
                old_value=audit_text(before),
                new_value=audit_text(after),
            )
    if changed:
        session.execute(delete(LineItem).where(LineItem.invoice_id == invoice.id))
        session.flush()
        session.add_all(
            LineItem(
                invoice_id=invoice.id,
                position=position,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
            )
            for position, line in enumerate(corrected, start=1)
        )
    return changed


def correct_document(
    engine: Engine,
    clock: Clock,
    settings: Settings,
    *,
    document_id: uuid.UUID,
    version: int,
    correction: Correction,
    actor: uuid.UUID,
) -> None:
    """Saves changes and re-runs the rules. The status stays: only a person approves."""
    with Session(engine) as session, session.begin():
        document = lock_for_review(session, document_id, version)
        invoice = session.scalar(select(Invoice).where(Invoice.document_id == document_id))
        if invoice is None:
            # The extraction failed, so the reviewer is typing the fields in.
            invoice = Invoice(
                document_id=document_id,
                document_type=correction.document_type,
                overall_confidence=Confidence.LOW,
                contains_embedded_instructions=False,
            )
            session.add(invoice)
            session.flush()
        lines = list(
            session.scalars(
                select(LineItem)
                .where(LineItem.invoice_id == invoice.id)
                .order_by(LineItem.position)
            )
        )
        scalars_changed = apply_scalars(session, invoice, correction, actor)
        lines_changed = apply_lines(session, invoice, lines, correction.line_items, actor)
        if not scalars_changed and not lines_changed:
            return
        invoice.normalized_vendor = (
            normalize_vendor(invoice.vendor_name) if invoice.vendor_name else None
        )
        invoice.normalized_invoice_number = (
            normalize_invoice_number(invoice.invoice_number) if invoice.invoice_number else None
        )
        session.flush()
        decision = evaluate(session, clock, settings, document_id, invoice)
        document.status_reasons = decision.reasons
        document.version += 1
    log.info("document_corrected", document_id=str(document_id))


def approve_document(
    engine: Engine,
    clock: Clock,
    *,
    document_id: uuid.UUID,
    version: int,
    override_reason: str | None,
    actor: uuid.UUID,
) -> None:
    with Session(engine) as session, session.begin():
        document = lock_for_review(session, document_id, version)
        invoice = session.scalar(select(Invoice.id).where(Invoice.document_id == document_id))
        if invoice is None:
            raise NothingToApprove
        failed = session.scalars(
            select(RuleResult.id).where(
                RuleResult.document_id == document_id, RuleResult.outcome == RuleOutcome.FAIL
            )
        ).first()
        if failed is not None and not override_reason:
            raise OverrideRequired
        document.status = DocumentStatus.APPROVED
        document.finished_at = clock.now()
        document.version += 1
        record_audit_event(
            session,
            document_id=document_id,
            actor_user_id=actor,
            action="document_approved",
            field="override_reason" if failed is not None else None,
            new_value=override_reason if failed is not None else None,
        )
    log.info("document_approved", document_id=str(document_id), overridden=failed is not None)


def reject_document(
    engine: Engine,
    clock: Clock,
    *,
    document_id: uuid.UUID,
    version: int,
    reason: str,
    actor: uuid.UUID,
) -> None:
    with Session(engine) as session, session.begin():
        document = lock_for_review(session, document_id, version)
        document.status = DocumentStatus.REJECTED
        document.finished_at = clock.now()
        document.version += 1
        record_audit_event(
            session,
            document_id=document_id,
            actor_user_id=actor,
            action="document_rejected",
            field="reason",
            new_value=reason,
        )
    log.info("document_rejected", document_id=str(document_id))
