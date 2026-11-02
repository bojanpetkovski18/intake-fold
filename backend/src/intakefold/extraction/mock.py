"""Deterministic and offline. It tests plumbing and says nothing about accuracy."""

import json
from pathlib import Path

from intakefold.db.models import ExtractionOutcome
from intakefold.extraction.schema import ExtractedDocument
from intakefold.extraction.types import DocumentInput, ExtractionResult

MOCK = "mock"


def unknown_document() -> ExtractedDocument:
    return ExtractedDocument(
        document_type="other",
        vendor_name=None,
        invoice_number=None,
        issue_date=None,
        due_date=None,
        currency=None,
        subtotal=None,
        tax_total=None,
        adjustments_total=None,
        total=None,
        line_items=[],
        overall_confidence="low",
        uncertain_fields=[],
        contains_embedded_instructions=False,
    )


def read_labels(directory: Path) -> dict[str, ExtractedDocument]:
    documents: dict[str, ExtractedDocument] = {}
    for path in directory.glob("*/*.json"):
        label = json.loads(path.read_text(encoding="utf-8"))
        documents[label["sha256"]] = ExtractedDocument.model_validate(
            label["fields"]
            | {
                "overall_confidence": "high",
                "uncertain_fields": [],
                "contains_embedded_instructions": label["contains_embedded_instructions"],
            }
        )
    return documents


class MockExtractor:
    name = MOCK

    def __init__(self, labels_directory: Path) -> None:
        self.documents = read_labels(labels_directory)

    def extract(self, document: DocumentInput) -> ExtractionResult:
        data = self.documents.get(document.sha256, unknown_document())
        return ExtractionResult(
            outcome=ExtractionOutcome.SUCCEEDED,
            extractor=self.name,
            data=data,
            raw_output=data.model_dump(mode="json"),
        )
