import uuid
from collections.abc import Iterator
from datetime import timedelta
from functools import partial
from io import BytesIO
from pathlib import Path

import pytest
from conftest import ORIGIN, REVIEWER_EMAIL, REVIEWER_PASSWORD, BuildApp, https_client, sign_in
from fastapi.testclient import TestClient
from fixtures_files import jpeg_bytes, pdf_bytes
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.db.models import Document, DocumentStatus, Job, JobStatus, RunStep, StepStatus
from intakefold.documents.intake import PROCESS_DOCUMENT
from intakefold.documents.rendering import MAX_RENDER_SIDE
from intakefold.documents.storage import Storage
from intakefold.extraction.mock import MockExtractor
from intakefold.jobs import queue
from intakefold.settings import Settings
from intakefold.worker.handlers import build_handlers, fail_documents_of_dead_jobs
from intakefold.worker.loop import Worker

pytestmark = pytest.mark.integration

LEASE = timedelta(minutes=5)
EMPTY_MOCK = MockExtractor(Path("does-not-exist"))
RULE_SETTINGS = Settings.model_validate({"database_url": "postgresql://unused"})


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "storage")


@pytest.fixture
def worker(seeded: Engine, storage: Storage, clock: FakeClock) -> Worker:
    return Worker(
        seeded,
        build_handlers(seeded, storage, clock, EMPTY_MOCK, RULE_SETTINGS),
        clock=clock,
        lease=LEASE,
        on_job_dead=partial(fail_documents_of_dead_jobs, seeded, clock),
    )


@pytest.fixture
def client(seeded: Engine, build: BuildApp, clock: FakeClock) -> Iterator[TestClient]:
    with https_client(build(clock)) as client:
        sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
        yield client


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


def only_job(engine: Engine) -> Job:
    with Session(engine) as session:
        return session.scalars(select(Job)).one()


def steps(engine: Engine, document_id: uuid.UUID) -> list[tuple[str, StepStatus, int]]:
    with Session(engine) as session:
        rows = session.scalars(
            select(RunStep)
            .where(RunStep.document_id == document_id)
            .order_by(RunStep.started_at, RunStep.id)
        )
        return [(row.step, row.status, row.attempt) for row in rows]


