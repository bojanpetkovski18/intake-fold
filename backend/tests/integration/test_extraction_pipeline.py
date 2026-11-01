import json
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

import httpx2
import pytest
from anthropic import Anthropic
from conftest import ORIGIN, REVIEWER_EMAIL, REVIEWER_PASSWORD, BuildApp, https_client, sign_in
from fastapi.testclient import TestClient
from fixtures_files import pdf_bytes
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from support import CompromisedExtractor, FakeClock

from intakefold.db.models import (
    Batch,
    BatchSource,
    Document,
    DocumentStatus,
    Extraction,
    ExtractionOutcome,
    Invoice,
    Job,
    JobStatus,
    LineItem,
    RunStep,
)
from intakefold.documents.storage import Storage
from intakefold.extraction.budget import TokenBudget
from intakefold.extraction.claude import ClaudeExtractor
from intakefold.extraction.mock import MockExtractor
from intakefold.extraction.types import (
    DocumentInput,
    ExtractionRejected,
    ExtractionResult,
    Extractor,
    Usage,
)
from intakefold.settings import Settings
from intakefold.worker.handlers import build_handlers, fail_documents_of_dead_jobs
from intakefold.worker.loop import Worker

pytestmark = pytest.mark.integration

LABELED_SET = Path(__file__).parents[3] / "data" / "labeled"


@dataclass
class Scripted:
    """Returns or raises whatever the test wants, and counts calls."""

    result: ExtractionResult | Exception
    name: str = "scripted"
    calls: list[DocumentInput] = field(default_factory=list[DocumentInput])

    def extract(self, document: DocumentInput) -> ExtractionResult:
        self.calls.append(document)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "storage")


@pytest.fixture
def client(seeded: Engine, build: BuildApp, clock: FakeClock) -> Iterator[TestClient]:
    with https_client(build(clock)) as client:
        sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
        yield client


