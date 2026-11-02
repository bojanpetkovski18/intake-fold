import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Money = Numeric(14, 4)
Cost = Numeric(12, 6)
Timestamp = DateTime(timezone=True)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Role(enum.StrEnum):
    REVIEWER = "reviewer"
    ADMIN = "admin"


class BatchSource(enum.StrEnum):
    UPLOAD = "upload"
    DEMO = "demo"
    EVAL = "eval"


class DocumentStatus(enum.StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    AUTO_APPROVED = "auto_approved"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class ExtractionOutcome(enum.StrEnum):
    SUCCEEDED = "succeeded"
    INVALID = "invalid"
    REFUSED = "refused"
    INPUT_TOO_LARGE = "input_too_large"
    BUDGET_EXCEEDED = "budget_exceeded"


class DocumentType(enum.StrEnum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    OTHER = "other"


class Confidence(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RuleOutcome(enum.StrEnum):
    PASS = "pass"  # noqa: S105 - a rule result, not a password
    FAIL = "fail"
    SKIP = "skip"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEAD = "dead"


class StepStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    DEAD = "dead"


def enum_values(members: type[enum.Enum]) -> list[str]:
    return [str(member.value) for member in members]


def stored_enum(enum_type: type[enum.StrEnum]) -> Enum:
    # A checked string, not a native enum: adding a value is then an ordinary migration.
    return Enum(
        enum_type,
        name=enum_type.__name__.lower(),
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=enum_values,
    )


def new_id() -> uuid.UUID:
    return uuid.uuid7()  # Time-ordered, so primary key indexes stay compact.


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(stored_enum(Role))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(Timestamp, index=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    source: Mapped[BatchSource] = mapped_column(stored_enum(BatchSource))
    doc_cap: Mapped[int] = mapped_column(Integer)
    token_cap: Mapped[int] = mapped_column(BigInteger)
    tokens_used: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Cost, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_status_received_at", "status", "received_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[DocumentStatus] = mapped_column(stored_enum(DocumentStatus))
    status_reasons: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    # Every reviewer action names the version it saw, so two reviewers cannot overwrite each other.
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    received_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Extraction(Base):
    __tablename__ = "extractions"
    __table_args__ = (UniqueConstraint("document_id", "attempt"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    extractor: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[ExtractionOutcome] = mapped_column(stored_enum(ExtractionOutcome))
    raw_output: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_dedupe_number", "normalized_vendor", "normalized_invoice_number"),
        Index("ix_invoices_dedupe_details", "normalized_vendor", "issue_date", "total"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extractions.id"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    document_type: Mapped[DocumentType] = mapped_column(stored_enum(DocumentType))
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax_total: Mapped[Decimal | None] = mapped_column(Money)
    adjustments_total: Mapped[Decimal | None] = mapped_column(Money)
    total: Mapped[Decimal | None] = mapped_column(Money)
    overall_confidence: Mapped[Confidence] = mapped_column(stored_enum(Confidence))
    uncertain_fields: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    contains_embedded_instructions: Mapped[bool] = mapped_column(Boolean)
    normalized_vendor: Mapped[str | None] = mapped_column(String(200))
    normalized_invoice_number: Mapped[str | None] = mapped_column(String(100))


class LineItem(Base):
    __tablename__ = "line_items"
    __table_args__ = (UniqueConstraint("invoice_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Money)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    amount: Mapped[Decimal | None] = mapped_column(Money)


class RuleResult(Base):
    __tablename__ = "rule_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extractions.id"))
    rule: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[RuleOutcome] = mapped_column(stored_enum(RuleOutcome))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # Partial indexes: the live rows are few, and the finished ones pile up.
        Index(
            "ix_jobs_claimable",
            "run_after",
            "id",
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_jobs_leases", "locked_until", postgresql_where=text("status = 'running'")),
        Index("ix_jobs_dead", "updated_at", postgresql_where=text("status = 'dead'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[JobStatus] = mapped_column(stored_enum(JobStatus))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer)
    run_after: Mapped[datetime] = mapped_column(Timestamp)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_until: Mapped[datetime | None] = mapped_column(Timestamp)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    step: Mapped[str] = mapped_column(String(64))
    status: Mapped[StepStatus] = mapped_column(stored_enum(StepStatus))
    started_at: Mapped[datetime] = mapped_column(Timestamp)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    extractor: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Cost)
    error_code: Mapped[str | None] = mapped_column(String(64))


class AuditEvent(Base):
    """Append-only: a trigger in the initial migration blocks UPDATE and DELETE."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    field: Mapped[str | None] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("target", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    target: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[uuid.UUID] = mapped_column(default=new_id)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[DeliveryStatus] = mapped_column(stored_enum(DeliveryStatus))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"
    __table_args__ = (UniqueConstraint("delivery_id", "attempt"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_deliveries.id", ondelete="CASCADE")
    )
    attempt: Mapped[int] = mapped_column(Integer)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())
