from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from intakefold.db.models import DocumentStatus, RuleOutcome
from intakefold.validation.normalize import normalize_invoice_number, normalize_vendor
from intakefold.validation.routing import Signals, route
from intakefold.validation.rules import (
    InvoiceFacts,
    LineFacts,
    RuleResult,
    Thresholds,
    date_plausible,
    known_vendor,
    line_items_total,
    not_duplicate,
    required_fields,
    run_rules,
    total_reconciles,
)

TODAY = date(2026, 6, 15)
LIMITS = Thresholds(Decimal("0.01"), Decimal("0.02"), future_days=1, max_age_days=1825)
LINE = LineFacts(Decimal(2), Decimal("50.00"), Decimal("100.00"))
FACTS = InvoiceFacts(
    document_type="invoice",
    vendor_name="Tarnwell Freight",
    invoice_number="INV-1",
    issue_date=date(2026, 3, 1),
    due_date=date(2026, 3, 31),
    currency="USD",
    subtotal=Decimal("100.00"),
    tax_total=Decimal("10.00"),
    adjustments_total=Decimal("0.00"),
    total=Decimal("110.00"),
    lines=(LINE,),
)
CLEAN_SIGNALS = Signals("invoice", "high", (), False)
money = st.decimals(min_value=-100_000, max_value=100_000, places=2)


def outcome(result: RuleResult) -> tuple[RuleOutcome, str | None]:
    return result.outcome, result.reason_code


def test_clean_invoice_passes_every_rule() -> None:
    results = run_rules(FACTS, today=TODAY, limits=LIMITS, duplicate_of=None, vendor_known=True)

    assert len(results) == 6
    assert all(result.outcome is RuleOutcome.PASS for result in results)


@pytest.mark.parametrize(
    ("change", "missing"),
    [
        ({"vendor_name": None}, "vendor_name"),
        ({"vendor_name": ""}, "vendor_name"),
        ({"issue_date": None}, "issue_date"),
        ({"currency": None}, "currency"),
        ({"total": None}, "total"),
        ({"invoice_number": None}, "invoice_number"),
    ],
)
def test_required_fields_fail(change: dict[str, None], missing: str) -> None:
    result = required_fields(replace(FACTS, **change))  # pyright: ignore[reportArgumentType]

    assert outcome(result) == (RuleOutcome.FAIL, "missing_fields")
    assert result.detail is not None
    assert missing in result.detail


def test_receipt_needs_no_number() -> None:
    receipt = replace(FACTS, document_type="receipt", invoice_number=None)

    assert required_fields(receipt).outcome is RuleOutcome.PASS


def test_a_zero_total_counts_as_present() -> None:
    assert required_fields(replace(FACTS, total=Decimal(0))).outcome is RuleOutcome.PASS


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("100.00", RuleOutcome.PASS),
        ("100.01", RuleOutcome.PASS),
        ("99.99", RuleOutcome.PASS),
        ("100.02", RuleOutcome.FAIL),
        ("99.98", RuleOutcome.FAIL),
    ],
)
def test_line_tolerance_boundary(amount: str, expected: RuleOutcome) -> None:
    value = Decimal(amount)
    facts = replace(FACTS, lines=(replace(LINE, amount=value),), subtotal=value)

    assert line_items_total(facts, LIMITS).outcome is expected


@pytest.mark.parametrize(
    ("subtotal", "expected"),
    [
        ("100.00", RuleOutcome.PASS),
        ("100.02", RuleOutcome.PASS),
        ("99.98", RuleOutcome.PASS),
        ("100.03", RuleOutcome.FAIL),
        ("99.97", RuleOutcome.FAIL),
    ],
)
def test_subtotal_tolerance_boundary(subtotal: str, expected: RuleOutcome) -> None:
    facts = replace(FACTS, subtotal=Decimal(subtotal))

    assert line_items_total(facts, LIMITS).outcome is expected


