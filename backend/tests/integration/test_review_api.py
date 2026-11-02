import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

import httpx2
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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.db.models import (
    AuditEvent,
    Document,
    DocumentStatus,
    ExtractionOutcome,
    Invoice,
    LineItem,
    User,
)
from intakefold.documents.storage import Storage
from intakefold.extraction.schema import ExtractedDocument
from intakefold.extraction.types import DocumentInput, ExtractionResult, Extractor
from intakefold.settings import Settings
from intakefold.worker.handlers import build_handlers, fail_documents_of_dead_jobs
from intakefold.worker.loop import Worker

pytestmark = pytest.mark.integration

SETTINGS = Settings.model_validate({"database_url": "postgresql://unused"})
EXTRACTED: dict[str, Any] = {
    "document_type": "invoice",
    "vendor_name": "Tarnwell Freight",
    "invoice_number": "INV-1",
    "issue_date": date(2026, 9, 1),
    "due_date": None,
    "currency": "USD",
    "subtotal": "100.00",
    "tax_total": "10.00",
    "adjustments_total": "0.00",
    "total": "999.00",
    "line_items": [
        {"description": "Item", "quantity": "2", "unit_price": "50.00", "amount": "100.00"}
    ],
    "overall_confidence": "high",
    "uncertain_fields": [],
    "contains_embedded_instructions": False,
}


class Fixed:
    name = "fixed"

    def __init__(self, **changes: object) -> None:
        self.data = ExtractedDocument.model_validate(EXTRACTED | changes)

    def extract(self, document: DocumentInput) -> ExtractionResult:
        return ExtractionResult(ExtractionOutcome.SUCCEEDED, self.name, data=self.data)


class Failing:
    name = "failing"

    def extract(self, document: DocumentInput) -> ExtractionResult:
        return ExtractionResult(ExtractionOutcome.INVALID, self.name)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 1, 9, 0, tzinfo=UTC))


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "storage")


@pytest.fixture
def app(seeded: Engine, build: BuildApp, clock: FakeClock) -> FastAPI:
    return build(clock, upload_rate_limit="1000/minute")


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


def in_review(
    actor: tuple[TestClient, str],
    engine: Engine,
    storage: Storage,
    clock: FakeClock,
    extractor: Extractor | None = None,
) -> uuid.UUID:
    client, csrf = actor
    response = client.post(
        "/api/documents",
        files=[("files", ("invoice.pdf", pdf_bytes(seed=uuid.uuid4().int % 1000)))],
        headers=headers(csrf),
    )
    document_id = uuid.UUID(response.json()["files"][0]["documentId"])
    Worker(
        engine,
        build_handlers(engine, storage, clock, extractor or Fixed(), SETTINGS),
        clock=clock,
        on_job_dead=partial(fail_documents_of_dead_jobs, engine, clock),
    ).run_once()
    return document_id


def detail(actor: tuple[TestClient, str], document_id: uuid.UUID) -> dict[str, Any]:
    return actor[0].get(f"/api/documents/{document_id}").json()


def patch(
    actor: tuple[TestClient, str],
    document_id: uuid.UUID,
    version: int,
    fields: dict[str, Any],
) -> httpx2.Response:
    client, csrf = actor
    return client.patch(
        f"/api/documents/{document_id}/fields",
        json={"version": version, "fields": fields},
        headers=headers(csrf),
    )


def post(
    actor: tuple[TestClient, str], document_id: uuid.UUID, action: str, body: dict[str, Any]
) -> httpx2.Response:
    client, csrf = actor
    return client.post(f"/api/documents/{document_id}/{action}", json=body, headers=headers(csrf))


def events(engine: Engine, document_id: uuid.UUID, action: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.document_id == document_id, AuditEvent.action == action)
                .order_by(AuditEvent.id)
            )
        )


def status_of(engine: Engine, document_id: uuid.UUID) -> DocumentStatus:
    with Session(engine) as session:
        return session.get_one(Document, document_id).status


