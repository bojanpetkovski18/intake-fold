import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from conftest import alembic_config
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from intakefold.audit.records import record_audit_event
from intakefold.db.models import (
    AuditEvent,
    Base,
    Batch,
    BatchSource,
    Document,
    DocumentStatus,
    Job,
    JobStatus,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def blank_database_url(database_url: str) -> Iterator[str]:
    """A separate empty database, so these tests can downgrade without touching others."""
    name = f"migrations_{uuid.uuid4().hex}"
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {name}"))
    yield make_url(database_url).set(database=name).render_as_string(hide_password=False)
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE {name} WITH (FORCE)"))
    admin.dispose()


def table_names(url: str) -> set[str]:
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    return names


def make_document(session: Session) -> Document:
    batch = Batch(source=BatchSource.UPLOAD, doc_cap=25, token_cap=1000)
    session.add(batch)
    session.flush()
    document = Document(
        batch_id=batch.id,
        sha256=uuid.uuid4().hex * 2,
        original_filename="invoice.pdf",
        media_type="application/pdf",
        size_bytes=1,
        storage_key=uuid.uuid4().hex,
        status=DocumentStatus.QUEUED,
    )
    session.add(document)
    session.flush()
    return document


def test_upgrade_downgrade_upgrade(blank_database_url: str) -> None:
    config = alembic_config(blank_database_url)
    expected = {table.name for table in Base.metadata.sorted_tables}

    command.upgrade(config, "head")
    assert expected <= table_names(blank_database_url)

    command.downgrade(config, "base")
    assert table_names(blank_database_url) == {"alembic_version"}

    command.upgrade(config, "head")
    assert expected <= table_names(blank_database_url)


def test_migrations_match_the_models(engine: Engine) -> None:
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_each_enum_column_has_exactly_one_check_constraint(engine: Engine) -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT pg_get_constraintdef(oid) AS definition, count(*) AS copies "
                "FROM pg_constraint WHERE contype = 'c' AND connamespace = 'public'::regnamespace "
                "GROUP BY conrelid, definition"
            )
        ).all()

    assert rows
    assert all(row.copies == 1 for row in rows)


def test_enum_check_rejects_an_unknown_value_at_the_database(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs (id, kind, payload, idempotency_key, status, max_attempts, "
                "run_after) VALUES (gen_random_uuid(), 'k', '{}', 'key', 'nonsense', 1, now())"
            )
        )


def test_enums_are_stored_by_value(engine: Engine) -> None:
    with Session(engine) as session:
        make_document(session)
        session.commit()
    with engine.connect() as connection:
        stored = connection.scalar(text("SELECT status FROM documents"))

    assert stored == DocumentStatus.QUEUED.value


def test_document_sha256_is_unique(engine: Engine) -> None:
    with Session(engine) as session:
        first = make_document(session)
        second = make_document(session)
        second.sha256 = first.sha256
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_events SET new_value = 'forged'", "DELETE FROM audit_events"],
    ids=["update", "delete"],
)
def test_audit_events_cannot_be_changed_with_sql(engine: Engine, statement: str) -> None:
    with Session(engine) as session, session.begin():
        document = make_document(session)
        record_audit_event(
            session,
            document_id=document.id,
            actor_user_id=None,
            action="field_corrected",
            field="total",
            old_value="1.00",
            new_value="2.00",
        )

    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(text(statement))

    with Session(engine) as session:
        event = session.query(AuditEvent).one()
    assert event.new_value == "2.00"


def test_truncate_is_the_known_bypass_of_the_audit_trigger(engine: Engine) -> None:
    """The demo reset depends on this. Application code must use it nowhere else."""
    with Session(engine) as session, session.begin():
        document = make_document(session)
        record_audit_event(session, document_id=document.id, actor_user_id=None, action="uploaded")

    with engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_events"))
        remaining = connection.scalar(text("SELECT count(*) FROM audit_events"))

    assert remaining == 0


def test_jobs_default_to_no_attempts(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.execute(
            text(
                "INSERT INTO jobs (id, kind, payload, idempotency_key, status, max_attempts, "
                "run_after) VALUES (gen_random_uuid(), 'k', '{}', 'key', 'queued', 1, now())"
            )
        )
    with Session(engine) as session:
        job = session.query(Job).one()

    assert job.attempts == 0
    assert job.status is JobStatus.QUEUED
