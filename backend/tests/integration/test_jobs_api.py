import uuid
from collections.abc import Iterator
from datetime import timedelta
from functools import partial
from pathlib import Path

import pytest
from conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ORIGIN,
    REVIEWER_EMAIL,
    REVIEWER_PASSWORD,
    BuildApp,
    https_client,
    sign_in,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fixtures_files import pdf_bytes
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.db.models import (
    AuditEvent,
    Document,
    DocumentStatus,
    Job,
    JobStatus,
)
from intakefold.documents.storage import Storage
from intakefold.extraction.mock import MockExtractor
from intakefold.extraction.types import (
    DocumentInput,
    ExtractionRejected,
    ExtractionResult,
    Extractor,
)
from intakefold.jobs.queue import enqueue
from intakefold.settings import Settings
from intakefold.worker.handlers import build_handlers, fail_documents_of_dead_jobs
from intakefold.worker.loop import Worker

pytestmark = pytest.mark.integration

JOBS = "/api/jobs"
SETTINGS = Settings.model_validate({"database_url": "postgresql://unused"})


class Rejecting:
    name = "rejecting"

    def extract(self, document: DocumentInput) -> ExtractionResult:
        raise ExtractionRejected("api_400")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "storage")


@pytest.fixture
def app(seeded: Engine, build: BuildApp, clock: FakeClock) -> FastAPI:
    return build(clock)


@pytest.fixture
def reviewer(app: FastAPI) -> Iterator[tuple[TestClient, str]]:
    with https_client(app) as client:
        yield client, sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)


@pytest.fixture
def admin(app: FastAPI) -> Iterator[tuple[TestClient, str]]:
    with https_client(app) as client:
        yield client, sign_in(client, ADMIN_EMAIL, ADMIN_PASSWORD)


def headers(csrf: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf}


def upload(reviewer: tuple[TestClient, str], seed: int = 0) -> uuid.UUID:
    client, csrf = reviewer
    response = client.post(
        "/api/documents",
        files=[("files", ("broken.pdf", pdf_bytes(seed=seed)))],
        headers=headers(csrf),
    )
    return uuid.UUID(response.json()["files"][0]["documentId"])


def run_worker(engine: Engine, storage: Storage, clock: FakeClock, extractor: Extractor) -> None:
    worker = Worker(
        engine,
        build_handlers(engine, storage, clock, extractor, SETTINGS),
        clock=clock,
        on_job_dead=partial(fail_documents_of_dead_jobs, engine, clock),
    )
    worker.run_once()


def document(engine: Engine, document_id: uuid.UUID) -> Document:
    with Session(engine) as session:
        return session.get_one(Document, document_id)