def test_line_rule_skips_without_line_items_or_subtotal() -> None:
    assert outcome(line_items_total(replace(FACTS, lines=()), LIMITS)) == (
        RuleOutcome.SKIP,
        "no_line_items",
    )
    assert outcome(line_items_total(replace(FACTS, subtotal=None), LIMITS)) == (
        RuleOutcome.SKIP,
        "no_subtotal",
    )


def test_line_without_an_amount_fails() -> None:
    facts = replace(FACTS, lines=(replace(LINE, amount=None),))

    assert outcome(line_items_total(facts, LIMITS)) == (RuleOutcome.FAIL, "line_amount_missing")


def test_line_without_quantity_is_only_summed() -> None:
    facts = replace(FACTS, lines=(replace(LINE, quantity=None),))

    assert line_items_total(facts, LIMITS).outcome is RuleOutcome.PASS


def test_many_small_line_differences_cannot_add_up_unnoticed() -> None:
    line = LineFacts(Decimal(1), Decimal("10.00"), Decimal("10.01"))
    facts = replace(FACTS, lines=(line,) * 5, subtotal=Decimal("50.00"))

    assert outcome(line_items_total(facts, LIMITS)) == (RuleOutcome.FAIL, "subtotal_mismatch")


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        ("110.00", RuleOutcome.PASS),
        ("110.02", RuleOutcome.PASS),
        ("109.98", RuleOutcome.PASS),
        ("110.03", RuleOutcome.FAIL),
        ("109.97", RuleOutcome.FAIL),
    ],
)
def test_total_tolerance_boundary(total: str, expected: RuleOutcome) -> None:
    assert total_reconciles(replace(FACTS, total=Decimal(total)), LIMITS).outcome is expected


def test_total_counts_negative_adjustments() -> None:
    facts = replace(FACTS, adjustments_total=Decimal("-10.00"), total=Decimal("100.00"))

    assert total_reconciles(facts, LIMITS).outcome is RuleOutcome.PASS


def test_missing_tax_and_adjustments_count_as_zero() -> None:
    facts = replace(FACTS, tax_total=None, adjustments_total=None, total=Decimal("100.00"))

    assert total_reconciles(facts, LIMITS).outcome is RuleOutcome.PASS


def test_total_rule_skips_without_subtotal_or_total() -> None:
    assert outcome(total_reconciles(replace(FACTS, subtotal=None), LIMITS)) == (
        RuleOutcome.SKIP,
        "no_subtotal",
    )
    assert outcome(total_reconciles(replace(FACTS, total=None), LIMITS)) == (
        RuleOutcome.SKIP,
        "no_total",
    )


@pytest.mark.parametrize(
    ("issued", "expected"),
    [
        (TODAY, (RuleOutcome.PASS, None)),
        (TODAY + timedelta(days=1), (RuleOutcome.PASS, None)),
        (TODAY + timedelta(days=2), (RuleOutcome.FAIL, "issue_date_future")),
        (TODAY - timedelta(days=1825), (RuleOutcome.PASS, None)),
        (TODAY - timedelta(days=1826), (RuleOutcome.FAIL, "issue_date_old")),
    ],
)
def test_issue_date_boundaries(issued: date, expected: tuple[RuleOutcome, str | None]) -> None:
    facts = replace(FACTS, issue_date=issued, due_date=None)

    assert outcome(date_plausible(facts, TODAY, LIMITS)) == expected


def test_due_date_may_equal_the_issue_date_but_not_precede_it() -> None:
    same = replace(FACTS, due_date=FACTS.issue_date)
    earlier = replace(FACTS, due_date=date(2026, 2, 28))

    assert date_plausible(same, TODAY, LIMITS).outcome is RuleOutcome.PASS
    assert outcome(date_plausible(earlier, TODAY, LIMITS)) == (
        RuleOutcome.FAIL,
        "due_before_issue",
    )


