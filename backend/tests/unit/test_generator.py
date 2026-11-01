import hashlib
import json
import random
from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from intakefold.documents.checks import check_upload
from intakefold.generator.__main__ import GeneratedDocument, generate, write_set
from intakefold.generator.labels import build_label, expected_reasons, fields_label
from intakefold.generator.plan import (
    DEFAULT_SEED,
    DEVELOPMENT,
    HELD_OUT,
    INJECTION,
    DocumentPlan,
    Scenario,
    plan_set,
)
from intakefold.generator.vendors import KNOWN_VENDORS, UNKNOWN_VENDORS, VendorProfile
from intakefold.settings import Settings

LABELED_SET = Path(__file__).parents[3] / "data" / "labeled"
# Real brands in the fields this set touches. A failure here means renaming a vendor.
BRAND_DENYLIST = (
    "quill",
    "staples",
    "office depot",
    "officemax",
    "fedex",
    "dhl",
    "ups ",
    "usps",
    "amazon",
    "walmart",
    "sysco",
    "aramark",
    "abm",
    "siemens",
    "schneider",
    "ikea",
    "culligan",
    "sodexo",
    "vistaprint",
    "uline",
    "yellowgates",
)
ALL_VENDORS = (*KNOWN_VENDORS, *UNKNOWN_VENDORS)


@pytest.fixture(scope="module")
def plans() -> list[DocumentPlan]:
    return plan_set()


@pytest.fixture(scope="module")
def documents(plans: list[DocumentPlan]) -> list[GeneratedDocument]:
    return [generate(plan) for plan in plans]


def pdf_text(pdf: bytes) -> str:
    return " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)


def compact(text: str) -> str:
    return "".join(text.split())


def test_set_has_the_promised_shape(plans: list[DocumentPlan]) -> None:
    splits = Counter(plan.split for plan in plans)

    assert splits == {DEVELOPMENT: 20, HELD_OUT: 40, INJECTION: 16}
    assert len({plan.id for plan in plans}) == 76
    assert len({plan.layout for plan in plans}) >= 5
    assert len({plan.facts.vendor.name for plan in plans}) >= 8
    assert {plan.facts.document_type for plan in plans} == {"invoice", "receipt"}
    assert {plan.file_format for plan in plans} == {"pdf", "jpeg", "png"}
    assert {"rotation", "noise", "blur", "low_contrast"} <= {
        degradation for plan in plans for degradation in plan.degradations
    }


def test_every_scenario_is_in_both_splits(plans: list[DocumentPlan]) -> None:
    main = [plan for plan in plans if plan.split != INJECTION]

    for split in (DEVELOPMENT, HELD_OUT):
        scenarios = {plan.scenario for plan in main if plan.split == split}
        assert len(scenarios) >= 8


def test_same_seed_gives_identical_labels() -> None:
    first = [build_label(plan) for plan in plan_set(7)]
    second = [build_label(plan) for plan in plan_set(7)]

    assert first == second


def test_another_seed_gives_other_labels() -> None:
    assert [build_label(p) for p in plan_set(7)] != [build_label(p) for p in plan_set(8)]


def test_same_seed_gives_identical_files(documents: list[GeneratedDocument]) -> None:
    for document in documents[:12]:
        assert generate(document.plan).content == document.content


def test_pdfs_carry_no_timestamp_of_the_run(documents: list[GeneratedDocument]) -> None:
    metadata = PdfReader(BytesIO(documents[0].pdf)).metadata

    assert metadata is not None
    assert metadata.creation_date is not None
    assert metadata.creation_date.year == 2000  # The fixed date reportlab's invariant mode writes.


def test_global_random_generator_is_untouched() -> None:
    random.seed(1)
    expected = random.random()  # noqa: S311 - not security
    random.seed(1)
    plan_set()

    assert random.random() == expected  # noqa: S311 - not security


def test_each_file_passes_the_upload_checks(documents: list[GeneratedDocument]) -> None:
    settings = Settings.model_validate({"database_url": "postgresql://unused"})

    for document in documents:
        checked = check_upload(document.content, settings)
        assert checked.media_type == document.label["media_type"]
        assert checked.page_count == 1


