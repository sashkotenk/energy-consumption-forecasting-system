"""add dataset import reporting

Revision ID: 3f61c7a2e904
Revises: 8b31f6f2d912
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3f61c7a2e904"
down_revision: str | None = "8b31f6f2d912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_imports",
        sa.Column("import_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="app",
    )
    op.add_column(
        "dataset_imports",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_table(
        "dataset_import_errors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("import_id", sa.UUID(), nullable=False),
        sa.Column("source_row_number", sa.BigInteger(), nullable=False),
        sa.Column("parse_status", sa.String(length=20), server_default="invalid", nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("column_name", sa.String(length=100), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("parse_status = 'invalid'"),
        sa.CheckConstraint("source_row_number >= 1"),
        sa.ForeignKeyConstraint(["import_id"], ["app.dataset_imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_import_errors_import_row",
        "dataset_import_errors",
        ["import_id", "source_row_number"],
        unique=False,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_import_errors_import_row", table_name="dataset_import_errors", schema="app")
    op.drop_table("dataset_import_errors", schema="app")
    op.drop_column("dataset_imports", "completed_at", schema="app")
    op.drop_column("dataset_imports", "import_report", schema="app")
