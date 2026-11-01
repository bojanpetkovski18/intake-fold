import json
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from conftest import ORIGIN, REVIEWER_EMAIL, REVIEWER_PASSWORD, BuildApp, https_client, sign_in
from fastapi.testclient import TestClient
from fixtures_files import pdf_bytes
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from support import CompromisedExtractor, FakeClock

from intakefold.db.models import (
    AuditEvent,
    Document,
    DocumentStatus,
    ExtractionOutcome,
    Invoice,
    Job,
    JobStatus,
    RuleOutcome,
    RuleResult,
    RunStep,
    StepStatus,
    Vendor,
)
from intakefold.documents.storage import Storage
from intakefold.extraction.mock import MockExtractor
from intakefold.extraction.schema import ExtractedDocument
from intakefold.extraction.types import DocumentInput, ExtractionResult, Extractor
from intakefold.settings import Settings
from intakefold.validation.apply import validate_document
from intakefold.worker.handlers import build_handlers, fail_documents_of_dead_jobs
from intakefold.worker.loop import Worker

pytestmark = pytest.mark.integration

LABELED_SET = Path(__file__).parents[3] / "data" / "labeled"
RULE_SETTINGS = Settings.model_validate({"database_url": "postgresql://unused"})
LABEL_DATE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
CLEAN: dict[str, Any] = {
    "document_type": "invoice",
    "vendor_name": "Tarnwell Freight",
    "invoice_number": "INV-1",
    "issue_date": date(2026, 9, 1),
    "due_date": None,
    "currency": "USD",
    "subtotal": "100.00",
    "tax_total": "10.00",
    "adjustments_total": "0.00",
    "total": "110.00",
    "line_items": [],
    "overall_confidence": "high",
    "uncertain_fields": [],
    "contains_embedded_instructions": False,
}


class Fixed:
    """Reports the same fields for every file, the way two copies of one invoice would read."""

    name = "fixed"

    def __init__(self, **changes: object) -> None:
        self.data = ExtractedDocument.model_validate(CLEAN | changes)

    def extract(self, document: DocumentInput) -> ExtractionResult:
        return ExtractionResult(ExtractionOutcome.SUCCEEDED, self.name, data=self.data)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(LABEL_DATE)


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "storage")


@pytest.fixture
def client(seeded: Engine, build: BuildApp, clock: FakeClock) -> Iterator[TestClient]:
    app = build(clock, upload_rate_limit="1000/minute")
    with https_client(app) as client:
        sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
        yield client


def worker_for(engine: Engine, storage: Storage, clock: FakeClock, extractor: Extractor) -> Worker:
    return Worker(
        engine,
        build_handlers(engine, storage, clock, extractor, RULE_SETTINGS),
        clock=clock,
        on_job_dead=partial(fail_documents_of_dead_jobs, engine, clock),
    )


def upload(client: TestClient, data: bytes) -> uuid.UUID:
    csrf = client.get("/api/auth/me").json()["csrfToken"]
    response = client.post(
        "/api/documents",
        files=[("files", ("file", data))],
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    return uuid.UUID(response.json()["files"][0]["documentId"])


def document(engine: Engine, document_id: uuid.UUID) -> Document:
    with Session(engine) as session:
        return session.get_one(Document, document_id)


def process(
    client: TestClient, engine: Engine, storage: Storage, clock: FakeClock, extractor: Extractor
) -> uuid.UUID:
    document_id = upload(client, pdf_bytes(seed=uuid.uuid4().int % 1000))
    worker_for(engine, storage, clock, extractor).run_once()
    return document_id


def test_clean_document_is_auto_approved_with_rule_results_and_a_trail(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = process(client, seeded, storage, clock, Fixed())

    row = document(seeded, document_id)
    assert row.status is DocumentStatus.AUTO_APPROVED
    assert row.status_reasons == []
    assert row.finished_at == clock.now()
    with Session(seeded) as session:
        results = session.scalars(select(RuleResult)).all()
        event = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "document_routed")
        ).one()
        step = session.scalars(select(RunStep).where(RunStep.step == "validate")).one()
        invoice = session.scalars(select(Invoice)).one()
        vendor = session.scalars(select(Vendor).where(Vendor.name == "Tarnwell Freight")).one()
    assert len(results) == 6
    assert {result.outcome for result in results} <= {RuleOutcome.PASS, RuleOutcome.SKIP}
    assert all(result.extraction_id == invoice.extraction_id for result in results)
    assert event.actor_user_id is None
    assert event.new_value == "auto_approved"
    assert step.status is StepStatus.SUCCEEDED
    assert invoice.vendor_id == vendor.id