def test_labels_match_what_was_drawn(documents: list[GeneratedDocument]) -> None:
    for document in documents:
        text = compact(pdf_text(document.pdf))
        facts = document.plan.facts
        assert compact(facts.vendor.name) in text
        for line in facts.lines:
            assert compact(f"{line.amount:,.2f}") in text
            assert compact(line.description) in text
        assert compact(f"{facts.subtotal:,.2f}") in text
        assert compact(f"{facts.total:,.2f}") in text
        if facts.invoice_number is not None:
            assert facts.invoice_number in text
        if facts.currency is not None:
            assert facts.currency in text


def test_missing_fields_are_not_on_the_page(documents: list[GeneratedDocument]) -> None:
    missing = {
        Scenario.MISSING_INVOICE_NUMBER: ("InvoiceNo.", "invoice_number"),
        Scenario.MISSING_DATE: ("Date:", "issue_date"),
        Scenario.MISSING_CURRENCY: ("Currency", "currency"),
    }
    seen = Counter[Scenario]()
    for document in documents:
        if document.plan.scenario in missing:
            title, field = missing[document.plan.scenario]
            fields = document.label["fields"]
            assert isinstance(fields, dict)
            assert fields[field] is None
            assert title not in compact(pdf_text(document.pdf))
            seen[document.plan.scenario] += 1

    assert set(seen) == set(missing)


def test_wrong_total_is_printed_wrong(documents: list[GeneratedDocument]) -> None:
    wrong = [d for d in documents if d.plan.scenario is Scenario.WRONG_TOTAL]
    assert wrong

    for document in wrong:
        facts = document.plan.facts
        correct = facts.subtotal + facts.tax_total + facts.adjustments_total
        assert facts.total != correct
        text = compact(pdf_text(document.pdf))
        assert compact(f"{facts.total:,.2f}") in text
        assert "total_reconciles" in expected_reasons(document.plan)


def test_wrong_line_is_printed_wrong(documents: list[GeneratedDocument]) -> None:
    wrong = [d for d in documents if d.plan.scenario is Scenario.WRONG_LINE]
    assert wrong

    for document in wrong:
        line = document.plan.facts.lines[0]
        assert line.quantity * line.unit_price != line.amount
        assert compact(f"{line.amount:,.2f}") in compact(pdf_text(document.pdf))
        assert "line_items_total" in expected_reasons(document.plan)


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        (Scenario.MISSING_INVOICE_NUMBER, "required_fields"),
        (Scenario.MISSING_DATE, "required_fields"),
        (Scenario.MISSING_CURRENCY, "required_fields"),
        (Scenario.UNKNOWN_VENDOR, "known_vendor"),
        (Scenario.FUTURE_DATE, "date_plausible"),
        (Scenario.OLD_DATE, "date_plausible"),
        (Scenario.DUE_BEFORE_ISSUE, "date_plausible"),
        (Scenario.DUPLICATE, "not_duplicate"),
    ],
)
def test_each_scenario_expects_its_reason_and_only_that(
    plans: list[DocumentPlan], scenario: Scenario, reason: str
) -> None:
    matching = [plan for plan in plans if plan.scenario is scenario]

    assert matching
    assert all(expected_reasons(plan) == [reason] for plan in matching)


def test_clean_documents_expect_auto_approval(plans: list[DocumentPlan]) -> None:
    clean = [p for p in plans if p.scenario is Scenario.CLEAN and p.injection is None]

    assert clean
    assert all(expected_reasons(plan) == [] for plan in clean)
    assert all(
        build_label(plan)["expected_routing"] == {"outcome": "auto_approved", "reasons": []}
        for plan in clean
    )


def test_duplicates_point_at_an_earlier_document_in_the_same_split(
    plans: list[DocumentPlan],
) -> None:
    by_id = {plan.id: index for index, plan in enumerate(plans)}
    duplicates = [plan for plan in plans if plan.scenario is Scenario.DUPLICATE]

    assert len(duplicates) == 7
    for plan in duplicates:
        assert plan.duplicate_of is not None
        original = plans[by_id[plan.duplicate_of]]
        assert by_id[original.id] < by_id[plan.id]
        assert original.split == plan.split
        assert original.facts == plan.facts