def test_date_rule_skips_without_an_issue_date() -> None:
    facts = replace(FACTS, issue_date=None)

    assert outcome(date_plausible(facts, TODAY, LIMITS)) == (RuleOutcome.SKIP, "no_issue_date")


def test_duplicate_rule() -> None:
    assert not_duplicate(FACTS, None).outcome is RuleOutcome.PASS
    assert outcome(not_duplicate(FACTS, "other")) == (RuleOutcome.FAIL, "duplicate")
    assert not_duplicate(replace(FACTS, vendor_name=None), "other").outcome is RuleOutcome.SKIP


def test_vendor_rule() -> None:
    assert known_vendor(FACTS, True).outcome is RuleOutcome.PASS
    assert outcome(known_vendor(FACTS, False)) == (RuleOutcome.FAIL, "unknown_vendor")
    assert known_vendor(replace(FACTS, vendor_name=None), False).outcome is RuleOutcome.SKIP


def test_thresholds_are_used_not_built_in() -> None:
    wide = replace(LIMITS, total_tolerance=Decimal("5.00"))
    facts = replace(FACTS, total=Decimal("114.00"))

    assert total_reconciles(facts, wide).outcome is RuleOutcome.PASS
    assert total_reconciles(facts, LIMITS).outcome is RuleOutcome.FAIL


def test_a_failed_rule_says_why() -> None:
    result = total_reconciles(replace(FACTS, total=Decimal("1.00")), LIMITS)

    assert result.detail == "Subtotal, tax and adjustments come to 110.00, not the total 1.00."


@given(subtotal=money, tax=money, adjustments=money)
def test_a_consistent_total_always_reconciles(
    subtotal: Decimal, tax: Decimal, adjustments: Decimal
) -> None:
    facts = replace(
        FACTS,
        subtotal=subtotal,
        tax_total=tax,
        adjustments_total=adjustments,
        total=subtotal + tax + adjustments,
    )

    assert total_reconciles(facts, LIMITS).outcome is RuleOutcome.PASS


@given(subtotal=money, tax=money, error=st.decimals(min_value="0.03", max_value=1000, places=2))
def test_a_total_off_by_more_than_the_tolerance_always_fails(
    subtotal: Decimal, tax: Decimal, error: Decimal
) -> None:
    for wrong in (subtotal + tax + error, subtotal + tax - error):
        facts = replace(
            FACTS,
            subtotal=subtotal,
            tax_total=tax,
            adjustments_total=Decimal(0),
            total=wrong,
        )
        assert total_reconciles(facts, LIMITS).outcome is RuleOutcome.FAIL


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=999),
            st.decimals(min_value=0, max_value=10_000, places=2),
        ),
        min_size=1,
        max_size=20,
    )
)
def test_correct_lines_always_sum(items: list[tuple[int, Decimal]]) -> None:
    lines = tuple(
        LineFacts(Decimal(quantity), price, quantity * price) for quantity, price in items
    )
    subtotal = sum((line.amount or Decimal(0) for line in lines), Decimal(0))

    result = line_items_total(replace(FACTS, lines=lines, subtotal=subtotal), LIMITS)

    assert result.outcome is RuleOutcome.PASS


def test_decimal_avoids_the_float_error_this_tolerance_exists_to_ignore() -> None:
    assert 0.1 + 0.2 != 0.3
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


PASSING = [RuleResult("required_fields", RuleOutcome.PASS)]
FAILING = [RuleResult("total_reconciles", RuleOutcome.FAIL, "total_mismatch", "detail")]
SKIPPED = [RuleResult("line_items_total", RuleOutcome.SKIP, "no_line_items")]


