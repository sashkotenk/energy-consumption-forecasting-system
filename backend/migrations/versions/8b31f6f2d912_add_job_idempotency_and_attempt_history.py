"""add job idempotency and attempt history

Revision ID: 8b31f6f2d912
Revises: 0aec62c65582
Create Date: 2026-08-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b31f6f2d912"
down_revision: str | None = "0aec62c65582"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        schema="app",
    )
    op.create_index(
        "ux_jobs_idempotency_key",
        "jobs",
        ["idempotency_key"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.CheckConstraint("attempt >= 1"),
        sa.CheckConstraint("finished_at IS NULL OR finished_at >= started_at"),
        sa.CheckConstraint("status IN ('running', 'cancelled', 'succeeded', 'failed', 'stale')"),
        sa.ForeignKeyConstraint(["job_id"], ["app.jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt"),
        schema="app",
    )
    op.create_index(
        "ix_job_attempts_job_started",
        "job_attempts",
        ["job_id", "started_at"],
        unique=False,
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_job_attempts_job_started", table_name="job_attempts", schema="app")
    op.drop_table("job_attempts", schema="app")
    op.drop_index("ux_jobs_idempotency_key", table_name="jobs", schema="app")
    op.drop_column("jobs", "idempotency_key", schema="app")