def test_dead_job_is_listed_with_its_document(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = upload(reviewer)
    run_worker(seeded, storage, clock, Rejecting())

    response = reviewer[0].get(JOBS, params={"status": "dead"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["kind"] == "process_document"
    assert item["lastError"] == "api_400"
    assert item["attempts"] == 1
    assert item["documentId"] == str(document_id)
    assert item["filename"] == "broken.pdf"


def test_only_dead_jobs_are_listed(reviewer: tuple[TestClient, str]) -> None:
    upload(reviewer)

    assert reviewer[0].get(JOBS).json() == {"items": [], "nextCursor": None}
    assert reviewer[0].get(JOBS, params={"status": "queued"}).status_code == 422


def test_paging_through_dead_jobs(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    for seed in range(3):
        upload(reviewer, seed)
        clock.advance(timedelta(seconds=1))
        run_worker(seeded, storage, clock, Rejecting())

    first = reviewer[0].get(JOBS, params={"limit": 2}).json()
    second = reviewer[0].get(JOBS, params={"limit": 2, "cursor": first["nextCursor"]}).json()

    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert second["nextCursor"] is None
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(ids)) == 3


def test_bad_cursor_is_refused(reviewer: tuple[TestClient, str]) -> None:
    assert reviewer[0].get(JOBS, params={"cursor": "nonsense!"}).status_code == 400


def test_failing_job_reaches_dead_and_an_admin_brings_it_back(
    reviewer: tuple[TestClient, str],
    admin: tuple[TestClient, str],
    seeded: Engine,
    storage: Storage,
    clock: FakeClock,
) -> None:
    document_id = upload(reviewer)
    run_worker(seeded, storage, clock, Rejecting())
    assert document(seeded, document_id).status is DocumentStatus.FAILED
    job_id = reviewer[0].get(JOBS).json()["items"][0]["id"]

    client, csrf = admin
    response = client.post(f"{JOBS}/{job_id}/retry", headers=headers(csrf))

    assert response.status_code == 202
    row = document(seeded, document_id)
    assert row.status is DocumentStatus.QUEUED
    assert row.status_reasons == []
    assert row.finished_at is None
    assert client.get(JOBS).json()["items"] == []

    run_worker(seeded, storage, clock, MockExtractor(Path("does-not-exist")))

    row = document(seeded, document_id)
    assert row.status is DocumentStatus.NEEDS_REVIEW
    with Session(seeded) as session:
        job = session.scalars(select(Job)).one()
    assert job.status is JobStatus.SUCCEEDED
    assert job.attempts == 1


def test_retry_is_audited_with_the_admin(
    reviewer: tuple[TestClient, str],
    admin: tuple[TestClient, str],
    seeded: Engine,
    storage: Storage,
    clock: FakeClock,
) -> None:
    upload(reviewer)
    run_worker(seeded, storage, clock, Rejecting())
    job_id = reviewer[0].get(JOBS).json()["items"][0]["id"]
    client, csrf = admin
    admin_id = client.get("/api/auth/me").json()["user"]["id"]

    client.post(f"{JOBS}/{job_id}/retry", headers=headers(csrf))

    with Session(seeded) as session:
        event = session.scalars(select(AuditEvent).where(AuditEvent.action == "job_requeued")).one()
    assert str(event.actor_user_id) == admin_id


def test_reviewer_cannot_retry(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = upload(reviewer)
    run_worker(seeded, storage, clock, Rejecting())
    job_id = reviewer[0].get(JOBS).json()["items"][0]["id"]

    client, csrf = reviewer
    response = client.post(f"{JOBS}/{job_id}/retry", headers=headers(csrf))

    assert response.status_code == 403
    assert document(seeded, document_id).status is DocumentStatus.FAILED


def test_retry_of_a_missing_job_is_404(admin: tuple[TestClient, str]) -> None:
    client, csrf = admin

    response = client.post(f"{JOBS}/{uuid.uuid4()}/retry", headers=headers(csrf))

    assert response.status_code == 404


def test_retry_of_a_job_that_is_not_dead_is_409(
    reviewer: tuple[TestClient, str], admin: tuple[TestClient, str], seeded: Engine
) -> None:
    document_id = upload(reviewer)
    with Session(seeded) as session:
        job_id = session.scalars(select(Job.id)).one()
    client, csrf = admin

    response = client.post(f"{JOBS}/{job_id}/retry", headers=headers(csrf))

    assert response.status_code == 409
    assert document(seeded, document_id).status is DocumentStatus.QUEUED


def test_job_with_no_document_can_be_retried(
    admin: tuple[TestClient, str], seeded: Engine, clock: FakeClock
) -> None:
    with Session(seeded) as session, session.begin():
        job_id = enqueue(
            session, kind="deliver_webhook", idempotency_key="k", payload={}, clock=clock
        ).job_id
        session.get_one(Job, job_id).status = JobStatus.DEAD
    client, csrf = admin

    assert client.post(f"{JOBS}/{job_id}/retry", headers=headers(csrf)).status_code == 202
    with Session(seeded) as session:
        assert session.get_one(Job, job_id).status is JobStatus.QUEUED


def test_session_reports_the_extractor(reviewer: tuple[TestClient, str]) -> None:
    assert reviewer[0].get("/api/auth/me").json()["extractor"] == "mock"
