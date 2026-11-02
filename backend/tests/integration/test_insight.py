import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from conftest import ORIGIN, REVIEWER_EMAIL, REVIEWER_PASSWORD, BuildApp, https_client, sign_in
from fastapi.testclient import TestClient
from fixtures_files import pdf_bytes
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.db.models import (
    Batch,
    BatchSource,
    Document,
    DocumentStatus,
    Extraction,
    ExtractionOutcome,
    RunStep,
    StepStatus,
    new_id,
)
from intakefold.documents.storage import Storage
from intakefold.extraction.mock import MockExtractor
from intakefold.extraction.schema import ExtractedDocument
from intakefold.extraction.types import DocumentInput, ExtractionResult, Usage
from intakefold.settings import Settings
from intakefold.worker.handlers import build_handlers, on_job_dead
from intakefold.worker.loop import Worker

pytestmark = pytest.mark.integration

SETTINGS = Settings.model_validate({"database_url": "postgresql://unused"})
LABELED_SET = Path(__file__).parents[3] / "data" / "labeled"
START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def client(seeded: Engine, build: BuildApp) -> Iterator[TestClient]:
    with https_client(build(FakeClock(START), upload_rate_limit="1000/minute")) as client:
        sign_in(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)
        yield client


def add_document(
    session: Session,
    batch_id: uuid.UUID,
    status: DocumentStatus,
    extractor: str | None,
    seconds: int | None,
) -> None:
    document_id = new_id()
    session.add(
        Document(
            id=document_id,
            batch_id=batch_id,
            sha256=uuid.uuid4().hex * 2,
            original_filename="f.pdf",
            media_type="application/pdf",
            size_bytes=1,
            page_count=1,
            storage_key=f"originals/{uuid.uuid4()}",
            status=status,
            received_at=START,
        )
    )
    session.flush()
    if extractor is not None:
        session.add(
            Extraction(
                document_id=document_id,
                attempt=1,
                extractor=extractor,
                prompt_version="p",
                schema_version="s",
                outcome=ExtractionOutcome.SUCCEEDED,
            )
        )
    if seconds is not None:
        # Two steps, so the time must come from the last one to finish, not the first.
        for step, ends in (("render", seconds / 2), ("validate", seconds)):
            session.add(
                RunStep(
                    document_id=document_id,
                    attempt=1,
                    step=step,
                    status=StepStatus.SUCCEEDED,
                    started_at=START,
                    finished_at=START + timedelta(seconds=ends),
                )
            )


def batch(session: Session, source: BatchSource) -> uuid.UUID:
    batch_id = new_id()
    session.add(Batch(id=batch_id, source=source, doc_cap=25, token_cap=1000))
    session.flush()
    return batch_id


def test_metrics_match_a_hand_computed_fixture(client: TestClient, seeded: Engine) -> None:
    with Session(seeded) as session, session.begin():
        upload = batch(session, BatchSource.UPLOAD)
        evaluation = batch(session, BatchSource.EVAL)
        # mock: 2 auto, 1 review, 1 approved after review, 1 failed -> 5 processed.
        add_document(session, upload, DocumentStatus.AUTO_APPROVED, "mock", 10)
        add_document(session, upload, DocumentStatus.AUTO_APPROVED, "mock", 20)
        add_document(session, upload, DocumentStatus.NEEDS_REVIEW, "mock", 30)
        add_document(session, upload, DocumentStatus.APPROVED, "mock", 40)
        add_document(session, upload, DocumentStatus.FAILED, "mock", None)
        # claude: 1 rejected after review.
        add_document(session, upload, DocumentStatus.REJECTED, "claude", 7)
        # Never extracted: the render failed.
        add_document(session, upload, DocumentStatus.FAILED, None, 3)
        # Not counted: still running, or part of an evaluation.
        add_document(session, upload, DocumentStatus.PROCESSING, "mock", 5)
        add_document(session, upload, DocumentStatus.QUEUED, None, None)
        add_document(session, evaluation, DocumentStatus.AUTO_APPROVED, "mock", 99)

    rows = client.get("/api/metrics").json()["rows"]

    assert rows == [
        {
            "extractor": "claude",
            "processed": 1,
            "autoApproved": 0,
            "wentToReview": 1,
            "failed": 0,
            "autoApprovedShare": "0.0000",
            "reviewShare": "1.0000",
            "failureShare": "0.0000",
            "averageSeconds": "7.0",
        },
        {
            "extractor": "mock",
            "processed": 5,
            "autoApproved": 2,
            "wentToReview": 2,
            "failed": 1,
            "autoApprovedShare": "0.4000",
            "reviewShare": "0.4000",
            "failureShare": "0.2000",
            # (10 + 20 + 30 + 40) / 4: the failed one has no finished step, so it has no time.
            "averageSeconds": "25.0",
        },
        {
            "extractor": "none",
            "processed": 1,
            "autoApproved": 0,
            "wentToReview": 0,
            "failed": 1,
            "autoApprovedShare": "0.0000",
            "reviewShare": "0.0000",
            "failureShare": "1.0000",
            "averageSeconds": "3.0",
        },
    ]


def test_metrics_with_no_documents_are_empty_not_an_error(client: TestClient) -> None:
    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert response.json() == {"rows": []}