def test_pdf_pages_are_rendered_and_served(
    client: TestClient, worker: Worker, seeded: Engine
) -> None:
    document_id = upload(client, pdf_bytes(pages=2))

    assert worker.run_once() is True

    assert only_job(seeded).status is JobStatus.SUCCEEDED
    assert document(seeded, document_id).status is DocumentStatus.NEEDS_REVIEW
    assert steps(seeded, document_id) == [
        ("render", StepStatus.SUCCEEDED, 1),
        ("extract", StepStatus.SUCCEEDED, 1),
        ("validate", StepStatus.SUCCEEDED, 1),
    ]
    for page in (1, 2):
        response = client.get(f"/api/documents/{document_id}/pages/{page}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        with Image.open(BytesIO(response.content)) as image:
            assert image.format == "PNG"
            assert image.width > 300  # Rendered at 150 DPI, not at PDF points.
    assert client.get(f"/api/documents/{document_id}/pages/3").status_code == 404


def test_image_is_rendered_as_one_png_page(
    client: TestClient, worker: Worker, seeded: Engine
) -> None:
    document_id = upload(client, jpeg_bytes(size=(60, 40)))

    worker.run_once()

    response = client.get(f"/api/documents/{document_id}/pages/1")
    assert response.status_code == 200
    with Image.open(BytesIO(response.content)) as image:
        assert image.format == "PNG"
        assert image.size == (60, 40)


def test_huge_stated_page_size_renders_within_bounds(
    client: TestClient, worker: Worker, storage: Storage
) -> None:
    writer = PdfWriter()
    writer.add_blank_page(14400, 14400)
    output = BytesIO()
    writer.write(output)
    document_id = upload(client, output.getvalue())

    worker.run_once()

    with Image.open(BytesIO(storage.read(storage.page_key(document_id, 1)))) as image:
        assert max(image.size) <= MAX_RENDER_SIDE


def test_running_the_job_again_is_harmless(
    client: TestClient, seeded: Engine, storage: Storage, clock: FakeClock, worker: Worker
) -> None:
    document_id = upload(client, pdf_bytes())
    worker.run_once()
    job = queue.claim(seeded, "other", LEASE, clock)
    assert job is None

    handler = build_handlers(seeded, storage, clock, EMPTY_MOCK, RULE_SETTINGS)[PROCESS_DOCUMENT]
    finished = only_job(seeded)
    handler(
        queue.ClaimedJob(finished.id, finished.kind, finished.payload, 2, 5, "redelivered"),
    )

    assert document(seeded, document_id).status is DocumentStatus.NEEDS_REVIEW
    assert storage.exists(storage.page_key(document_id, 1))


def test_finished_document_is_left_alone(
    client: TestClient, seeded: Engine, storage: Storage, worker: Worker
) -> None:
    document_id = upload(client, pdf_bytes())
    with Session(seeded) as session, session.begin():
        session.get_one(Document, document_id).status = DocumentStatus.APPROVED

    worker.run_once()

    assert document(seeded, document_id).status is DocumentStatus.APPROVED
    assert steps(seeded, document_id) == []
    assert only_job(seeded).status is JobStatus.SUCCEEDED


def test_file_the_renderer_cannot_read_fails_at_once(
    client: TestClient, seeded: Engine, storage: Storage, worker: Worker
) -> None:
    document_id = upload(client, pdf_bytes())
    storage.write(document(seeded, document_id).storage_key, b"damaged after upload")

    worker.run_once()

    job = only_job(seeded)
    row = document(seeded, document_id)
    assert job.status is JobStatus.DEAD
    assert job.attempts == 1
    assert job.last_error == "render_failed"
    assert row.status is DocumentStatus.FAILED
    assert row.status_reasons == ["render_failed"]
    assert row.finished_at is not None
    assert steps(seeded, document_id) == [("render", StepStatus.FAILED, 1)]


def test_parsers_disagreeing_on_the_page_count_fails_the_document(
    client: TestClient, seeded: Engine, worker: Worker
) -> None:
    document_id = upload(client, pdf_bytes(pages=2))
    with Session(seeded) as session, session.begin():
        session.get_one(Document, document_id).page_count = 3

    worker.run_once()

    assert document(seeded, document_id).status is DocumentStatus.FAILED


def test_passing_error_retries_then_the_document_fails(
    client: TestClient,
    seeded: Engine,
    storage: Storage,
    clock: FakeClock,
    worker: Worker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = upload(client, pdf_bytes())

    def disk_trouble(_: str) -> bytes:
        raise OSError("private path detail")

    monkeypatch.setattr(storage, "read", disk_trouble)

    for attempt in range(1, 6):
        assert worker.run_once() is True
        expected = DocumentStatus.FAILED if attempt == 5 else DocumentStatus.PROCESSING
        assert document(seeded, document_id).status is expected
        clock.advance(timedelta(minutes=10))

    assert only_job(seeded).status is JobStatus.DEAD
    assert document(seeded, document_id).status_reasons == ["OSError"]
    assert steps(seeded, document_id)[-1] == ("render", StepStatus.FAILED, 5)


def test_worker_killed_on_the_last_attempt_still_fails_the_document(
    client: TestClient, seeded: Engine, clock: FakeClock, worker: Worker
) -> None:
    document_id = upload(client, pdf_bytes())
    with Session(seeded) as session, session.begin():
        session.scalars(select(Job)).one().max_attempts = 1
        session.get_one(Document, document_id).status = DocumentStatus.PROCESSING
    # Claimed by a worker that then disappears, as a PDFium crash would cause.
    assert queue.claim(seeded, "crashed", LEASE, clock) is not None
    clock.advance(LEASE + timedelta(minutes=1))

    worker.run_once()

    assert only_job(seeded).status is JobStatus.DEAD
    row = document(seeded, document_id)
    assert row.status is DocumentStatus.FAILED
    assert row.status_reasons == ["lease_expired"]


def test_dead_job_of_another_document_changes_nothing(
    client: TestClient, seeded: Engine, clock: FakeClock
) -> None:
    alive = upload(client, pdf_bytes(seed=1))
    dead = upload(client, pdf_bytes(seed=2))
    with Session(seeded) as session, session.begin():
        for job in session.scalars(select(Job)):
            if job.payload["document_id"] == str(dead):
                job.status = JobStatus.DEAD
                job.last_error = "boom"

    fail_documents_of_dead_jobs(seeded, clock)

    assert document(seeded, alive).status is DocumentStatus.QUEUED
    assert document(seeded, dead).status is DocumentStatus.FAILED
