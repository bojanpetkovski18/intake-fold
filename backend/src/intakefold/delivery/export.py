"""CSV of approved invoices. Read in SQL, written as it is read."""

import csv
import io
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from intakefold.db.models import Document, DocumentStatus, Invoice, LineItem
from intakefold.validation.rules import amount_text

APPROVED = (DocumentStatus.APPROVED, DocumentStatus.AUTO_APPROVED)
# A spreadsheet runs a cell that starts with one of these as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
HEADER = (
    "document_id",
    "approved_at",
    "vendor_name",
    "invoice_number",
    "issue_date",
    "due_date",
    "currency",
    "subtotal",
    "tax_total",
    "adjustments_total",
    "total",
    "line_position",
    "line_description",
    "line_quantity",
    "line_unit_price",
    "line_amount",
)
BATCH_ROWS = 500


def safe_text(value: str | None) -> str:
    """Text only. Money is written from Decimal and never passes here, so -5.00 stays a number."""
    if value is None:
        return ""
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def number(value: Decimal | None) -> str:
    return "" if value is None else amount_text(value)


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def export_rows(engine: Engine, start: date | None, end: date | None) -> Iterator[str]:
    """Yields CSV text in chunks. `end` is inclusive, by approval date in UTC."""
    statement = (
        select(Document, Invoice, LineItem)
        .join(Invoice, Invoice.document_id == Document.id)
        .outerjoin(LineItem, LineItem.invoice_id == Invoice.id)
        .where(Document.status.in_(APPROVED))
        .order_by(Document.finished_at, Document.id, LineItem.position)
        .execution_options(yield_per=BATCH_ROWS)
    )
    if start is not None:
        statement = statement.where(Document.finished_at >= day_start(start))
    if end is not None:
        statement = statement.where(Document.finished_at < day_start(end + timedelta(days=1)))

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(HEADER)
    with Session(engine) as session:
        for count, (document, invoice, joined) in enumerate(session.execute(statement), start=1):
            # An outer join: an invoice with no line items still gets its one row.
            line = cast(LineItem | None, joined)
            writer.writerow(
                (
                    str(document.id),
                    document.finished_at.isoformat() if document.finished_at else "",
                    safe_text(invoice.vendor_name),
                    safe_text(invoice.invoice_number),
                    invoice.issue_date.isoformat() if invoice.issue_date else "",
                    invoice.due_date.isoformat() if invoice.due_date else "",
                    safe_text(invoice.currency),
                    number(invoice.subtotal),
                    number(invoice.tax_total),
                    number(invoice.adjustments_total),
                    number(invoice.total),
                    str(line.position) if line is not None else "",
                    safe_text(line.description) if line is not None else "",
                    number(line.quantity) if line is not None else "",
                    number(line.unit_price) if line is not None else "",
                    number(line.amount) if line is not None else "",
                )
            )
            if count % BATCH_ROWS == 0:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()
    yield buffer.getvalue()