def test_metrics_use_the_latest_extraction(client: TestClient, seeded: Engine) -> None:
    with Session(seeded) as session, session.begin():
        upload = batch(session, BatchSource.UPLOAD)
        add_document(session, upload, DocumentStatus.NEEDS_REVIEW, "mock", 1)
        document_id = session.query(Document.id).one()[0]
        session.add(
            Extraction(
                document_id=document_id,
                attempt=2,
                extractor="claude",
                prompt_version="p",
                schema_version="s",
                outcome=ExtractionOutcome.SUCCEEDED,
            )
        )

    assert [row["extractor"] for row in client.get("/api/metrics").json()["rows"]] == ["claude"]


def test_metrics_agree_with_a_direct_query(client: TestClient, seeded: Engine) -> None:
    with Session(seeded) as session, session.begin():
        upload = batch(session, BatchSource.UPLOAD)
        for index, status in enumerate(
            [DocumentStatus.AUTO_APPROVED] * 3 + [DocumentStatus.NEEDS_REVIEW] * 4
        ):
            add_document(session, upload, status, "mock", index + 1)

    row = client.get("/api/metrics").json()["rows"][0]
    with seeded.connect() as connection:
        direct = connection.execute(
            text(
                "SELECT count(*) FILTER (WHERE status = 'auto_approved')::numeric / count(*) "
                "FROM documents WHERE status NOT IN ('queued', 'processing')"
            )
        ).scalar_one()

    assert Decimal(row["autoApprovedShare"]) == round(direct, 4)


CLAUDE_RESULT: dict[str, Any] = {
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


class PretendClaude:
    """Stands in for a real model call, with the usage a real one reports."""

    name = "claude"

    def extract(self, document: DocumentInput) -> ExtractionResult:
        return ExtractionResult(
            ExtractionOutcome.SUCCEEDED,
            self.name,
            data=ExtractedDocument.model_validate(CLAUDE_RESULT),
            model="claude-opus-5-5",
            usage=Usage(1200, 300),
            estimated_cost_usd=Decimal("0.010800"),
        )


def process(client: TestClient, engine: Engine, tmp_path: Path, extractor: object) -> str:
    csrf = client.get("/api/auth/me").json()["csrfToken"]
    response = client.post(
        "/api/documents",
        files=[("files", ("a.pdf", pdf_bytes(seed=uuid.uuid4().int % 1000)))],
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    document_id = response.json()["files"][0]["documentId"]
    clock = FakeClock(START)
    Worker(
        engine,
        build_handlers(engine, Storage(tmp_path / "storage"), clock, extractor, SETTINGS),  # pyright: ignore[reportArgumentType]
        clock=clock,
        on_job_dead=partial(on_job_dead, engine, clock),
    ).run_once()
    return document_id


def test_run_log_of_a_real_worker_pass(client: TestClient, seeded: Engine, tmp_path: Path) -> None:
    document_id = process(client, seeded, tmp_path, MockExtractor(LABELED_SET))

    body = client.get(f"/api/documents/{document_id}/run-log").json()

    assert [step["step"] for step in body["steps"]] == ["render", "extract", "validate"]
    assert all(step["status"] == "succeeded" for step in body["steps"])
    assert all(step["durationMs"] is not None for step in body["steps"])
    assert all(step["finishedAt"] is not None for step in body["steps"])
    actions = [event["action"] for event in body["events"]]
    assert actions == ["document_uploaded", "document_routed"]
    assert body["events"][0]["actorName"] == "Riley Reviewer"
    assert body["events"][1]["actorName"] is None


def test_mock_runs_show_no_token_counts_or_cost(
    client: TestClient, seeded: Engine, tmp_path: Path
) -> None:
    document_id = process(client, seeded, tmp_path, MockExtractor(LABELED_SET))

    extract = client.get(f"/api/documents/{document_id}/run-log").json()["steps"][1]

    assert extract["extractor"] == "mock"
    assert extract["model"] is None
    for field in ("inputTokens", "outputTokens", "cacheReadTokens", "estimatedCostUsd"):
        assert extract[field] is None


def test_model_steps_carry_tokens_and_cost_as_text(
    client: TestClient, seeded: Engine, tmp_path: Path
) -> None:
    document_id = process(client, seeded, tmp_path, PretendClaude())

    extract = client.get(f"/api/documents/{document_id}/run-log").json()["steps"][1]

    assert extract["model"] == "claude-opus-5-5"
    assert (extract["inputTokens"], extract["outputTokens"]) == (1200, 300)
    assert extract["estimatedCostUsd"] == "0.010800"


def test_corrections_appear_in_the_trail_with_who_and_what(
    client: TestClient, seeded: Engine, tmp_path: Path
) -> None:
    document_id = process(client, seeded, tmp_path, MockExtractor(Path("no-labels")))
    fields = client.get(f"/api/documents/{document_id}").json()["fields"] | {"total": "5.00"}
    csrf = client.get("/api/auth/me").json()["csrfToken"]
    client.patch(
        f"/api/documents/{document_id}/fields",
        json={"version": 1, "fields": fields},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )

    events = client.get(f"/api/documents/{document_id}/run-log").json()["events"]

    correction = next(event for event in events if event["action"] == "field_corrected")
    assert correction == correction | {
        "field": "total",
        "oldValue": None,
        "newValue": "5.00",
        "actorName": "Riley Reviewer",
    }


def test_run_log_of_a_missing_document_is_404(client: TestClient) -> None:
    assert client.get(f"/api/documents/{uuid.uuid4()}/run-log").status_code == 404
