"""Creates the deliveries of an approval, inside the approval's own transaction."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from intakefold.clock import Clock
from intakefold.db.models import (
    DeliveryStatus,
    Document,
    Invoice,
    LineItem,
    WebhookDelivery,
    new_id,
)
from intakefold.jobs.queue import enqueue
from intakefold.settings import Settings
from intakefold.validation.rules import amount_text

DELIVER_WEBHOOK = "deliver_webhook"
INVOICE_APPROVED = "invoice.approved"


def money(value: Decimal | None) -> str | None:
    return None if value is None else amount_text(value)


def approved_payload(
    session: Session, document: Document, event_id: uuid.UUID, approved_by: str
) -> dict[str, object]:
    invoice = session.scalars(select(Invoice).where(Invoice.document_id == document.id)).one()
    lines = session.scalars(
        select(LineItem).where(LineItem.invoice_id == invoice.id).order_by(LineItem.position)
    )
    # Money is a string on the wire, as everywhere else in the API.
    return {
        "event_id": str(event_id),
        "type": INVOICE_APPROVED,
        "document_id": str(document.id),
        "approved_by": approved_by,
        "invoice": {
            "document_type": invoice.document_type.value,
            "vendor_name": invoice.vendor_name,
            "invoice_number": invoice.invoice_number,
            "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else None,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "currency": invoice.currency,
            "subtotal": money(invoice.subtotal),
            "tax_total": money(invoice.tax_total),
            "adjustments_total": money(invoice.adjustments_total),
            "total": money(invoice.total),
            "line_items": [
                {
                    "position": line.position,
                    "description": line.description,
                    "quantity": money(line.quantity),
                    "unit_price": money(line.unit_price),
                    "amount": money(line.amount),
                }
                for line in lines
            ],
        },
    }


def enqueue_deliveries(
    session: Session, clock: Clock, settings: Settings, document: Document, approved_by: str
) -> None:
    """Called in the approval transaction, so an approval always has its deliveries."""
    if not settings.webhook_targets:
        return
    event_id = new_id()
    payload = approved_payload(session, document, event_id, approved_by)
    for target in settings.webhook_targets:
        delivery = WebhookDelivery(
            id=new_id(),
            document_id=document.id,
            target=target.name,
            event_id=event_id,
            payload=payload,
            status=DeliveryStatus.PENDING,
        )
        session.add(delivery)
        session.flush()
        enqueue(
            session,
            kind=DELIVER_WEBHOOK,
            idempotency_key=f"{DELIVER_WEBHOOK}:{delivery.id}",
            payload={"delivery_id": str(delivery.id)},
            clock=clock,
        )
