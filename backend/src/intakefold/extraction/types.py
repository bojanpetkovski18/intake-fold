import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from intakefold.db.models import ExtractionOutcome
from intakefold.extraction.schema import ExtractedDocument


@dataclass(frozen=True)
class DocumentInput:
    document_id: uuid.UUID
    batch_id: uuid.UUID
    sha256: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True)
class ExtractionResult:
    """Parsed data, or a typed failure. Only SUCCEEDED carries `data`."""

    outcome: ExtractionOutcome
    extractor: str
    data: ExtractedDocument | None = None
    model: str | None = None
    usage: Usage | None = None
    estimated_cost_usd: Decimal | None = None
    repairs: int = 0
    raw_output: dict[str, object] | None = None


class ExtractionRejected(Exception):
    """The API refused the request in a way retrying cannot fix. `code` is safe to store."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Extractor(Protocol):
    name: str

    def extract(self, document: DocumentInput) -> ExtractionResult: ...