def worker_for(engine: Engine, storage: Storage, clock: FakeClock, extractor: Extractor) -> Worker:
    return Worker(
        engine,
        build_handlers(engine, storage, clock, extractor),
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


def labeled(document_id: str = "doc-002") -> tuple[bytes, dict[str, Any]]:
    path = next(LABELED_SET.glob(f"*/{document_id}.json"))
    label = json.loads(path.read_text(encoding="utf-8"))
    return (path.parent / label["file"]).read_bytes(), label


def test_mock_extraction_is_stored_as_decimal_with_line_items(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    content, label = labeled()
    document_id = upload(client, content)

    worker_for(seeded, storage, clock, MockExtractor(LABELED_SET)).run_once()

    fields = label["fields"]
    with Session(seeded) as session:
        invoice = session.scalars(select(Invoice)).one()
        items = session.scalars(select(LineItem).order_by(LineItem.position)).all()
        extraction = session.scalars(select(Extraction)).one()
        step = session.scalars(select(RunStep).where(RunStep.step == "extract")).one()
    assert invoice.document_id == document_id
    assert invoice.total == Decimal(str(fields["total"]))
    assert invoice.vendor_name == fields["vendor_name"]
    assert invoice.extraction_id == extraction.id
    assert [item.position for item in items] == list(range(1, len(items) + 1))
    assert len(items) == len(fields["line_items"])
    assert extraction.outcome is ExtractionOutcome.SUCCEEDED
    assert extraction.extractor == "mock"
    assert extraction.raw_output is not None
    assert step.extractor == "mock"
    assert step.input_tokens is None
    assert document(seeded, document_id).status is DocumentStatus.PROCESSING


def test_dedupe_keys_are_normalized(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    content, _ = labeled()
    upload(client, content)

    worker_for(seeded, storage, clock, MockExtractor(LABELED_SET)).run_once()

    with Session(seeded) as session:
        invoice = session.scalars(select(Invoice)).one()
    assert invoice.vendor_name is not None
    assert invoice.normalized_vendor == invoice.vendor_name.lower()
    assert invoice.normalized_invoice_number == invoice.invoice_number


def test_unknown_document_goes_through_as_low_confidence(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    upload(client, pdf_bytes(seed=77))

    worker_for(seeded, storage, clock, MockExtractor(LABELED_SET)).run_once()

    with Session(seeded) as session:
        invoice = session.scalars(select(Invoice)).one()
    assert invoice.overall_confidence == "low"
    assert invoice.total is None


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (ExtractionOutcome.INVALID, "extraction_invalid"),
        (ExtractionOutcome.REFUSED, "extraction_refused"),
        (ExtractionOutcome.INPUT_TOO_LARGE, "input_too_large"),
        (ExtractionOutcome.BUDGET_EXCEEDED, "budget_exceeded"),
    ],
)
def test_failed_extraction_goes_to_review_with_its_reason(
    client: TestClient,
    seeded: Engine,
    storage: Storage,
    clock: FakeClock,
    outcome: ExtractionOutcome,
    reason: str,
) -> None:
    document_id = upload(client, pdf_bytes())
    result = ExtractionResult(outcome, "scripted", model="m")

    worker_for(seeded, storage, clock, Scripted(result)).run_once()

    row = document(seeded, document_id)
    assert row.status is DocumentStatus.NEEDS_REVIEW
    assert row.status_reasons == [reason]
    assert row.finished_at is not None
    with Session(seeded) as session:
        assert session.scalars(select(Job)).one().status is JobStatus.SUCCEEDED
        assert session.scalars(select(Invoice)).all() == []
        assert session.scalars(select(Extraction)).one().outcome is outcome


def test_token_use_and_cost_reach_the_run_log(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    upload(client, pdf_bytes())
    result = ExtractionResult(
        ExtractionOutcome.REFUSED,
        "scripted",
        model="claude-opus-5-5",
        usage=Usage(1000, 200, 30, 40),
        estimated_cost_usd=Decimal("0.012345"),
    )

    worker_for(seeded, storage, clock, Scripted(result)).run_once()

    with Session(seeded) as session:
        step = session.scalars(select(RunStep).where(RunStep.step == "extract")).one()
    assert step.model == "claude-opus-5-5"
    assert (step.input_tokens, step.output_tokens) == (1000, 200)
    assert (step.cache_read_tokens, step.cache_write_tokens) == (30, 40)
    assert step.estimated_cost_usd == Decimal("0.012345")


def test_api_rejection_kills_the_job_with_its_code(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = upload(client, pdf_bytes())

    worker_for(seeded, storage, clock, Scripted(ExtractionRejected("api_401"))).run_once()

    with Session(seeded) as session:
        job = session.scalars(select(Job)).one()
    assert job.status is JobStatus.DEAD
    assert job.last_error == "api_401"
    assert job.attempts == 1
    row = document(seeded, document_id)
    assert row.status is DocumentStatus.FAILED
    assert row.status_reasons == ["api_401"]


def test_passing_failure_retries_then_the_document_fails(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = upload(client, pdf_bytes())
    scripted = Scripted(ConnectionError("down"))
    worker = worker_for(seeded, storage, clock, scripted)

    for _ in range(5):
        worker.run_once()
        clock.advance(timedelta(minutes=10))

    assert len(scripted.calls) == 5
    assert document(seeded, document_id).status is DocumentStatus.FAILED


def test_redelivered_job_reuses_a_successful_extraction(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    upload(client, pdf_bytes())
    mock = MockExtractor(LABELED_SET)
    calls: list[DocumentInput] = []
    original = mock.extract

    def counting(document: DocumentInput) -> ExtractionResult:
        calls.append(document)
        return original(document)

    mock.extract = counting
    worker = worker_for(seeded, storage, clock, mock)
    worker.run_once()
    with Session(seeded) as session, session.begin():
        job = session.scalars(select(Job)).one()
        job.status = JobStatus.QUEUED
        job.locked_by = None

    worker.run_once()

    assert len(calls) == 1
    with Session(seeded) as session:
        assert len(session.scalars(select(Extraction)).all()) == 1
        assert len(session.scalars(select(Invoice)).all()) == 1


def test_a_failed_attempt_is_tried_again_and_numbered(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = upload(client, pdf_bytes())
    failed = ExtractionResult(ExtractionOutcome.INVALID, "scripted")
    worker_for(seeded, storage, clock, Scripted(failed)).run_once()
    with Session(seeded) as session, session.begin():
        job = session.scalars(select(Job)).one()
        job.status = JobStatus.QUEUED
        session.get_one(Document, document_id).status = DocumentStatus.PROCESSING

    worker_for(seeded, storage, clock, MockExtractor(LABELED_SET)).run_once()

    with Session(seeded) as session:
        rows = session.scalars(select(Extraction).order_by(Extraction.attempt)).all()
    assert [row.attempt for row in rows] == [1, 2]
    assert rows[1].outcome is ExtractionOutcome.SUCCEEDED


def test_a_new_prompt_version_replaces_the_stored_invoice(
    client: TestClient,
    seeded: Engine,
    storage: Storage,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content, label = labeled()
    upload(client, content)
    worker = worker_for(seeded, storage, clock, MockExtractor(LABELED_SET))
    worker.run_once()
    monkeypatch.setattr("intakefold.worker.handlers.PROMPT_VERSION", "next-version")
    with Session(seeded) as session, session.begin():
        session.scalars(select(Job)).one().status = JobStatus.QUEUED

    worker.run_once()

    with Session(seeded) as session:
        assert len(session.scalars(select(Invoice)).all()) == 1
        count = len(session.scalars(select(LineItem)).all())
        latest = session.scalars(select(Extraction).order_by(Extraction.attempt.desc())).first()
    assert count == len(label["fields"]["line_items"])
    assert latest is not None
    assert latest.prompt_version == "next-version"


def test_compromised_model_output_is_stored_only_as_a_proposal(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    # M7 finishes this test once rules exist. Here: it never approves anything by itself.
    document_id = upload(client, pdf_bytes())

    worker_for(seeded, storage, clock, CompromisedExtractor()).run_once()

    row = document(seeded, document_id)
    assert row.status is DocumentStatus.PROCESSING
    with Session(seeded) as session:
        invoice = session.scalars(select(Invoice)).one()
    assert invoice.contains_embedded_instructions is False
    assert invoice.overall_confidence == "high"


def make_batch(engine: Engine, cap: int) -> uuid.UUID:
    batch_id = uuid.uuid4()
    with Session(engine) as session, session.begin():
        session.add(Batch(id=batch_id, source=BatchSource.EVAL, doc_cap=25, token_cap=cap))
    return batch_id


def batch(engine: Engine, batch_id: uuid.UUID) -> Batch:
    with Session(engine) as session:
        return session.get_one(Batch, batch_id)


def test_reservation_refuses_at_the_cap_exactly(engine: Engine) -> None:
    budget = TokenBudget(engine)
    batch_id = make_batch(engine, 100)

    assert budget.reserve(batch_id, 60) is True
    assert budget.reserve(batch_id, 41) is False
    assert budget.reserve(batch_id, 40) is True
    assert batch(engine, batch_id).tokens_used == 100


def test_settling_replaces_the_reservation_and_adds_cost(engine: Engine) -> None:
    budget = TokenBudget(engine)
    batch_id = make_batch(engine, 100)
    budget.reserve(batch_id, 60)

    budget.settle(batch_id, 60, 25, Decimal("0.5"))

    row = batch(engine, batch_id)
    assert row.tokens_used == 25
    assert row.estimated_cost_usd == Decimal("0.5")


def test_concurrent_reservations_never_pass_the_cap(engine: Engine) -> None:
    budget = TokenBudget(engine)
    batch_id = make_batch(engine, 1000)
    barrier = threading.Barrier(16)
    granted: list[bool] = []

    def reserve_some() -> None:
        barrier.wait()
        for _ in range(10):
            granted.append(budget.reserve(batch_id, 100))

    threads = [threading.Thread(target=reserve_some) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert granted.count(True) == 10
    assert batch(engine, batch_id).tokens_used == 1000


def test_token_cap_stops_real_extractor_calls(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    sent: list[str] = []

    def api(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 1000})
        sent.append(request.url.path)
        return httpx2.Response(500, json={"type": "error", "error": {"type": "api_error"}})

    anthropic_client = Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(api)),
    )
    settings = Settings.model_validate({"database_url": "postgresql://unused"})
    extractor = ClaudeExtractor(anthropic_client, settings, TokenBudget(seeded))
    document_id = upload(client, pdf_bytes())
    with Session(seeded) as session, session.begin():
        session.scalars(select(Batch)).one().token_cap = 500

    worker_for(seeded, storage, clock, extractor).run_once()

    assert sent == []
    row = document(seeded, document_id)
    assert row.status is DocumentStatus.NEEDS_REVIEW
    assert row.status_reasons == ["budget_exceeded"]