@pytest.mark.parametrize(
    ("results", "signals", "status", "reasons"),
    [
        (PASSING, CLEAN_SIGNALS, DocumentStatus.AUTO_APPROVED, []),
        (SKIPPED, CLEAN_SIGNALS, DocumentStatus.AUTO_APPROVED, []),
        (FAILING, CLEAN_SIGNALS, DocumentStatus.NEEDS_REVIEW, ["total_reconciles"]),
        (
            PASSING,
            replace(CLEAN_SIGNALS, overall_confidence="medium"),
            DocumentStatus.NEEDS_REVIEW,
            ["confidence_not_high"],
        ),
        (
            PASSING,
            replace(CLEAN_SIGNALS, overall_confidence="low"),
            DocumentStatus.NEEDS_REVIEW,
            ["confidence_not_high"],
        ),
        (
            PASSING,
            replace(CLEAN_SIGNALS, uncertain_fields=("total",)),
            DocumentStatus.NEEDS_REVIEW,
            ["uncertain_fields"],
        ),
        (
            PASSING,
            replace(CLEAN_SIGNALS, contains_embedded_instructions=True),
            DocumentStatus.NEEDS_REVIEW,
            ["embedded_instructions"],
        ),
        (
            PASSING,
            replace(CLEAN_SIGNALS, document_type="other"),
            DocumentStatus.NEEDS_REVIEW,
            ["unsupported_document_type"],
        ),
        (
            PASSING,
            replace(CLEAN_SIGNALS, document_type="receipt"),
            DocumentStatus.AUTO_APPROVED,
            [],
        ),
    ],
)
def test_route_table(
    results: list[RuleResult], signals: Signals, status: DocumentStatus, reasons: list[str]
) -> None:
    decision = route(results, signals)

    assert decision.status is status
    assert decision.reasons == reasons


def test_route_lists_every_reason() -> None:
    signals = Signals("other", "low", ("total",), True)

    assert route(FAILING, signals).reasons == [
        "total_reconciles",
        "embedded_instructions",
        "confidence_not_high",
        "uncertain_fields",
        "unsupported_document_type",
    ]


@given(
    confidence=st.sampled_from(["high", "medium", "low"]),
    uncertain=st.lists(st.sampled_from(["total", "currency"]), max_size=2),
    injected=st.booleans(),
    document_type=st.sampled_from(["invoice", "receipt", "other"]),
    rule_failed=st.booleans(),
)
def test_auto_approval_needs_every_condition(
    confidence: str,
    uncertain: list[str],
    injected: bool,
    document_type: str,
    rule_failed: bool,
) -> None:
    results = FAILING if rule_failed else PASSING
    signals = Signals(document_type, confidence, tuple(uncertain), injected)

    approved = route(results, signals).status is DocumentStatus.AUTO_APPROVED

    assert approved == (
        not rule_failed
        and confidence == "high"
        and not uncertain
        and not injected
        and document_type != "other"
    )


@pytest.mark.parametrize(
    "name", ["Tarnwell Freight", "TARNWELL  FREIGHT", " tarnwell freight ", "Tarnwell, Freight."]
)
def test_vendor_normalization(name: str) -> None:
    assert normalize_vendor(name) == "tarnwell freight"


def test_vendor_normalization_is_not_fuzzy() -> None:
    assert normalize_vendor("Tarnwell Freights") != normalize_vendor("Tarnwell Freight")


@pytest.mark.parametrize("number", ["INV-2601", "inv 2601", "INV_2601", "INV/2601", " inv.2601 "])
def test_invoice_number_normalization(number: str) -> None:
    assert normalize_invoice_number(number) == "INV2601"


def test_messages_show_amounts_the_way_people_write_them() -> None:
    stored = LineFacts(Decimal("8.0000"), Decimal("18.6000"), Decimal("155.8000"))
    facts = replace(FACTS, lines=(stored,), subtotal=Decimal("155.8000"))

    result = line_items_total(facts, LIMITS)

    assert result.detail == "Line 1: 8.00 x 18.60 is 148.80, not 155.80."


def test_messages_keep_real_precision() -> None:
    facts = replace(FACTS, total=Decimal("1234.5678"))

    result = total_reconciles(facts, LIMITS)

    assert result.detail == "Subtotal, tax and adjustments come to 110.00, not the total 1234.5678."
