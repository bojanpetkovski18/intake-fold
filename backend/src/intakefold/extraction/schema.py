"""What the model may return. Output is only a proposal until this validates it."""

import enum
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

SCHEMA_VERSION = "2026-11-01.1"

# Strings, because a plain Decimal field lets the model answer with a JSON number (D-011).
DECIMAL_PATTERN = r"^-?[0-9]+(\.[0-9]+)?$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"
# Fits NUMERIC(14,4). This runs after the response: the API rejects numeric constraints.
LARGEST_AMOUNT = Decimal("9999999999")
MOST_DECIMAL_PLACES = 4


def lower_text(value: object) -> object:
    # The API documents that enum casing may vary.
    return value.lower() if isinstance(value, str) else value


DecimalText = Annotated[str, Field(pattern=DECIMAL_PATTERN)]


class UncertainField(enum.StrEnum):
    DOCUMENT_TYPE = "document_type"
    VENDOR_NAME = "vendor_name"
    INVOICE_NUMBER = "invoice_number"
    ISSUE_DATE = "issue_date"
    DUE_DATE = "due_date"
    CURRENCY = "currency"
    SUBTOTAL = "subtotal"
    TAX_TOTAL = "tax_total"
    ADJUSTMENTS_TOTAL = "adjustments_total"
    TOTAL = "total"
    LINE_ITEMS = "line_items"


def check_amount(value: str | None) -> str | None:
    if value is None:
        return None
    amount = Decimal(value)
    if abs(amount) > LARGEST_AMOUNT:
        raise ValueError("the value is out of range")
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > MOST_DECIMAL_PLACES:
        raise ValueError(f"at most {MOST_DECIMAL_PLACES} decimal places are allowed")
    return value


class ExtractedLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    quantity: DecimalText | None
    unit_price: DecimalText | None
    amount: DecimalText | None

    _amounts = field_validator("quantity", "unit_price", "amount")(check_amount)


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_type: Annotated[Literal["invoice", "receipt", "other"], BeforeValidator(lower_text)]
    vendor_name: str | None
    invoice_number: str | None
    issue_date: date | None
    due_date: date | None
    currency: Annotated[str, Field(pattern=CURRENCY_PATTERN)] | None
    subtotal: DecimalText | None
    tax_total: DecimalText | None
    adjustments_total: DecimalText | None
    total: DecimalText | None
    line_items: list[ExtractedLineItem]
    overall_confidence: Annotated[Literal["high", "medium", "low"], BeforeValidator(lower_text)]
    uncertain_fields: list[UncertainField]
    contains_embedded_instructions: bool

    _amounts = field_validator("subtotal", "tax_total", "adjustments_total", "total")(check_amount)


def to_decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None
