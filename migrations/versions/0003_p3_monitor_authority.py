"""P3 monitor, replan, and authority records.

Revision ID: 0003_p3_monitor_authority
Revises: 0002_p2_jobs_grounding
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[import-not-found]
from sqlalchemy import inspect

revision = "0003_p3_monitor_authority"
down_revision = "0002_p2_jobs_grounding"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()

    if "locked_days" not in tables:
        op.create_table(
            "locked_days",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column(
                "board_id", sa.String(48), sa.ForeignKey("boards.id"), nullable=False
            ),
            sa.Column("schedule_run_id", sa.String(48), nullable=False),
            sa.Column("shoot_date", sa.Date(), nullable=False),
            sa.Column("locked_assignments_json", sa.JSON(), nullable=True),
            sa.Column("locations_json", sa.JSON(), nullable=True),
            sa.Column("cast_json", sa.JSON(), nullable=True),
            sa.Column("call_sheet_version", sa.String(120), nullable=False),
            sa.Column("recorded_by_name", sa.String(120), nullable=False),
            sa.Column("recorded_by_role", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "board_id", "shoot_date", name="uq_locked_days_board_date"
            ),
        )
        op.create_index(
            "ix_locked_days_production_id", "locked_days", ["production_id"]
        )
        op.create_index("ix_locked_days_board_id", "locked_days", ["board_id"])

    if "monitor_findings" not in tables:
        op.create_table(
            "monitor_findings",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column(
                "board_id", sa.String(48), sa.ForeignKey("boards.id"), nullable=False
            ),
            sa.Column(
                "evidence_id",
                sa.String(48),
                sa.ForeignKey("grounding_evidence.id"),
                nullable=True,
            ),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("fact_kind", sa.String(40), nullable=False),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("material", sa.Boolean(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("old_fingerprint", sa.String(64), nullable=True),
            sa.Column("new_fingerprint", sa.String(64), nullable=True),
            sa.Column("old_value_json", sa.JSON(), nullable=True),
            sa.Column("new_value_json", sa.JSON(), nullable=True),
            sa.Column("affected_work_ids_json", sa.JSON(), nullable=True),
            sa.Column("requester_component", sa.String(80), nullable=True),
            sa.Column("reviewed_by_name", sa.String(120), nullable=True),
            sa.Column("reviewed_by_role", sa.String(80), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_monitor_findings_production_id", "monitor_findings", ["production_id"]
        )
        op.create_index(
            "ix_monitor_findings_board_id", "monitor_findings", ["board_id"]
        )

    if "replan_requests" not in tables:
        op.create_table(
            "replan_requests",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column(
                "finding_id",
                sa.String(48),
                sa.ForeignKey("monitor_findings.id"),
                nullable=False,
            ),
            sa.Column(
                "current_board_id",
                sa.String(48),
                sa.ForeignKey("boards.id"),
                nullable=False,
            ),
            sa.Column("requester_component", sa.String(80), nullable=False),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("affected_work_ids_json", sa.JSON(), nullable=True),
            sa.Column("locked_days_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_replan_requests_production_id", "replan_requests", ["production_id"]
        )
        op.create_index(
            "ix_replan_requests_finding_id", "replan_requests", ["finding_id"]
        )
        op.create_index(
            "ix_replan_requests_current_board_id",
            "replan_requests",
            ["current_board_id"],
        )

    if "board_selections" not in tables:
        op.create_table(
            "board_selections",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column("prior_board_id", sa.String(48), nullable=True),
            sa.Column(
                "selected_board_id",
                sa.String(48),
                sa.ForeignKey("boards.id"),
                nullable=False,
            ),
            sa.Column("prior_schedule_run_id", sa.String(48), nullable=True),
            sa.Column("new_schedule_run_id", sa.String(48), nullable=False),
            sa.Column("actor_name", sa.String(120), nullable=False),
            sa.Column("actor_role", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_board_selections_production_id", "board_selections", ["production_id"]
        )
        op.create_index(
            "ix_board_selections_selected_board_id",
            "board_selections",
            ["selected_board_id"],
        )

    if "cost_approvals" not in tables:
        op.create_table(
            "cost_approvals",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column(
                "board_id", sa.String(48), sa.ForeignKey("boards.id"), nullable=False
            ),
            sa.Column("approver_name", sa.String(120), nullable=False),
            sa.Column("approver_role", sa.String(80), nullable=False),
            sa.Column("cost_delta", sa.Float(), nullable=True),
            sa.Column("added_shoot_days_json", sa.JSON(), nullable=True),
            sa.Column("decision", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_cost_approvals_production_id", "cost_approvals", ["production_id"]
        )
        op.create_index("ix_cost_approvals_board_id", "cost_approvals", ["board_id"])


def downgrade() -> None:
    tables = _tables()
    for table, indexes in (
        (
            "cost_approvals",
            ("ix_cost_approvals_board_id", "ix_cost_approvals_production_id"),
        ),
        (
            "board_selections",
            (
                "ix_board_selections_selected_board_id",
                "ix_board_selections_production_id",
            ),
        ),
        (
            "replan_requests",
            (
                "ix_replan_requests_current_board_id",
                "ix_replan_requests_finding_id",
                "ix_replan_requests_production_id",
            ),
        ),
        (
            "monitor_findings",
            ("ix_monitor_findings_board_id", "ix_monitor_findings_production_id"),
        ),
        ("locked_days", ("ix_locked_days_board_id", "ix_locked_days_production_id")),
    ):
        if table not in tables:
            continue
        for index in indexes:
            op.drop_index(index, table_name=table)
        op.drop_table(table)
