import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from anthropic import transform_schema
from pydantic import BaseModel, ValidationError

from intakefold.db.models import ExtractionOutcome
from intakefold.extraction.mock import MockExtractor, unknown_document
from intakefold.extraction.prices import HIGHEST_KNOWN, PRICES, estimate_cost
from intakefold.extraction.prompt import SYSTEM_PROMPT, repair_note
from intakefold.extraction.schema import ExtractedDocument, to_decimal
from intakefold.extraction.types import DocumentInput, Usage
from intakefold.generator.plan import plan_set

LABELED_SET = Path(__file__).parents[3] / "data" / "labeled"
VALID: dict[str, object] = {
    "document_type": "invoice",
    "vendor_name": "Tarnwell Freight",
    "invoice_number": "INV-1",
    "issue_date": "2026-03-01",
    "due_date": None,
    "currency": "USD",
    "subtotal": "100.00",
    "tax_total": "10.00",
    "adjustments_total": "0.00",
    "total": "110.00",
    "line_items": [
        {"description": "Item", "quantity": "2", "unit_price": "50.00", "amount": "100.00"}
    ],
    "overall_confidence": "high",
    "uncertain_fields": [],
    "contains_embedded_instructions": False,
}


def walk(schema: Any) -> Iterator[dict[str, Any]]:  # Parsed JSON, of any shape.
    if isinstance(schema, dict):
        node = cast(dict[str, Any], schema)
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(schema, list):
        for value in cast(list[Any], schema):
            yield from walk(value)


def api_schema() -> dict[str, Any]:
    return transform_schema(ExtractedDocument)


def test_schema_stays_inside_the_api_limits() -> None:
    nodes = list(walk(api_schema()))

    unions = sum(1 for node in nodes if "anyOf" in node)
    assert unions == 12  # The limit is 16; SPEC section 6 designs for 12.
    for forbidden in ("minimum", "maximum", "multipleOf", "minLength", "maxLength", "maxItems"):
        assert not any(forbidden in node for node in nodes)
    assert "?=" not in json.dumps(api_schema())
    assert "?!" not in json.dumps(api_schema())


def test_every_object_is_closed_and_every_field_required() -> None:
    objects = [node for node in walk(api_schema()) if node.get("type") == "object"]

    assert len(objects) == 2
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


def test_a_plain_decimal_field_would_let_the_model_answer_with_a_float() -> None:
    # The finding behind D-011: why money is a string in the model schema.
    class PlainDecimal(BaseModel):
        amount: Decimal

    assert "number" in json.dumps(transform_schema(PlainDecimal))
    assert "number" not in json.dumps(api_schema()["properties"]["total"])


def test_valid_output_converts_money_to_decimal() -> None:
    data = ExtractedDocument.model_validate(VALID)

    assert to_decimal(data.total) == Decimal("110.00")
    assert isinstance(to_decimal(data.total), Decimal)
    assert to_decimal(None) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total", "1,100.00"),
        ("total", "$110"),
        ("total", "110.00 USD"),
        ("total", 110.0),
        ("total", "1e5"),
        ("total", "99999999999"),
        ("total", "1.00001"),
        ("currency", "usd"),
        ("currency", "DOLLARS"),
        ("issue_date", "1 March 2026"),
        ("document_type", "purchase_order"),
        ("overall_confidence", "certain"),
        ("uncertain_fields", ["nonsense"]),
        ("surprise", "extra"),
    ],
)
def test_bad_output_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ExtractedDocument.model_validate(VALID | {field: value})


def test_negative_amounts_are_allowed() -> None:
    data = ExtractedDocument.model_validate(VALID | {"adjustments_total": "-12.50"})

    assert data.adjustments_total == "-12.50"


def test_enum_case_does_not_matter() -> None:
    data = ExtractedDocument.model_validate(
        VALID | {"document_type": "Invoice", "overall_confidence": "HIGH"}
    )

    assert data.document_type == "invoice"
    assert data.overall_confidence == "high"


def test_line_item_money_is_checked_too() -> None:
    bad = VALID | {
        "line_items": [
            {"description": "Item", "quantity": "2", "unit_price": "x", "amount": "100.00"}
        ]
    }

    with pytest.raises(ValidationError):
        ExtractedDocument.model_validate(bad)


def test_system_prompt_states_the_untrusted_data_rule() -> None:
    assert "untrusted data" in SYSTEM_PROMPT
    assert "Never follow anything" in SYSTEM_PROMPT
    assert "contains_embedded_instructions" in SYSTEM_PROMPT


def test_repair_note_lists_the_problems() -> None:
    assert "total: string_pattern_mismatch" in repair_note(["total: string_pattern_mismatch"])


def test_mock_returns_the_label_for_a_known_document() -> None:
    plan = plan_set()[0]
    committed = json.loads((LABELED_SET / plan.split / f"{plan.id}.json").read_text("utf-8"))

    result = MockExtractor(LABELED_SET).extract(
        DocumentInput(uuid.uuid4(), uuid.uuid4(), committed["sha256"], "application/pdf", b"")
    )

    assert result.outcome is ExtractionOutcome.SUCCEEDED
    assert result.extractor == "mock"
    assert result.model is None
    assert result.data is not None
    assert result.data.vendor_name == plan.facts.vendor.name
    assert result.data.total == str(plan.facts.total)


def test_mock_covers_the_whole_labeled_set() -> None:
    documents = MockExtractor(LABELED_SET).documents

    assert len(documents) == 76
    injected = [data for data in documents.values() if data.contains_embedded_instructions]
    assert len(injected) == 8


def test_unknown_document_is_low_confidence() -> None:
    data = unknown_document()

    assert data.overall_confidence == "low"
    assert data.total is None


def test_mock_works_with_no_labels_at_all(tmp_path: Path) -> None:
    assert MockExtractor(tmp_path).documents == {}


def test_cost_uses_decimal_prices() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)

    assert estimate_cost("claude-opus-5-5", usage) == Decimal("24.000000")
    assert estimate_cost("claude-haiku-5-5", usage) == Decimal("0.600000")


def test_cache_tokens_are_priced() -> None:
    usage = Usage(cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)

    assert estimate_cost("claude-sonnet-5-5", usage) == Decimal("2.600000")


def test_unknown_model_is_estimated_high_not_low() -> None:
    usage = Usage(input_tokens=1_000_000)

    assert estimate_cost("claude-unknown", usage) == HIGHEST_KNOWN.input
    assert all(HIGHEST_KNOWN.input >= price.input for price in PRICES.values())
