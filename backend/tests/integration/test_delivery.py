import csv
import io
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
import uvicorn
from conftest import ORIGIN, REVIEWER_EMAIL, REVIEWER_PASSWORD, BuildApp, https_client, sign_in
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fixtures_files import pdf_bytes
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool
from support import FakeClock

from intakefold.db.models import (
    DeliveryAttempt,
    DeliveryStatus,
    Document,
    DocumentStatus,
    ExtractionOutcome,
    Job,
    JobStatus,
    Role,
    User,
    WebhookDelivery,
)
from intakefold.delivery.sender import WebhookSender
from intakefold.documents.storage import Storage
from intakefold.extraction.schema import ExtractedDocument
from intakefold.extraction.types import DocumentInput, ExtractionResult
from intakefold.jobs.dead_letters import retry_dead_job
from intakefold.settings import Settings
from intakefold.worker.handlers import build_handlers, on_job_dead
from intakefold.worker.loop import Worker
from intakefold_sink.app import build_sink

pytestmark = pytest.mark.integration

SECRET = "whsec_integration_secret_0123456789"  # noqa: S105 - fictional test secret
CLEAN: dict[str, Any] = {
    "document_type": "invoice",
    "vendor_name": "Tarnwell Freight",
    "invoice_number": "INV-1",
    "issue_date": date(2026, 9, 1),
    "due_date": None,
    "currency": "USD",
    "subtotal": "100.00",
    "tax_total": "10.00",
    "adjustments_total": "-5.00",
    "total": "105.00",
    "line_items": [
        {"description": "=HYPERLINK(1)", "quantity": "2", "unit_price": "50.00", "amount": "100.00"}
    ],
    "overall_confidence": "high",
    "uncertain_fields": [],
    "contains_embedded_instructions": False,
}


class Fixed:
    name = "fixed"

    def __init__(self, **changes: object) -> None:
        self.data = ExtractedDocument.model_validate(CLEAN | changes)

    def extract(self, document: DocumentInput) -> ExtractionResult:
        return ExtractionResult(ExtractionOutcome.SUCCEEDED, self.name, data=self.data)


class RunningSink:
    """The real sink on a real socket, so signatures and HTTP are exercised for real."""

    def __init__(self, fail_first: int) -> None:
        self.app = build_sink(SECRET, fail_first)
        self.server = uvicorn.Server(
            uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="error")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> RunningSink:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("the sink did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def url(self) -> str:
        port = self.server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/webhook"

    def events(self) -> list[dict[str, Any]]:
        return list(self.app.state.sink.received)


def settings_for(url: str) -> Settings:
    return Settings.model_validate(
        {
            "database_url": "postgresql://unused",
            "webhook_targets": [{"name": "sink", "url": url, "secret": SECRET}],
        }
    )


@pytest.fixture
def clock() -> FakeClock:
    # Real time, or the sink would refuse the signature's timestamp.
    return FakeClock(datetime.now(UTC))


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "storage")


@pytest.fixture
def http() -> Iterator[httpx2.Client]:
    with httpx2.Client(timeout=5, follow_redirects=False) as client:
        yield client


def worker(
    engine: Engine,
    storage: Storage,
    clock: FakeClock,
    settings: Settings,
    http: httpx2.Client,
    extractor: object = None,
) -> Worker:
    sender = WebhookSender(engine, clock, settings, http)
    return Worker(
        engine,
        build_handlers(engine, storage, clock, extractor or Fixed(), settings, sender),  # pyright: ignore[reportArgumentType]
        clock=clock,
        on_job_dead=partial(on_job_dead, engine, clock),
    )


def app_for(build: BuildApp, clock: FakeClock, settings: Settings) -> FastAPI:
    return build(
        clock,
        webhook_targets=[
            target.model_dump(mode="json") | {"secret": SECRET}
            for target in settings.webhook_targets
        ],
        upload_rate_limit="1000/minute",
    )


