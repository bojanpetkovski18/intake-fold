"""The rules of SPEC section 7. Pure functions: no database, no clock, no model."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from intakefold.db.models import RuleOutcome
from intakefold.settings import Settings

REQUIRED_FIELDS = "required_fields"
LINE_ITEMS_TOTAL = "line_items_total"
TOTAL_RECONCILES = "total_reconciles"
DATE_PLAUSIBLE = "date_plausible"
NOT_DUPLICATE = "not_duplicate"
KNOWN_VENDOR = "known_vendor"


@dataclass(frozen=True)
class LineFacts:
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None


@dataclass(frozen=True)
class InvoiceFacts:
    document_type: str
    vendor_name: str | None
    invoice_number: str | None
    issue_date: date | None
    due_date: date | None
    currency: str | None
    subtotal: Decimal | None
    tax_total: Decimal | None
    adjustments_total: Decimal | None
    total: Decimal | None
    lines: tuple[LineFacts, ...]


@dataclass(frozen=True)
class Thresholds:
    line_tolerance: Decimal
    total_tolerance: Decimal
    future_days: int
    max_age_days: int


@dataclass(frozen=True)
class RuleResult:
    rule: str
    outcome: RuleOutcome
    reason_code: str | None = None
    detail: str | None = None


def thresholds_from(settings: Settings) -> Thresholds:
    return Thresholds(
        line_tolerance=settings.rule_line_tolerance,
        total_tolerance=settings.rule_total_tolerance,
        future_days=settings.rule_future_days,
        max_age_days=settings.rule_max_age_days,
    )


def passed(rule: str) -> RuleResult:
    return RuleResult(rule, RuleOutcome.PASS)


def skipped(rule: str, reason_code: str) -> RuleResult:
    return RuleResult(rule, RuleOutcome.SKIP, reason_code)


def failed(rule: str, reason_code: str, detail: str) -> RuleResult:
    return RuleResult(rule, RuleOutcome.FAIL, reason_code, detail)


def required_fields(facts: InvoiceFacts) -> RuleResult:
    required: dict[str, object] = {
        "vendor_name": facts.vendor_name,
        "issue_date": facts.issue_date,
        "currency": facts.currency,
        "total": facts.total,
    }
    if facts.document_type == "invoice":
        required["invoice_number"] = facts.invoice_number
    missing = [name for name, value in required.items() if value is None or value == ""]
    if missing:
        return failed(REQUIRED_FIELDS, "missing_fields", f"Missing: {', '.join(missing)}.")
    return passed(REQUIRED_FIELDS)


def line_items_total(facts: InvoiceFacts, limits: Thresholds) -> RuleResult:
    if not facts.lines:
        return skipped(LINE_ITEMS_TOTAL, "no_line_items")
    if facts.subtotal is None:
        return skipped(LINE_ITEMS_TOTAL, "no_subtotal")
    for number, line in enumerate(facts.lines, start=1):
        if line.amount is None:
            return failed(LINE_ITEMS_TOTAL, "line_amount_missing", f"Line {number} has no amount.")
        if line.quantity is None or line.unit_price is None:
            continue
        expected = line.quantity * line.unit_price
        if abs(expected - line.amount) > limits.line_tolerance:
            return failed(
                LINE_ITEMS_TOTAL,
                "line_amount_mismatch",
                f"Line {number}: {line.quantity} x {line.unit_price} is {expected}, "
                f"not {line.amount}.",
            )
    amounts = sum((line.amount for line in facts.lines if line.amount is not None), Decimal(0))
    if abs(amounts - facts.subtotal) > limits.total_tolerance:
        return failed(
            LINE_ITEMS_TOTAL,
            "subtotal_mismatch",
            f"Line amounts sum to {amounts}, not the subtotal {facts.subtotal}.",
        )
    return passed(LINE_ITEMS_TOTAL)


def total_reconciles(facts: InvoiceFacts, limits: Thresholds) -> RuleResult:
    if facts.subtotal is None:
        return skipped(TOTAL_RECONCILES, "no_subtotal")
    if facts.total is None:
        return skipped(TOTAL_RECONCILES, "no_total")
    expected = facts.subtotal + (facts.tax_total or 0) + (facts.adjustments_total or 0)
    if abs(expected - facts.total) > limits.total_tolerance:
        return failed(
            TOTAL_RECONCILES,
            "total_mismatch",
            f"Subtotal, tax and adjustments come to {expected}, not the total {facts.total}.",
        )
    return passed(TOTAL_RECONCILES)


def date_plausible(facts: InvoiceFacts, today: date, limits: Thresholds) -> RuleResult:
    issued = facts.issue_date
    if issued is None:
        return skipped(DATE_PLAUSIBLE, "no_issue_date")
    if issued > today + timedelta(days=limits.future_days):
        return failed(DATE_PLAUSIBLE, "issue_date_future", f"Issue date {issued} is in the future.")
    if issued < today - timedelta(days=limits.max_age_days):
        return failed(DATE_PLAUSIBLE, "issue_date_old", f"Issue date {issued} is too old.")
    if facts.due_date is not None and facts.due_date < issued:
        return failed(
            DATE_PLAUSIBLE,
            "due_before_issue",
            f"Due date {facts.due_date} is before issue date {issued}.",
        )
    return passed(DATE_PLAUSIBLE)


def not_duplicate(facts: InvoiceFacts, duplicate_of: str | None) -> RuleResult:
    if facts.vendor_name is None:
        return skipped(NOT_DUPLICATE, "no_vendor")
    if duplicate_of is not None:
        return failed(NOT_DUPLICATE, "duplicate", f"Same invoice as document {duplicate_of}.")
    return passed(NOT_DUPLICATE)


def known_vendor(facts: InvoiceFacts, is_known: bool) -> RuleResult:
    if facts.vendor_name is None:
        return skipped(KNOWN_VENDOR, "no_vendor")
    if not is_known:
        return failed(KNOWN_VENDOR, "unknown_vendor", "The vendor is not on the vendor list.")
    return passed(KNOWN_VENDOR)


def run_rules(
    facts: InvoiceFacts,
    *,
    today: date,
    limits: Thresholds,
    duplicate_of: str | None,
    vendor_known: bool,
) -> list[RuleResult]:
    return [
        required_fields(facts),
        line_items_total(facts, limits),
        total_reconciles(facts, limits),
        date_plausible(facts, today, limits),
        not_duplicate(facts, duplicate_of),
        known_vendor(facts, vendor_known),
    ]
