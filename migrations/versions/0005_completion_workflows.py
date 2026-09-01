"""Completion workflow records.

Revision ID: 0005_completion_workflows
Revises: 0004_call_sheets
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[import-not-found]
from sqlalchemy import inspect

revision = "0005_completion_workflows"
down_revision = "0004_call_sheets"
branch_labels = None
depends_on = None


def _inspector():
    return inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def upgrade() -> None:
    if "approval_state" not in _columns("boards"):
        op.add_column(
            "boards",
            sa.Column(
                "approval_state",
                sa.String(40),
                nullable=True,
                server_default="approved",
            ),
        )

    if "replan_requests" in _tables():
        replan_columns = _columns("replan_requests")
        with op.batch_alter_table("replan_requests") as batch:
            if "source_kind" not in replan_columns:
                batch.add_column(
                    sa.Column(
                        "source_kind",
                        sa.String(40),
                        nullable=True,
                        server_default="monitor",
                    )
                )
            if "source_id" not in replan_columns:
                batch.add_column(
                    sa.Column(
                        "source_id", sa.String(48), nullable=True, server_default=""
                    )
                )
            if "reason" not in replan_columns:
                batch.add_column(
                    sa.Column("reason", sa.Text(), nullable=True, server_default="")
                )
            if "finding_id" in replan_columns:
                batch.alter_column(
                    "finding_id", existing_type=sa.String(48), nullable=True
                )

    if "constraint_proposals" not in _tables():
        op.create_table(
            "constraint_proposals",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column("source_text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("validation_errors_json", sa.JSON(), nullable=True),
            sa.Column("created_by_name", sa.String(120), nullable=True),
            sa.Column("accepted_by_name", sa.String(120), nullable=True),
            sa.Column("accepted_by_role", sa.String(80), nullable=True),
            sa.Column("accepted_constraint_id", sa.String(48), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_constraint_proposals_production_id",
            "constraint_proposals",
            ["production_id"],
        )

    if "grounded_values" not in _tables():
        op.create_table(
            "grounded_values",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column(
                "evidence_id",
                sa.String(48),
                sa.ForeignKey("grounding_evidence.id"),
                nullable=False,
            ),
            sa.Column("fact_kind", sa.String(40), nullable=False),
            sa.Column("location_id", sa.String(120), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("normalized_value_json", sa.JSON(), nullable=True),
            sa.Column("units", sa.String(80), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("source_quote", sa.Text(), nullable=False),
            sa.Column("source_span", sa.Text(), nullable=False),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("provider_response_id", sa.String(160), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("derived_from", sa.String(40), nullable=False),
            sa.Column("validator_result_json", sa.JSON(), nullable=True),
            sa.Column("covering_date", sa.Boolean(), nullable=True),
            sa.Column("context_source_urls_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_grounded_values_production_id", "grounded_values", ["production_id"]
        )
        op.create_index(
            "ix_grounded_values_evidence_id", "grounded_values", ["evidence_id"]
        )

    if "monitored_sources" not in _tables():
        op.create_table(
            "monitored_sources",
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
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("fact_kind", sa.String(40), nullable=False),
            sa.Column("location_id", sa.String(120), nullable=True),
            sa.Column("query", sa.Text(), nullable=True),
            sa.Column("provider", sa.String(80), nullable=True),
            sa.Column("external_monitor_id", sa.String(160), nullable=True),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("last_fingerprint", sa.String(64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_monitored_sources_production_id", "monitored_sources", ["production_id"]
        )
        op.create_index(
            "ix_monitored_sources_board_id", "monitored_sources", ["board_id"]
        )

    if "monitor_change_events" not in _tables():
        op.create_table(
            "monitor_change_events",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column(
                "monitored_source_id",
                sa.String(48),
                sa.ForeignKey("monitored_sources.id"),
                nullable=True,
            ),
            sa.Column(
                "board_id", sa.String(48), sa.ForeignKey("boards.id"), nullable=False
            ),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("material", sa.Boolean(), nullable=True),
            sa.Column("old_fingerprint", sa.String(64), nullable=True),
            sa.Column("new_fingerprint", sa.String(64), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("finding_id", sa.String(48), nullable=True),
            sa.Column("replan_request_id", sa.String(48), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_monitor_change_events_production_id",
            "monitor_change_events",
            ["production_id"],
        )
        op.create_index(
            "ix_monitor_change_events_monitored_source_id",
            "monitor_change_events",
            ["monitored_source_id"],
        )
        op.create_index(
            "ix_monitor_change_events_board_id", "monitor_change_events", ["board_id"]
        )

    if "schedule_diffs" not in _tables():
        op.create_table(
            "schedule_diffs",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column(
                "base_board_id",
                sa.String(48),
                sa.ForeignKey("boards.id"),
                nullable=False,
            ),
            sa.Column(
                "revised_board_id",
                sa.String(48),
                sa.ForeignKey("boards.id"),
                nullable=False,
            ),
            sa.Column(
                "replan_request_id",
                sa.String(48),
                sa.ForeignKey("replan_requests.id"),
                nullable=True,
            ),
            sa.Column("diff_json", sa.JSON(), nullable=False),
            sa.Column("required_approvals_json", sa.JSON(), nullable=True),
            sa.Column("cost_delta", sa.Float(), nullable=True),
            sa.Column("rendered_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_schedule_diffs_production_id", "schedule_diffs", ["production_id"]
        )
        op.create_index(
            "ix_schedule_diffs_base_board_id", "schedule_diffs", ["base_board_id"]
        )
        op.create_index(
            "ix_schedule_diffs_revised_board_id", "schedule_diffs", ["revised_board_id"]
        )
        op.create_index(
            "ix_schedule_diffs_replan_request_id",
            "schedule_diffs",
            ["replan_request_id"],
        )

    if "coverage_items" not in _tables():
        op.create_table(
            "coverage_items",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column("scene_id", sa.String(120), nullable=False),
            sa.Column("coverage_key", sa.String(160), nullable=False),
            sa.Column("coverage_type", sa.String(80), nullable=False),
            sa.Column("planned_json", sa.JSON(), nullable=True),
            sa.Column("shot_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "production_id", "coverage_key", name="uq_coverage_items_key"
            ),
        )
        op.create_index(
            "ix_coverage_items_production_id", "coverage_items", ["production_id"]
        )

    if "coverage_findings" not in _tables():
        op.create_table(
            "coverage_findings",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column(
                "production_id",
                sa.String(48),
                sa.ForeignKey("productions.id"),
                nullable=False,
            ),
            sa.Column(
                "coverage_item_id",
                sa.String(48),
                sa.ForeignKey("coverage_items.id"),
                nullable=False,
            ),
            sa.Column(
                "board_id", sa.String(48), sa.ForeignKey("boards.id"), nullable=True
            ),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("severity", sa.String(40), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("raised_by_name", sa.String(120), nullable=False),
            sa.Column("raised_by_role", sa.String(80), nullable=False),
            sa.Column("human_raised", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_coverage_findings_production_id", "coverage_findings", ["production_id"]
        )
        op.create_index(
            "ix_coverage_findings_coverage_item_id",
            "coverage_findings",
            ["coverage_item_id"],
        )

    if "pickup_tasks" not in _tables():
        op.create_table(
            "pickup_tasks",
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
                sa.ForeignKey("coverage_findings.id"),
                nullable=False,
            ),
            sa.Column(
                "coverage_item_id",
                sa.String(48),
                sa.ForeignKey("coverage_items.id"),
                nullable=False,
            ),
            sa.Column(
                "board_id", sa.String(48), sa.ForeignKey("boards.id"), nullable=True
            ),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("scene_id", sa.String(120), nullable=False),
            sa.Column("pickup_spec_json", sa.JSON(), nullable=True),
            sa.Column("decision_json", sa.JSON(), nullable=True),
            sa.Column("requested_by_name", sa.String(120), nullable=False),
            sa.Column("requested_by_role", sa.String(80), nullable=False),
            sa.Column("confirmed_by_name", sa.String(120), nullable=True),
            sa.Column("confirmed_by_role", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("finding_id", name="uq_pickup_tasks_finding"),
        )
        op.create_index(
            "ix_pickup_tasks_production_id", "pickup_tasks", ["production_id"]
        )
        op.create_index("ix_pickup_tasks_finding_id", "pickup_tasks", ["finding_id"])
        op.create_index(
            "ix_pickup_tasks_coverage_item_id", "pickup_tasks", ["coverage_item_id"]
        )


def downgrade() -> None:
    if "pickup_tasks" in _tables():
        op.drop_index("ix_pickup_tasks_coverage_item_id", table_name="pickup_tasks")
        op.drop_index("ix_pickup_tasks_finding_id", table_name="pickup_tasks")
        op.drop_index("ix_pickup_tasks_production_id", table_name="pickup_tasks")
        op.drop_table("pickup_tasks")
    if "coverage_findings" in _tables():
        op.drop_index(
            "ix_coverage_findings_coverage_item_id", table_name="coverage_findings"
        )
        op.drop_index(
            "ix_coverage_findings_production_id", table_name="coverage_findings"
        )
        op.drop_table("coverage_findings")
    if "coverage_items" in _tables():
        op.drop_index("ix_coverage_items_production_id", table_name="coverage_items")
        op.drop_table("coverage_items")
    if "schedule_diffs" in _tables():
        op.drop_index(
            "ix_schedule_diffs_replan_request_id", table_name="schedule_diffs"
        )
        op.drop_index("ix_schedule_diffs_revised_board_id", table_name="schedule_diffs")
        op.drop_index("ix_schedule_diffs_base_board_id", table_name="schedule_diffs")
        op.drop_index("ix_schedule_diffs_production_id", table_name="schedule_diffs")
        op.drop_table("schedule_diffs")
    if "monitor_change_events" in _tables():
        op.drop_index(
            "ix_monitor_change_events_board_id", table_name="monitor_change_events"
        )
        op.drop_index(
            "ix_monitor_change_events_monitored_source_id",
            table_name="monitor_change_events",
        )
        op.drop_index(
            "ix_monitor_change_events_production_id", table_name="monitor_change_events"
        )
        op.drop_table("monitor_change_events")
    if "monitored_sources" in _tables():
        op.drop_index("ix_monitored_sources_board_id", table_name="monitored_sources")
        op.drop_index(
            "ix_monitored_sources_production_id", table_name="monitored_sources"
        )
        op.drop_table("monitored_sources")
    if "grounded_values" in _tables():
        op.drop_index("ix_grounded_values_evidence_id", table_name="grounded_values")
        op.drop_index("ix_grounded_values_production_id", table_name="grounded_values")
        op.drop_table("grounded_values")
    if "constraint_proposals" in _tables():
        op.drop_index(
            "ix_constraint_proposals_production_id", table_name="constraint_proposals"
        )
        op.drop_table("constraint_proposals")
    if "replan_requests" in _tables():
        replan_columns = _columns("replan_requests")
        with op.batch_alter_table("replan_requests") as batch:
            if "reason" in replan_columns:
                batch.drop_column("reason")
            if "source_id" in replan_columns:
                batch.drop_column("source_id")
            if "source_kind" in replan_columns:
                batch.drop_column("source_kind")
    if "approval_state" in _columns("boards"):
        op.drop_column("boards", "approval_state")
