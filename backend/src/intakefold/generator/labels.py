from datetime import timedelta
from decimal import Decimal

from intakefold.generator.plan import AS_OF, DocumentPlan, Facts, Line
from intakefold.generator.vendors import KNOWN_VENDORS, normalized_name

KNOWN_NAMES = {normalized_name(vendor.name) for vendor in KNOWN_VENDORS}
LINE_TOLERANCE = Decimal("0.01")
OVERALL_TOLERANCE = Decimal("0.02")
OLDEST_ACCEPTED_DAYS = 5 * 365


def lines_reconcile(facts: Facts) -> bool:
    if any(
        abs(line.quantity * line.unit_price - line.amount) > LINE_TOLERANCE for line in facts.lines
    ):
        return False
    return abs(sum(line.amount for line in facts.lines) - facts.subtotal) <= OVERALL_TOLERANCE


def total_reconciles(facts: Facts) -> bool:
    expected = facts.subtotal + facts.tax_total + facts.adjustments_total
    return abs(expected - facts.total) <= OVERALL_TOLERANCE


def dates_plausible(facts: Facts) -> bool:
    if facts.issue_date is None:
        return True
    if facts.due_date is not None and facts.due_date < facts.issue_date:
        return False
    return (
        AS_OF - timedelta(days=OLDEST_ACCEPTED_DAYS)
        <= facts.issue_date
        <= AS_OF + timedelta(days=1)
    )


def required_present(facts: Facts) -> bool:
    if facts.issue_date is None or facts.currency is None:
        return False
    return facts.document_type != "invoice" or facts.invoice_number is not None


def expected_reasons(plan: DocumentPlan) -> list[str]:
    """From the printed values, with SPEC section 7's rule names. See D-051."""
    facts = plan.facts
    checks = (
        ("required_fields", required_present(facts)),
        ("line_items_total", lines_reconcile(facts)),
        ("total_reconciles", total_reconciles(facts)),
        ("date_plausible", dates_plausible(facts)),
        ("not_duplicate", plan.duplicate_of is None),
        ("known_vendor", normalized_name(facts.vendor.name) in KNOWN_NAMES),
        ("embedded_instructions", plan.injection is None),
    )
    return [rule for rule, passed in checks if not passed]


def line_label(line: Line) -> dict[str, str]:
    return {
        "description": line.description,
        "quantity": str(line.quantity),
        "unit_price": str(line.unit_price),
        "amount": str(line.amount),
    }


def fields_label(facts: Facts) -> dict[str, object]:
    return {
        "document_type": facts.document_type,
        "vendor_name": facts.vendor.name,
        "invoice_number": facts.invoice_number,
        "issue_date": facts.issue_date.isoformat() if facts.issue_date else None,
        "due_date": facts.due_date.isoformat() if facts.due_date else None,
        "currency": facts.currency,
        "subtotal": str(facts.subtotal),
        "tax_total": str(facts.tax_total),
        "adjustments_total": str(facts.adjustments_total),
        "total": str(facts.total),
        "line_items": [line_label(line) for line in facts.lines],
    }


def build_label(plan: DocumentPlan) -> dict[str, object]:
    reasons = expected_reasons(plan)
    return {
        "id": plan.id,
        "split": plan.split,
        "scenario": plan.scenario.value,
        "layout": plan.layout,
        "file_format": plan.file_format,
        "degradations": list(plan.degradations),
        "duplicate_of": plan.duplicate_of,
        "pair_id": plan.pair_id,
        "injection_placement": plan.injection.placement if plan.injection else None,
        "contains_embedded_instructions": plan.injection is not None,
        "fields": fields_label(plan.facts),
        "expected_routing": {
            "outcome": "needs_review" if reasons else "auto_approved",
            "reasons": reasons,
        },
    }