@pytest.fixture
def reviewer_for(seeded: Engine, build: BuildApp, clock: FakeClock):
    clients: list[TestClient] = []

    def make(settings: Settings) -> tuple[TestClient, str]:
        client = https_client(app_for(build, clock, settings))
        client.__enter__()
        clients.append(client)
        return client, sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def upload(actor: tuple[TestClient, str]) -> uuid.UUID:
    client, csrf = actor
    response = client.post(
        "/api/documents",
        files=[("files", ("invoice.pdf", pdf_bytes(seed=uuid.uuid4().int % 1000)))],
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    return uuid.UUID(response.json()["files"][0]["documentId"])


def deliveries(engine: Engine) -> list[WebhookDelivery]:
    with Session(engine) as session:
        return list(session.scalars(select(WebhookDelivery)))


def attempts(engine: Engine) -> list[DeliveryAttempt]:
    with Session(engine) as session:
        return list(session.scalars(select(DeliveryAttempt).order_by(DeliveryAttempt.attempt)))


def test_auto_approval_creates_a_signed_delivery_that_reaches_the_sink(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    with RunningSink(fail_first=0) as sink:
        settings = settings_for(sink.url)
        actor = reviewer_for(settings)
        document_id = upload(actor)
        loop = worker(seeded, storage, clock, settings, http)

        loop.run_once()
        assert len(deliveries(seeded)) == 1
        loop.run_once()

        received = sink.events()
    assert len(received) == 1
    payload = received[0]["payload"]
    assert payload["type"] == "invoice.approved"
    assert payload["document_id"] == str(document_id)
    assert payload["approved_by"] == "rules"
    assert payload["invoice"]["total"] == "105.00"
    assert payload["invoice"]["adjustments_total"] == "-5.00"
    [delivery] = deliveries(seeded)
    assert delivery.status is DeliveryStatus.DELIVERED
    assert received[0]["event_id"] == str(delivery.event_id)


def test_a_failing_target_is_retried_and_every_attempt_is_logged(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    with RunningSink(fail_first=2) as sink:
        settings = settings_for(sink.url)
        actor = reviewer_for(settings)
        document_id = upload(actor)
        loop = worker(seeded, storage, clock, settings, http)
        loop.run_once()

        # Past the backoff, but inside the sink's five-minute timestamp window.
        for _ in range(3):
            loop.run_once()
            clock.advance(timedelta(seconds=30))

        assert len(sink.events()) == 1
    logged = [(a.attempt, a.status_code, a.error_code) for a in attempts(seeded)]
    assert logged == [(1, 503, "http_503"), (2, 503, "http_503"), (3, 200, None)]
    assert all(a.duration_ms is not None for a in attempts(seeded))
    body = actor[0].get(f"/api/documents/{document_id}/deliveries").json()
    assert body[0]["status"] == "delivered"
    assert [item["statusCode"] for item in body[0]["attempts"]] == [503, 503, 200]


def test_a_repeat_delivery_is_not_processed_twice_by_the_sink(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    with RunningSink(fail_first=0) as sink:
        settings = settings_for(sink.url)
        upload(reviewer_for(settings))
        loop = worker(seeded, storage, clock, settings, http)
        loop.run_once()
        loop.run_once()
        [delivery] = deliveries(seeded)
        sender = WebhookSender(seeded, clock, settings, http)

        # At-least-once: the same event can arrive again, for example after a lost response.
        sender.send(delivery.id, delivery.event_id, delivery.payload, settings.webhook_targets[0])

        assert len(sink.events()) == 1
    assert len(attempts(seeded)) == 2


def test_a_target_that_never_works_ends_dead_and_the_document_stays_approved(
    seeded: Engine, storage: Storage, clock: FakeClock, reviewer_for: Any
) -> None:
    def always_down(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500)

    settings = settings_for("http://downstream.invalid/webhook")
    document_id = upload(reviewer_for(settings))
    with httpx2.Client(transport=httpx2.MockTransport(always_down)) as client:
        loop = worker(seeded, storage, clock, settings, client)
        for _ in range(6):
            loop.run_once()
            clock.advance(timedelta(minutes=10))

    [delivery] = deliveries(seeded)
    assert delivery.status is DeliveryStatus.DEAD
    assert len(attempts(seeded)) == 5
    with Session(seeded) as session:
        assert session.get_one(Document, document_id).status is DocumentStatus.AUTO_APPROVED
        job = session.scalars(select(Job).where(Job.kind == "deliver_webhook")).one()
    assert job.status is JobStatus.DEAD


def test_a_requeued_dead_delivery_is_sent_again(
    seeded: Engine, storage: Storage, clock: FakeClock, reviewer_for: Any
) -> None:
    def always_down(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500)

    def back_up(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200)

    settings = settings_for("http://downstream.invalid/webhook")
    upload(reviewer_for(settings))
    with httpx2.Client(transport=httpx2.MockTransport(always_down)) as client:
        loop = worker(seeded, storage, clock, settings, client)
        for _ in range(6):
            loop.run_once()
            clock.advance(timedelta(minutes=10))
    with Session(seeded) as session:
        job = session.scalars(select(Job).where(Job.kind == "deliver_webhook")).one()
        admin = session.scalars(select(User.id).where(User.role == Role.ADMIN)).one()

    retry_dead_job(seeded, job.id, admin, clock)
    with httpx2.Client(transport=httpx2.MockTransport(back_up)) as client:
        worker(seeded, storage, clock, settings, client).run_once()

    [delivery] = deliveries(seeded)
    assert delivery.status is DeliveryStatus.DELIVERED
    assert [attempt.status_code for attempt in attempts(seeded)] == [500] * 5 + [200]


def test_the_outbound_call_happens_with_no_database_connection_held(
    seeded: Engine, storage: Storage, clock: FakeClock, reviewer_for: Any
) -> None:
    held: list[int] = []

    def check(_: httpx2.Request) -> httpx2.Response:
        held.append(cast(QueuePool, seeded.pool).checkedout())
        return httpx2.Response(200)

    settings = settings_for("http://downstream.invalid/webhook")
    upload(reviewer_for(settings))
    with httpx2.Client(transport=httpx2.MockTransport(check)) as client:
        loop = worker(seeded, storage, clock, settings, client)
        loop.run_once()
        loop.run_once()

    assert held == [0]


def test_connection_failure_and_timeout_are_logged_by_code(
    seeded: Engine, storage: Storage, clock: FakeClock, reviewer_for: Any
) -> None:
    replies = [httpx2.ConnectError("down"), httpx2.ReadTimeout("slow")]

    def failing(request: httpx2.Request) -> httpx2.Response:
        raise replies.pop(0)

    settings = settings_for("http://downstream.invalid/webhook")
    upload(reviewer_for(settings))
    with httpx2.Client(transport=httpx2.MockTransport(failing)) as client:
        loop = worker(seeded, storage, clock, settings, client)
        loop.run_once()
        for _ in range(2):
            loop.run_once()
            clock.advance(timedelta(minutes=10))

    assert [a.error_code for a in attempts(seeded)] == ["connection_error", "timeout"]


def test_a_target_removed_from_configuration_fails_at_once(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    settings = settings_for("http://downstream.invalid/webhook")
    upload(reviewer_for(settings))
    worker(seeded, storage, clock, settings, http).run_once()
    without = Settings.model_validate({"database_url": "postgresql://unused"})

    worker(seeded, storage, clock, without, http).run_once()

    with Session(seeded) as session:
        job = session.scalars(select(Job).where(Job.kind == "deliver_webhook")).one()
    assert job.status is JobStatus.DEAD
    assert job.last_error == "unknown_target"
    assert deliveries(seeded)[0].status is DeliveryStatus.DEAD


def test_manual_approval_creates_a_delivery_in_the_same_transaction(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    settings = settings_for("http://downstream.invalid/webhook")
    actor = reviewer_for(settings)
    document_id = upload(actor)
    worker(seeded, storage, clock, settings, http, Fixed(total="999.00")).run_once()
    assert deliveries(seeded) == []

    client, csrf = actor
    response = client.post(
        f"/api/documents/{document_id}/approve",
        json={"version": 1, "overrideReason": "Checked."},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    [delivery] = deliveries(seeded)
    assert delivery.payload["approved_by"] == "reviewer"
    with Session(seeded) as session:
        job = session.scalars(select(Job).where(Job.kind == "deliver_webhook")).one()
    assert job.payload == {"delivery_id": str(delivery.id)}


def test_every_target_gets_the_same_event_id(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql://unused",
            "webhook_targets": [
                {"name": "first", "url": "http://one.invalid/hook", "secret": SECRET},
                {"name": "second", "url": "http://two.invalid/hook", "secret": SECRET},
            ],
        }
    )
    upload(reviewer_for(settings))

    worker(seeded, storage, clock, settings, http).run_once()

    found = deliveries(seeded)
    assert sorted(delivery.target for delivery in found) == ["first", "second"]
    assert len({delivery.event_id for delivery in found}) == 1


def test_a_delivered_event_is_never_sent_again(
    seeded: Engine, storage: Storage, clock: FakeClock, reviewer_for: Any
) -> None:
    calls: list[httpx2.Request] = []

    def ok(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200)

    settings = settings_for("http://downstream.invalid/webhook")
    upload(reviewer_for(settings))
    with httpx2.Client(transport=httpx2.MockTransport(ok)) as client:
        loop = worker(seeded, storage, clock, settings, client)
        loop.run_once()
        loop.run_once()
        with Session(seeded) as session, session.begin():
            session.scalars(
                select(Job).where(Job.kind == "deliver_webhook")
            ).one().status = JobStatus.QUEUED
        loop.run_once()

    assert len(calls) == 1
    assert len(attempts(seeded)) == 1


def test_no_targets_means_no_deliveries(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    settings = Settings.model_validate({"database_url": "postgresql://unused"})
    upload(reviewer_for(settings))

    worker(seeded, storage, clock, settings, http).run_once()

    assert deliveries(seeded) == []


def test_deliveries_of_a_missing_document_is_404(reviewer_for: Any) -> None:
    client, _ = reviewer_for(Settings.model_validate({"database_url": "postgresql://unused"}))

    assert client.get(f"/api/documents/{uuid.uuid4()}/deliveries").status_code == 404


def csv_rows(client: TestClient, query: str = "") -> list[dict[str, str]]:
    response = client.get(f"/api/exports/invoices.csv{query}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(response.text)))


def test_export_has_one_row_per_line_and_is_safe_to_open(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    settings = Settings.model_validate({"database_url": "postgresql://unused"})
    actor = reviewer_for(settings)
    upload(actor)
    worker(
        seeded,
        storage,
        clock,
        settings,
        http,
        Fixed(
            vendor_name="@Tarnwell, Freight",
            line_items=[
                {"description": "=1+1", "quantity": "2", "unit_price": "50.00", "amount": "100.00"},
                {
                    "description": 'Note "a"\nb',
                    "quantity": None,
                    "unit_price": None,
                    "amount": "0.00",
                },
            ],
            subtotal="100.00",
        ),
    ).run_once()

    rows = csv_rows(actor[0])

    assert len(rows) == 2
    assert rows[0]["vendor_name"] == "'@Tarnwell, Freight"
    assert rows[0]["line_description"] == "'=1+1"
    assert rows[1]["line_description"] == 'Note "a"\nb'
    assert rows[0]["adjustments_total"] == "-5.00"
    assert rows[0]["total"] == "105.00"
    assert rows[1]["line_quantity"] == ""


def test_an_invoice_without_line_items_still_gets_a_row(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    settings = Settings.model_validate({"database_url": "postgresql://unused"})
    actor = reviewer_for(settings)
    upload(actor)
    worker(seeded, storage, clock, settings, http, Fixed(line_items=[])).run_once()

    rows = csv_rows(actor[0])

    assert len(rows) == 1
    assert rows[0]["total"] == "105.00"
    assert rows[0]["line_position"] == ""


def test_export_leaves_out_documents_that_are_not_approved(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    settings = Settings.model_validate({"database_url": "postgresql://unused"})
    actor = reviewer_for(settings)
    upload(actor)
    worker(seeded, storage, clock, settings, http, Fixed(total="999.00")).run_once()

    assert csv_rows(actor[0]) == []


def test_export_filters_by_approval_date(
    seeded: Engine, storage: Storage, clock: FakeClock, http: httpx2.Client, reviewer_for: Any
) -> None:
    settings = Settings.model_validate({"database_url": "postgresql://unused"})
    actor = reviewer_for(settings)
    upload(actor)
    worker(seeded, storage, clock, settings, http).run_once()
    with Session(seeded) as session, session.begin():
        session.scalars(select(Document)).one().finished_at = datetime(
            2026, 3, 15, 23, 30, tzinfo=UTC
        )

    assert len(csv_rows(actor[0], "?from=2026-03-15&to=2026-03-15")) == 1
    assert csv_rows(actor[0], "?from=2026-03-16") == []
    assert csv_rows(actor[0], "?to=2026-03-14") == []
    assert (
        actor[0].get("/api/exports/invoices.csv?from=2026-03-16&to=2026-03-15").status_code == 422
    )
