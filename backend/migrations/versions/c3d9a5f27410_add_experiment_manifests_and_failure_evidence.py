"""add experiment manifests and failure evidence

Revision ID: c3d9a5f27410
Revises: a842d6c4b109
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d9a5f27410"
down_revision: str | None = "a842d6c4b109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("result_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="ml",
    )
    op.add_column(
        "experiments", sa.Column("failure_code", sa.String(length=80), nullable=True), schema="ml"
    )
    op.add_column("experiments", sa.Column("failure_detail", sa.Text(), nullable=True), schema="ml")
    op.create_check_constraint(
        "ck_experiments_completed_manifest",
        "experiments",
        "status <> 'completed' OR result_manifest IS NOT NULL",
        schema="ml",
    )
    op.add_column(
        "model_runs", sa.Column("failure_code", sa.String(length=80), nullable=True), schema="ml"
    )
    op.add_column("model_runs", sa.Column("failure_detail", sa.Text(), nullable=True), schema="ml")


def downgrade() -> None:
    op.drop_column("model_runs", "failure_detail", schema="ml")
    op.drop_column("model_runs", "failure_code", schema="ml")
    op.drop_constraint(
        "ck_experiments_completed_manifest", "experiments", schema="ml", type_="check"
    )
    op.drop_column("experiments", "failure_detail", schema="ml")
    op.drop_column("experiments", "failure_code", schema="ml")
    op.drop_column("experiments", "result_manifest", schema="ml")
