"""Persist schedule conflict metadata.

Revision ID: 0006_schedule_conflict_metadata
Revises: 0005_completion_workflows
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[import-not-found]
from sqlalchemy import inspect

revision = "0006_schedule_conflict_metadata"
down_revision = "0005_completion_workflows"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "conflict_json" not in _columns("schedule_runs"):
        op.add_column(
            "schedule_runs",
            sa.Column("conflict_json", sa.JSON(), nullable=True, server_default="{}"),
        )


def downgrade() -> None:
    if "conflict_json" in _columns("schedule_runs"):
        op.drop_column("schedule_runs", "conflict_json")