def test_failed_rule_is_recorded_with_its_reason(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = process(client, seeded, storage, clock, Fixed(total="999.00"))

    row = document(seeded, document_id)
    assert row.status is DocumentStatus.NEEDS_REVIEW
    assert row.status_reasons == ["total_reconciles"]
    with Session(seeded) as session:
        failed = session.scalars(
            select(RuleResult).where(RuleResult.outcome == RuleOutcome.FAIL)
        ).one()
    assert failed.rule == "total_reconciles"
    assert failed.reason_code == "total_mismatch"
    assert failed.detail is not None


def test_vendor_alias_counts_as_known(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = process(client, seeded, storage, clock, Fixed(vendor_name="TARNWELL FREIGHT CO."))

    assert document(seeded, document_id).status is DocumentStatus.AUTO_APPROVED


def test_similar_vendor_name_is_not_fuzzily_matched(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = process(client, seeded, storage, clock, Fixed(vendor_name="Tarnwell Freights"))

    assert document(seeded, document_id).status_reasons == ["known_vendor"]


def test_same_vendor_and_number_is_a_duplicate(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    first = process(client, seeded, storage, clock, Fixed(invoice_number="INV-7"))
    second = process(client, seeded, storage, clock, Fixed(invoice_number="inv 7"))

    assert document(seeded, first).status is DocumentStatus.AUTO_APPROVED
    assert document(seeded, second).status_reasons == ["not_duplicate"]
    with Session(seeded) as session:
        failed = session.scalars(
            select(RuleResult).where(
                RuleResult.document_id == second, RuleResult.outcome == RuleOutcome.FAIL
            )
        ).one()
    assert str(first) in str(failed.detail)


def test_another_number_from_the_same_vendor_is_not_a_duplicate(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    process(client, seeded, storage, clock, Fixed(invoice_number="INV-7"))
    second = process(client, seeded, storage, clock, Fixed(invoice_number="INV-8"))

    assert document(seeded, second).status is DocumentStatus.AUTO_APPROVED


def test_same_number_from_another_vendor_is_not_a_duplicate(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    process(client, seeded, storage, clock, Fixed())
    second = process(client, seeded, storage, clock, Fixed(vendor_name="Morrowfen Catering"))

    assert document(seeded, second).status is DocumentStatus.AUTO_APPROVED


def test_receipts_without_a_number_compare_vendor_date_and_total(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    receipt = Fixed(document_type="receipt", invoice_number=None)
    process(client, seeded, storage, clock, receipt)
    same = process(client, seeded, storage, clock, receipt)
    other_total = process(
        client,
        seeded,
        storage,
        clock,
        Fixed(
            document_type="receipt",
            invoice_number=None,
            subtotal="200.00",
            tax_total="0.00",
            total="200.00",
        ),
    )

    assert document(seeded, same).status_reasons == ["not_duplicate"]
    assert document(seeded, other_total).status is DocumentStatus.AUTO_APPROVED


def test_a_rejected_document_does_not_count_as_a_duplicate(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    first = process(client, seeded, storage, clock, Fixed())
    with Session(seeded) as session, session.begin():
        session.get_one(Document, first).status = DocumentStatus.REJECTED

    second = process(client, seeded, storage, clock, Fixed())

    assert document(seeded, second).status is DocumentStatus.AUTO_APPROVED


def run_together(worker: Worker, barrier: threading.Barrier) -> None:
    barrier.wait()
    worker.run_once()


def test_concurrent_duplicates_flag_exactly_one(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    for round_number in range(6):
        extractor = Fixed(invoice_number=f"RACE-{round_number}")
        ids = [upload(client, pdf_bytes(seed=round_number * 10 + n)) for n in range(4)]
        workers = [worker_for(seeded, storage, clock, extractor) for _ in ids]
        barrier = threading.Barrier(len(workers))
        threads = [
            threading.Thread(target=run_together, args=(worker, barrier)) for worker in workers
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        statuses = [document(seeded, document_id).status for document_id in ids]
        assert statuses.count(DocumentStatus.AUTO_APPROVED) == 1
        assert statuses.count(DocumentStatus.NEEDS_REVIEW) == 3


def test_crash_between_extraction_and_routing_resumes_without_a_second_model_call(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    calls: list[DocumentInput] = []

    class Counting(Fixed):
        def extract(self, document: DocumentInput) -> ExtractionResult:
            calls.append(document)
            return super().extract(document)

    document_id = process(client, seeded, storage, clock, Counting())
    with Session(seeded) as session, session.begin():
        session.get_one(Document, document_id).status = DocumentStatus.PROCESSING
        session.scalars(select(Job)).one().status = JobStatus.QUEUED

    worker_for(seeded, storage, clock, Counting()).run_once()

    assert len(calls) == 1
    assert document(seeded, document_id).status is DocumentStatus.AUTO_APPROVED
    with Session(seeded) as session:
        assert len(session.scalars(select(RuleResult)).all()) == 6


def test_compromised_model_cannot_get_a_rule_breaking_document_approved(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    # The double claims high confidence, no injection, and a total of 0.01 on a 100.00 invoice.
    document_id = process(client, seeded, storage, clock, CompromisedExtractor())

    row = document(seeded, document_id)
    assert row.status is DocumentStatus.NEEDS_REVIEW
    assert "total_reconciles" in row.status_reasons
    assert "known_vendor" in row.status_reasons


def test_the_injection_flag_alone_forces_review(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = process(
        client, seeded, storage, clock, Fixed(contains_embedded_instructions=True)
    )

    row = document(seeded, document_id)
    assert row.status is DocumentStatus.NEEDS_REVIEW
    assert row.status_reasons == ["embedded_instructions"]
    with Session(seeded) as session:
        results = session.scalars(select(RuleResult)).all()
    assert all(result.outcome is not RuleOutcome.FAIL for result in results)


def labels_in_processing_order() -> list[dict[str, Any]]:
    labels = [json.loads(path.read_text(encoding="utf-8")) for path in LABELED_SET.glob("*/*.json")]
    # Originals before their duplicates, which is how the labels' routing was worked out.
    return sorted(labels, key=lambda label: (label["pair_id"] is not None, label["id"]))


def test_running_the_rules_again_does_not_flag_a_document_as_its_own_duplicate(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    # What M9 does after a correction: the document is already routed by then.
    document_id = process(client, seeded, storage, clock, Fixed())

    decision = validate_document(seeded, clock, RULE_SETTINGS, document_id)

    assert decision.status is DocumentStatus.AUTO_APPROVED
    with Session(seeded) as session:
        assert len(session.scalars(select(RuleResult)).all()) == 6


def test_every_labeled_document_routes_as_its_label_expects(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    worker = worker_for(seeded, storage, clock, MockExtractor(LABELED_SET))
    routed: dict[str, tuple[str, list[str]]] = {}

    labels = labels_in_processing_order()
    assert len(labels) == 76
    for label in labels:
        content = (LABELED_SET / label["split"] / label["file"]).read_bytes()
        document_id = upload(client, content)
        assert worker.run_once() is True
        row = document(seeded, document_id)
        routed[label["id"]] = (row.status.value, row.status_reasons)

    expected = {
        label["id"]: (label["expected_routing"]["outcome"], label["expected_routing"]["reasons"])
        for label in labels
    }
    assert routed == expected
