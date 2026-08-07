"""add versioned quality reports

Revision ID: 71e4b5ca9021
Revises: 3f61c7a2e904
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "71e4b5ca9021"
down_revision: str | None = "3f61c7a2e904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RAW_PHYSICAL_CONSTRAINTS = (
    "raw_measurements_energy_kwh_check",
    "raw_measurements_active_power_kw_check",
    "raw_measurements_reactive_power_kw_check",
    "raw_measurements_voltage_v_check",
    "raw_measurements_current_a_check",
    "raw_measurements_sub_metering_1_wh_check",
    "raw_measurements_sub_metering_2_wh_check",
    "raw_measurements_sub_metering_3_wh_check",
)


def upgrade() -> None:
    for constraint in _RAW_PHYSICAL_CONSTRAINTS:
        op.drop_constraint(constraint, "raw_measurements", schema="ts", type_="check")

    op.create_table(
        "data_quality_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_version_id", sa.UUID(), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("engine_version", sa.String(length=80), nullable=False),
        sa.Column("expected_interval_seconds", sa.Integer(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("expected_interval_seconds IS NULL OR expected_interval_seconds > 0"),
        sa.CheckConstraint("report_version >= 1"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["app.dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_version_id", "report_version"),
        schema="app",
    )
    op.create_index(
        "ix_quality_reports_version_latest",
        "data_quality_reports",
        ["dataset_version_id", sa.literal_column("report_version DESC")],
        unique=False,
        schema="app",
    )
    op.drop_constraint(
        "data_quality_issues_issue_type_check",
        "data_quality_issues",
        schema="app",
        type_="check",
    )
    op.add_column(
        "data_quality_issues", sa.Column("report_id", sa.UUID(), nullable=True), schema="app"
    )
    op.add_column(
        "data_quality_issues",
        sa.Column("range_end", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.add_column(
        "data_quality_issues",
        sa.Column("occurrence_count", sa.BigInteger(), server_default="1", nullable=False),
        schema="app",
    )
    op.create_foreign_key(
        "fk_quality_issues_report",
        "data_quality_issues",
        "data_quality_reports",
        ["report_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_quality_issues_occurrence_count",
        "data_quality_issues",
        "occurrence_count >= 1",
        schema="app",
    )
    op.create_check_constraint(
        "ck_quality_issues_range",
        "data_quality_issues",
        "range_end IS NULL OR observed_at IS NULL OR range_end >= observed_at",
        schema="app",
    )
    op.create_check_constraint(
        "data_quality_issues_issue_type_check",
        "data_quality_issues",
        "issue_type IN ('missing', 'non_finite', 'physical_invalidity', "
        "'exact_duplicate', 'conflicting_duplicate', 'time_gap', 'timestamp_order', "
        "'statistical_anomaly', 'timezone_ambiguity', 'parse_error')",
        schema="app",
    )


def downgrade() -> None:
    op.drop_constraint(
        "data_quality_issues_issue_type_check",
        "data_quality_issues",
        schema="app",
        type_="check",
    )
    op.create_check_constraint(
        "data_quality_issues_issue_type_check",
        "data_quality_issues",
        "issue_type IN ('missing', 'exact_duplicate', 'conflicting_duplicate', "
        "'time_gap', 'invalid_value', 'statistical_anomaly', "
        "'timezone_ambiguity', 'parse_error')",
        schema="app",
    )
    op.drop_constraint("ck_quality_issues_range", "data_quality_issues", schema="app")
    op.drop_constraint("ck_quality_issues_occurrence_count", "data_quality_issues", schema="app")
    op.drop_constraint(
        "fk_quality_issues_report", "data_quality_issues", schema="app", type_="foreignkey"
    )
    op.drop_column("data_quality_issues", "occurrence_count", schema="app")
    op.drop_column("data_quality_issues", "range_end", schema="app")
    op.drop_column("data_quality_issues", "report_id", schema="app")
    op.drop_index(
        "ix_quality_reports_version_latest", table_name="data_quality_reports", schema="app"
    )
    op.drop_table("data_quality_reports", schema="app")

    physical_checks = {
        "raw_measurements_energy_kwh_check": "energy_kwh IS NULL OR energy_kwh >= 0",
        "raw_measurements_active_power_kw_check": "active_power_kw IS NULL OR active_power_kw >= 0",
        "raw_measurements_reactive_power_kw_check": (
            "reactive_power_kw IS NULL OR reactive_power_kw >= 0"
        ),
        "raw_measurements_voltage_v_check": "voltage_v IS NULL OR voltage_v > 0",
        "raw_measurements_current_a_check": "current_a IS NULL OR current_a >= 0",
        "raw_measurements_sub_metering_1_wh_check": (
            "sub_metering_1_wh IS NULL OR sub_metering_1_wh >= 0"
        ),
        "raw_measurements_sub_metering_2_wh_check": (
            "sub_metering_2_wh IS NULL OR sub_metering_2_wh >= 0"
        ),
        "raw_measurements_sub_metering_3_wh_check": (
            "sub_metering_3_wh IS NULL OR sub_metering_3_wh >= 0"
        ),
    }
    for name, expression in physical_checks.items():
        op.create_check_constraint(name, "raw_measurements", expression, schema="ts")