def test_duplicates_are_different_files(documents: list[GeneratedDocument]) -> None:
    hashes = [document.label["sha256"] for document in documents]

    assert len(set(hashes)) == len(hashes)


def test_injection_pairs_differ_only_by_the_injection(
    documents: list[GeneratedDocument],
) -> None:
    pairs: dict[str, list[GeneratedDocument]] = {}
    for document in documents:
        if document.plan.pair_id is not None:
            pairs.setdefault(document.plan.pair_id, []).append(document)

    assert len(pairs) == 8
    for clean, injected in pairs.values():
        assert clean.plan.injection is None
        assert injected.plan.injection is not None
        assert clean.label["contains_embedded_instructions"] is False
        assert injected.label["contains_embedded_instructions"] is True
        assert injected.plan.injection.text not in pdf_text(clean.pdf).replace("\n", " ")
        assert compact(injected.plan.injection.text) in compact(pdf_text(injected.pdf))
        assert "embedded_instructions" in expected_reasons(injected.plan)
        assert injected.plan.duplicate_of == clean.plan.id
        assert "not_duplicate" in expected_reasons(injected.plan)
        assert "embedded_instructions" not in expected_reasons(clean.plan)
        assert clean.plan.facts.total == injected.plan.facts.total


def test_one_injection_pair_also_breaks_a_rule(plans: list[DocumentPlan]) -> None:
    both = [
        plan
        for plan in plans
        if plan.injection is not None and "total_reconciles" in expected_reasons(plan)
    ]

    assert len(both) == 1


def test_hidden_injection_stays_a_pdf(plans: list[DocumentPlan]) -> None:
    hidden = [p for p in plans if p.injection is not None and p.injection.placement == "hidden"]

    assert hidden
    assert all(plan.file_format == "pdf" for plan in hidden)


@pytest.mark.parametrize("name", [vendor.name for vendor in ALL_VENDORS])
def test_vendor_names_are_not_real_brands(name: str) -> None:
    assert not [brand for brand in BRAND_DENYLIST if brand in f"{name.lower()} "]


def test_known_and_unknown_vendors_do_not_overlap() -> None:
    assert not {v.name for v in KNOWN_VENDORS} & {v.name for v in UNKNOWN_VENDORS}
    assert len(KNOWN_VENDORS) >= 8


@pytest.mark.parametrize("vendor", ALL_VENDORS, ids=[vendor.name for vendor in ALL_VENDORS])
def test_contact_details_are_obviously_fictional(vendor: VendorProfile) -> None:
    text = str(vendor)

    assert ".example.com" in text
    assert "555 01" in text
    assert "FAKE-TAX-" in text


def test_money_on_labels_is_exact_decimal_text(plans: list[DocumentPlan]) -> None:
    for plan in plans:
        assert Decimal(str(fields_label(plan.facts)["total"])) == plan.facts.total


def test_command_writes_a_document_and_a_label_for_each(tmp_path: Path) -> None:
    count = write_set(tmp_path, DEFAULT_SEED)

    labels = list(tmp_path.glob("*/*.json"))
    assert count == 76
    assert len(labels) == 76
    label = json.loads(labels[0].read_text(encoding="utf-8"))
    assert (labels[0].parent / label["file"]).is_file()


def committed_labels() -> list[dict[str, object]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in LABELED_SET.glob("*/*.json")]


def test_committed_set_is_what_the_default_seed_produces(plans: list[DocumentPlan]) -> None:
    committed = {str(label["id"]): label for label in committed_labels()}

    assert len(committed) == len(plans)
    for plan in plans:
        expected = build_label(plan)
        assert {key: committed[plan.id][key] for key in expected} == expected


def test_committed_files_match_their_labels() -> None:
    for path in LABELED_SET.glob("*/*.json"):
        label = json.loads(path.read_text(encoding="utf-8"))
        content = (path.parent / label["file"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == label["sha256"]
