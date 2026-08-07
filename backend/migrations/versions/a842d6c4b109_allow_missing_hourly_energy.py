"""allow missing hourly energy

Revision ID: a842d6c4b109
Revises: 71e4b5ca9021
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a842d6c4b109"
down_revision: str | None = "71e4b5ca9021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "hourly_observations_energy_kwh_check",
        "hourly_observations",
        schema="ts",
        type_="check",
    )
    op.alter_column(
        "hourly_observations",
        "energy_kwh",
        schema="ts",
        existing_type=sa.Double(),
        nullable=True,
    )
    op.create_check_constraint(
        "hourly_observations_energy_kwh_check",
        "hourly_observations",
        "energy_kwh IS NULL OR energy_kwh >= 0",
        schema="ts",
    )


def downgrade() -> None:
    op.execute("DELETE FROM ts.hourly_observations WHERE energy_kwh IS NULL")
    op.drop_constraint(
        "hourly_observations_energy_kwh_check",
        "hourly_observations",
        schema="ts",
        type_="check",
    )
    op.alter_column(
        "hourly_observations",
        "energy_kwh",
        schema="ts",
        existing_type=sa.Double(),
        nullable=False,
    )
    op.create_check_constraint(
        "hourly_observations_energy_kwh_check",
        "hourly_observations",
        "energy_kwh >= 0",
        schema="ts",
    )
