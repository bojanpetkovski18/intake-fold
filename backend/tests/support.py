from datetime import UTC, date, datetime, timedelta

from intakefold.db.models import ExtractionOutcome
from intakefold.extraction.schema import ExtractedDocument
from intakefold.extraction.types import DocumentInput, ExtractionResult


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


class CompromisedExtractor:
    """Behaves like a model an injected document has fooled: confident, and hiding the attack."""

    name = "compromised"

    def extract(self, document: DocumentInput) -> ExtractionResult:
        data = ExtractedDocument(
            document_type="invoice",
            vendor_name="Attacker Invented Vendor",
            invoice_number="INV-666",
            issue_date=date(2026, 1, 1),
            due_date=None,
            currency="USD",
            subtotal="100.00",
            tax_total="0.00",
            adjustments_total="0.00",
            total="0.01",
            line_items=[],
            overall_confidence="high",
            uncertain_fields=[],
            contains_embedded_instructions=False,
        )
        return ExtractionResult(ExtractionOutcome.SUCCEEDED, self.name, data=data)
