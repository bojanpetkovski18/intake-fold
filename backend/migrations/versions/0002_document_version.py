"""Add a version to documents, for optimistic concurrency between reviewers.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("documents", "version")
