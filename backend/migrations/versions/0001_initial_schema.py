"""initial schema

Revision ID: 0001
Revises: none
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A row trigger, so TRUNCATE still works: the demo reset (M13) needs it and is admin-only.
AUDIT_FUNCTION = """
CREATE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql
"""

AUDIT_TRIGGER = """
CREATE TRIGGER audit_events_append_only
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
"""


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "dead",
                name="jobstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'dead')", name=op.f("ck_jobs_jobstatus")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_jobs_idempotency_key")),
    )
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["run_after", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_jobs_dead",
        "jobs",
        ["updated_at"],
        unique=False,
        postgresql_where=sa.text("status = 'dead'"),
    )
    op.create_index(
        "ix_jobs_leases",
        "jobs",
        ["locked_until"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "role",
            sa.Enum("reviewer", "admin", name="role", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('reviewer', 'admin')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "vendors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendors")),
        sa.UniqueConstraint("normalized_name", name=op.f("uq_vendors_normalized_name")),
    )
    op.create_table(
        "batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("upload", "demo", "eval", name="batchsource", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("doc_cap", sa.Integer(), nullable=False),
        sa.Column("token_cap", sa.BigInteger(), nullable=False),
        sa.Column("tokens_used", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(precision=12, scale=6),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('upload', 'demo', 'eval')", name=op.f("ck_batches_batchsource")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_batches_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batches")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "processing",
                "auto_approved",
                "needs_review",
                "approved",
                "rejected",
                "failed",
                name="documentstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'auto_approved', 'needs_review', 'approved', 'rejected', 'failed')",
            name=op.f("ck_documents_documentstatus"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f("fk_documents_batch_id_batches")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("sha256", name=op.f("uq_documents_sha256")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_documents_storage_key")),
    )
    op.create_index(op.f("ix_documents_batch_id"), "documents", ["batch_id"], unique=False)
    op.create_index(
        "ix_documents_status_received_at", "documents", ["status", "received_at"], unique=False
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("field", sa.String(length=100), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_audit_events_actor_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_audit_events_document_id_documents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        op.f("ix_audit_events_document_id"), "audit_events", ["document_id"], unique=False
    )
    op.create_table(
        "extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("extractor", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "succeeded",
                "invalid",
                "refused",
                "input_too_large",
                "budget_exceeded",
                name="extractionoutcome",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("raw_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'invalid', 'refused', 'input_too_large', 'budget_exceeded')",
            name=op.f("ck_extractions_extractionoutcome"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_extractions_document_id_documents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extractions")),
        sa.UniqueConstraint(
            "document_id", "attempt", name=op.f("uq_extractions_document_id_attempt")
        ),
    )
    op.create_table(
        "run_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "running", "succeeded", "failed", name="stepstatus", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("extractor", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name=op.f("ck_run_steps_stepstatus")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_run_steps_document_id_documents")
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_run_steps_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_steps")),
    )
    op.create_index(op.f("ix_run_steps_document_id"), "run_steps", ["document_id"], unique=False)
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("target", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "delivered", "dead", name="deliverystatus", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'dead')",
            name=op.f("ck_webhook_deliveries_deliverystatus"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_webhook_deliveries_document_id_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
        sa.UniqueConstraint(
            "target", "event_id", name=op.f("uq_webhook_deliveries_target_event_id")
        ),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_document_id"),
        "webhook_deliveries",
        ["document_id"],
        unique=False,
    )
    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["webhook_deliveries.id"],
            name=op.f("fk_delivery_attempts_delivery_id_webhook_deliveries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_attempts")),
        sa.UniqueConstraint(
            "delivery_id", "attempt", name=op.f("uq_delivery_attempts_delivery_id_attempt")
        ),
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=True),
        sa.Column("vendor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "document_type",
            sa.Enum(
                "invoice", "receipt", "other", name="documenttype", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("vendor_name", sa.String(length=200), nullable=True),
        sa.Column("invoice_number", sa.String(length=100), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("tax_total", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("adjustments_total", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("total", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column(
            "overall_confidence",
            sa.Enum("high", "medium", "low", name="confidence", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "uncertain_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("contains_embedded_instructions", sa.Boolean(), nullable=False),
        sa.Column("normalized_vendor", sa.String(length=200), nullable=True),
        sa.Column("normalized_invoice_number", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "document_type IN ('invoice', 'receipt', 'other')",
            name=op.f("ck_invoices_documenttype"),
        ),
        sa.CheckConstraint(
            "overall_confidence IN ('high', 'medium', 'low')", name=op.f("ck_invoices_confidence")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_invoices_document_id_documents")
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["extractions.id"],
            name=op.f("fk_invoices_extraction_id_extractions"),
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"], ["vendors.id"], name=op.f("fk_invoices_vendor_id_vendors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("document_id", name=op.f("uq_invoices_document_id")),
    )
    op.create_index(
        "ix_invoices_dedupe_details",
        "invoices",
        ["normalized_vendor", "issue_date", "total"],
        unique=False,
    )
    op.create_index(
        "ix_invoices_dedupe_number",
        "invoices",
        ["normalized_vendor", "normalized_invoice_number"],
        unique=False,
    )
    op.create_table(
        "rule_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=True),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum("pass", "fail", "skip", name="ruleoutcome", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('pass', 'fail', 'skip')", name=op.f("ck_rule_results_ruleoutcome")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_rule_results_document_id_documents")
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["extractions.id"],
            name=op.f("fk_rule_results_extraction_id_extractions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_results")),
    )
    op.create_index(
        op.f("ix_rule_results_document_id"), "rule_results", ["document_id"], unique=False
    )
    op.create_table(
        "line_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_line_items_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_line_items")),
        sa.UniqueConstraint(
            "invoice_id", "position", name=op.f("uq_line_items_invoice_id_position")
        ),
    )
    op.execute(AUDIT_FUNCTION)
    op.execute(AUDIT_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
    op.drop_table("line_items")
    op.drop_index(op.f("ix_rule_results_document_id"), table_name="rule_results")
    op.drop_table("rule_results")
    op.drop_index("ix_invoices_dedupe_number", table_name="invoices")
    op.drop_index("ix_invoices_dedupe_details", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("delivery_attempts")
    op.drop_index(op.f("ix_webhook_deliveries_document_id"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index(op.f("ix_run_steps_document_id"), table_name="run_steps")
    op.drop_table("run_steps")
    op.drop_table("extractions")
    op.drop_index(op.f("ix_audit_events_document_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_documents_status_received_at", table_name="documents")
    op.drop_index(op.f("ix_documents_batch_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("batches")
    op.drop_table("vendors")
    op.drop_table("users")
    op.drop_index(
        "ix_jobs_leases", table_name="jobs", postgresql_where=sa.text("status = 'running'")
    )
    op.drop_index("ix_jobs_dead", table_name="jobs", postgresql_where=sa.text("status = 'dead'"))
    op.drop_index(
        "ix_jobs_claimable", table_name="jobs", postgresql_where=sa.text("status = 'queued'")
    )
    op.drop_table("jobs")