@pytest.fixture
def document_id(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> uuid.UUID:
    return in_review(reviewer, seeded, storage, clock)


def test_detail_shows_fields_money_as_strings_and_why_it_is_here(
    reviewer: tuple[TestClient, str], document_id: uuid.UUID
) -> None:
    body = detail(reviewer, document_id)

    assert body["status"] == "needs_review"
    assert body["version"] == 1
    assert body["statusReasons"] == ["total_reconciles"]
    assert body["fields"]["total"] == "999.00"
    assert body["fields"]["lineItems"][0]["quantity"] == "2.00"
    assert body["fields"]["issueDate"] == "2026-09-01"
    assert body["overallConfidence"] == "high"
    failed = [rule for rule in body["ruleResults"] if rule["outcome"] == "fail"]
    assert len(failed) == 1
    assert failed[0]["rule"] == "total_reconciles"
    assert failed[0]["fields"] == ["subtotal", "taxTotal", "adjustmentsTotal", "total"]
    assert "999.00" in failed[0]["detail"]


def test_required_field_failure_points_at_what_is_missing(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = in_review(reviewer, seeded, storage, clock, Fixed(currency=None))

    failed = [r for r in detail(reviewer, document_id)["ruleResults"] if r["outcome"] == "fail"]

    assert failed[0]["fields"] == ["currency"]


def test_precise_amounts_keep_their_digits(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = in_review(reviewer, seeded, storage, clock, Fixed(total="1234.5678"))

    assert detail(reviewer, document_id)["fields"]["total"] == "1234.5678"


def test_correction_re_runs_the_rules_but_leaves_approval_to_a_person(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    fields = detail(reviewer, document_id)["fields"] | {"total": "110.00"}

    response = patch(reviewer, document_id, 1, fields)

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["status"] == "needs_review"
    assert body["statusReasons"] == []
    assert all(rule["outcome"] != "fail" for rule in body["ruleResults"])
    with Session(seeded) as session:
        assert session.scalars(select(Invoice)).one().total == Decimal("110.00")


def test_every_correction_records_who_changed_what(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    fields = detail(reviewer, document_id)["fields"] | {"total": "110.00", "currency": "EUR"}

    patch(reviewer, document_id, 1, fields)

    with Session(seeded) as session:
        user = session.scalars(select(User).where(User.email == REVIEWER_EMAIL)).one()
    found = {
        event.field: (event.old_value, event.new_value, event.actor_user_id)
        for event in events(seeded, document_id, "field_corrected")
    }
    assert found == {
        "total": ("999.0000", "110.00", user.id),
        "currency": ("USD", "EUR", user.id),
    }


def test_audit_rows_of_a_correction_cannot_be_rewritten(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    fields = detail(reviewer, document_id)["fields"] | {"total": "110.00"}
    patch(reviewer, document_id, 1, fields)

    with pytest.raises(DBAPIError), Session(seeded) as session, session.begin():
        session.scalars(select(AuditEvent).where(AuditEvent.field == "total")).one().new_value = "1"


def test_line_item_changes_are_audited_by_position(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    fields = detail(reviewer, document_id)["fields"]
    fields["lineItems"][0]["amount"] = "90.00"
    fields["lineItems"].append(
        {"description": "Added", "quantity": None, "unitPrice": None, "amount": "10.00"}
    )

    response = patch(reviewer, document_id, 1, fields)

    assert [line["amount"] for line in response.json()["fields"]["lineItems"]] == ["90.00", "10.00"]
    changed = {event.field for event in events(seeded, document_id, "field_corrected")}
    assert changed == {
        "line_items[1].amount",
        "line_items[2].description",
        "line_items[2].amount",
    }
    with Session(seeded) as session:
        assert [row.position for row in session.scalars(select(LineItem))] == [1, 2]


def test_removing_a_line_is_audited(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    fields = detail(reviewer, document_id)["fields"] | {"lineItems": []}

    patch(reviewer, document_id, 1, fields)

    removed = events(seeded, document_id, "field_corrected")
    assert {e.field for e in removed} == {
        "line_items[1].description",
        "line_items[1].quantity",
        "line_items[1].unit_price",
        "line_items[1].amount",
    }
    assert all(e.new_value is None for e in removed)


def test_saving_nothing_changes_nothing(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    response = patch(reviewer, document_id, 1, detail(reviewer, document_id)["fields"])

    assert response.json()["version"] == 1
    assert events(seeded, document_id, "field_corrected") == []


def test_correcting_the_vendor_updates_the_keys_and_the_rule(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = in_review(
        reviewer, seeded, storage, clock, Fixed(vendor_name="Unknown Co", total="110.00")
    )
    assert detail(reviewer, document_id)["statusReasons"] == ["known_vendor"]
    fields = detail(reviewer, document_id)["fields"] | {"vendorName": "Tarnwell Freight"}

    body = patch(reviewer, document_id, 1, fields).json()

    assert body["statusReasons"] == []
    with Session(seeded) as session:
        invoice = session.scalars(select(Invoice)).one()
    assert invoice.normalized_vendor == "tarnwell freight"
    assert invoice.vendor_id is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [("total", "1,100.00"), ("total", "abc"), ("currency", "usd"), ("issueDate", "tomorrow")],
)
def test_bad_values_are_refused_with_the_field_named(
    reviewer: tuple[TestClient, str], document_id: uuid.UUID, field: str, value: str
) -> None:
    fields = detail(reviewer, document_id)["fields"] | {field: value}

    response = patch(reviewer, document_id, 1, fields)

    assert response.status_code == 422
    assert f"body.fields.{field}" in {error["field"] for error in response.json()["errors"]}
    assert detail(reviewer, document_id)["version"] == 1


def test_stale_version_is_refused(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    fields = detail(reviewer, document_id)["fields"] | {"total": "110.00"}
    patch(reviewer, document_id, 1, fields)

    response = patch(reviewer, document_id, 1, fields | {"total": "5.00"})

    assert response.status_code == 409
    assert "Reload" in response.json()["detail"]
    with Session(seeded) as session:
        assert session.scalars(select(Invoice)).one().total == Decimal("110.00")


def test_two_reviewers_saving_at_once_cannot_both_win(
    reviewer: tuple[TestClient, str],
    admin: tuple[TestClient, str],
    seeded: Engine,
    document_id: uuid.UUID,
) -> None:
    fields = detail(reviewer, document_id)["fields"]
    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def save(actor: tuple[TestClient, str], total: str) -> None:
        barrier.wait()
        statuses.append(patch(actor, document_id, 1, fields | {"total": total}).status_code)

    threads = [
        threading.Thread(target=save, args=(reviewer, "110.00")),
        threading.Thread(target=save, args=(admin, "111.00")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [200, 409]
    assert len(events(seeded, document_id, "field_corrected")) == 1


def test_approval_is_blocked_by_a_failed_rule_without_a_reason(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    for reason in (None, "", "   "):
        response = post(reviewer, document_id, "approve", {"version": 1, "overrideReason": reason})
        assert response.status_code == 422

    assert status_of(seeded, document_id) is DocumentStatus.NEEDS_REVIEW


def test_override_reason_approves_and_is_audited(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    response = post(
        reviewer, document_id, "approve", {"version": 1, "overrideReason": "Vendor confirmed."}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["version"] == 2
    event = events(seeded, document_id, "document_approved")[0]
    assert event.field == "override_reason"
    assert event.new_value == "Vendor confirmed."
    assert event.actor_user_id is not None


def test_clean_document_is_approved_without_a_reason(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    fields = detail(reviewer, document_id)["fields"] | {"total": "110.00"}
    patch(reviewer, document_id, 1, fields)

    response = post(reviewer, document_id, "approve", {"version": 2})

    assert response.status_code == 200
    event = events(seeded, document_id, "document_approved")[0]
    assert event.field is None
    assert event.new_value is None


def test_model_signals_alone_do_not_block_a_person(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = in_review(
        reviewer,
        seeded,
        storage,
        clock,
        Fixed(total="110.00", overall_confidence="low", contains_embedded_instructions=True),
    )

    response = post(reviewer, document_id, "approve", {"version": 1})

    assert response.status_code == 200


def test_rejection_needs_a_reason_and_is_audited(
    reviewer: tuple[TestClient, str], seeded: Engine, document_id: uuid.UUID
) -> None:
    assert post(reviewer, document_id, "reject", {"version": 1, "reason": ""}).status_code == 422
    assert post(reviewer, document_id, "reject", {"version": 1, "reason": "  "}).status_code == 422

    response = post(reviewer, document_id, "reject", {"version": 1, "reason": "Not ours."})

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert events(seeded, document_id, "document_rejected")[0].new_value == "Not ours."


@pytest.mark.parametrize(
    ("action", "body"),
    [("approve", {"overrideReason": "ok"}), ("reject", {"reason": "no"})],
)
def test_finished_documents_cannot_be_acted_on_again(
    reviewer: tuple[TestClient, str],
    document_id: uuid.UUID,
    action: str,
    body: dict[str, Any],
) -> None:
    assert post(reviewer, document_id, action, {"version": 1} | body).status_code == 200

    again = post(reviewer, document_id, action, {"version": 2} | body)
    fields = detail(reviewer, document_id)["fields"]

    assert again.status_code == 409
    assert "no longer in review" in again.json()["detail"]
    assert patch(reviewer, document_id, 2, fields).status_code == 409


def test_auto_approved_document_cannot_be_edited(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = in_review(reviewer, seeded, storage, clock, Fixed(total="110.00"))

    response = patch(reviewer, document_id, 1, detail(reviewer, document_id)["fields"])

    assert status_of(seeded, document_id) is DocumentStatus.AUTO_APPROVED
    assert response.status_code == 409


def test_approve_and_reject_use_the_version_too(
    reviewer: tuple[TestClient, str], document_id: uuid.UUID
) -> None:
    assert post(reviewer, document_id, "approve", {"version": 9}).status_code == 409
    assert post(reviewer, document_id, "reject", {"version": 9, "reason": "x"}).status_code == 409


def test_failed_extraction_can_be_keyed_in_by_hand(
    reviewer: tuple[TestClient, str], seeded: Engine, storage: Storage, clock: FakeClock
) -> None:
    document_id = in_review(reviewer, seeded, storage, clock, Failing())
    body = detail(reviewer, document_id)
    assert body["fields"] is None
    assert post(reviewer, document_id, "approve", {"version": 1}).status_code == 422

    fields: dict[str, Any] = {
        "documentType": "invoice",
        "vendorName": "Tarnwell Freight",
        "invoiceNumber": "INV-9",
        "issueDate": "2026-09-01",
        "dueDate": None,
        "currency": "USD",
        "subtotal": "100.00",
        "taxTotal": "0.00",
        "adjustmentsTotal": "0.00",
        "total": "100.00",
        "lineItems": [],
    }
    saved = patch(reviewer, document_id, 1, fields)

    assert saved.status_code == 200
    assert saved.json()["fields"]["vendorName"] == "Tarnwell Freight"
    assert post(reviewer, document_id, "approve", {"version": 2}).status_code == 200


def test_missing_document_is_404_everywhere(reviewer: tuple[TestClient, str]) -> None:
    missing = uuid.uuid4()
    fields: dict[str, Any] = {
        "documentType": "invoice",
        "vendorName": None,
        "invoiceNumber": None,
        "issueDate": None,
        "dueDate": None,
        "currency": None,
        "subtotal": None,
        "taxTotal": None,
        "adjustmentsTotal": None,
        "total": None,
        "lineItems": [],
    }

    assert reviewer[0].get(f"/api/documents/{missing}").status_code == 404
    assert patch(reviewer, missing, 1, fields).status_code == 404
    assert post(reviewer, missing, "approve", {"version": 1}).status_code == 404
    assert post(reviewer, missing, "reject", {"version": 1, "reason": "x"}).status_code == 404


def test_reasons_never_reach_the_logs(
    reviewer: tuple[TestClient, str],
    document_id: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    post(reviewer, document_id, "reject", {"version": 1, "reason": "private-reason-text"})

    assert "private-reason-text" not in capsys.readouterr().out
