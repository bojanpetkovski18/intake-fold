"""Dated prices per million tokens, from the pricing page. Estimates, not invoices."""

from dataclasses import dataclass
from decimal import Decimal

import structlog

from intakefold.extraction.types import Usage

log = structlog.get_logger()

PRICES_AS_OF = "2026-11-01"
PER_TOKENS = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal


PRICES = {
    "claude-opus-5-5": Price(Decimal("4"), Decimal("20"), Decimal("0.20"), Decimal("5")),
    "claude-sonnet-5-5": Price(Decimal("2"), Decimal("10"), Decimal("0.10"), Decimal("2.50")),
    # The rates for prompts up to 100K tokens, which MAX_INPUT_TOKENS_PER_DOC keeps below.
    "claude-haiku-5-5": Price(Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125")),
}
# A fallback can serve from a model not listed here, so estimate high rather than low.
HIGHEST_KNOWN = Price(Decimal("10"), Decimal("50"), Decimal("1"), Decimal("12.50"))


def estimate_cost(model: str, usage: Usage) -> Decimal:
    price = PRICES.get(model)
    if price is None:
        log.warning("price_unknown", model=model)
        price = HIGHEST_KNOWN
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    )
    return (total / PER_TOKENS).quantize(Decimal("0.000001"))
