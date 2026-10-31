import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.audit.records import record_audit_event, run_step
from intakefold.db.models import (
    AuditEvent,
    Batch,
    BatchSource,
    Document,
    DocumentStatus,
    Role,
    RunStep,
    StepStatus,
    User,
    Vendor,
)
from intakefold.db.seed import UNUSABLE_PASSWORD, seed

pytestmark = pytest.mark.integration


@pytest.fixture
def document_id(engine: Engine) -> uuid.UUID:
    with Session(engine) as session, session.begin():
        batch = Batch(source=BatchSource.UPLOAD, doc_cap=25, token_cap=1000)
        session.add(batch)
        session.flush()
        document = Document(
            batch_id=batch.id,
            sha256="a" * 64,
            original_filename="invoice.pdf",
            media_type="application/pdf",
            size_bytes=1,
            storage_key="key",
            status=DocumentStatus.QUEUED,
        )
        session.add(document)
        session.flush()
        return document.id


def only_step(engine: Engine) -> RunStep:
    with Session(engine) as session:
        return session.scalars(select(RunStep)).one()


def test_successful_step_records_timing_and_usage(engine: Engine, document_id: uuid.UUID) -> None:
    clock = FakeClock()

    with run_step(
        engine, clock, document_id=document_id, job_id=None, attempt=1, step="extract"
    ) as step:
        clock.advance(timedelta(milliseconds=1500))
        step.extractor = "claude"
        step.model = "a-model"
        step.input_tokens = 100
        step.output_tokens = 20
        step.estimated_cost_usd = Decimal("0.000800")

    row = only_step(engine)
    assert row.status is StepStatus.SUCCEEDED
    assert row.duration_ms == 1500
    assert row.model == "a-model"
    assert row.input_tokens == 100
    assert row.output_tokens == 20
    assert row.estimated_cost_usd == Decimal("0.000800")


def test_step_is_visible_while_it_runs(engine: Engine, document_id: uuid.UUID) -> None:
    with run_step(
        engine, FakeClock(), document_id=document_id, job_id=None, attempt=1, step="render"
    ):
        row = only_step(engine)

        assert row.status is StepStatus.RUNNING
        assert row.finished_at is None


def test_failed_step_records_the_error_type_and_reraises(
    engine: Engine, document_id: uuid.UUID
) -> None:
    with (
        pytest.raises(ValueError, match="document text"),
        run_step(
            engine, FakeClock(), document_id=document_id, job_id=None, attempt=2, step="extract"
        ),
    ):
        raise ValueError("document text")

    row = only_step(engine)
    assert row.status is StepStatus.FAILED
    assert row.error_code == "ValueError"
    assert row.attempt == 2


def test_step_without_a_model_has_no_usage(engine: Engine, document_id: uuid.UUID) -> None:
    with run_step(
        engine, FakeClock(), document_id=document_id, job_id=None, attempt=1, step="render"
    ):
        pass

    row = only_step(engine)
    assert row.input_tokens is None
    assert row.estimated_cost_usd is None


def test_audit_event_commits_with_the_callers_transaction(
    engine: Engine, document_id: uuid.UUID
) -> None:
    with Session(engine) as session:
        record_audit_event(session, document_id=document_id, actor_user_id=None, action="approved")
        session.rollback()

    with Session(engine) as session:
        assert session.scalars(select(AuditEvent)).all() == []


def test_seed_creates_fictional_records_and_is_repeatable(engine: Engine) -> None:
    for _ in range(2):
        with Session(engine) as session, session.begin():
            seed(session)

    with Session(engine) as session:
        users = session.scalars(select(User)).all()
        vendors = session.scalars(select(Vendor)).all()

    assert {user.role for user in users} == {Role.REVIEWER, Role.ADMIN}
    assert len(users) == 2
    assert len(vendors) == 4
    assert all(user.email.endswith("@example.com") for user in users)
    assert all(user.password_hash == UNUSABLE_PASSWORD for user in users)
