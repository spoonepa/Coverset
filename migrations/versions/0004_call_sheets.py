"""Call-sheet records.

Revision ID: 0004_call_sheets
Revises: 0003_p3_monitor_authority
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[import-not-found]
from sqlalchemy import inspect

revision = "0004_call_sheets"
down_revision = "0003_p3_monitor_authority"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "call_sheets" in _tables():
        return
    op.create_table(
        "call_sheets",
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
        sa.Column("generated_by_name", sa.String(120), nullable=False),
        sa.Column("generated_by_role", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("board_id", "shoot_date", name="uq_call_sheets_board_date"),
    )
    op.create_index("ix_call_sheets_production_id", "call_sheets", ["production_id"])
    op.create_index("ix_call_sheets_board_id", "call_sheets", ["board_id"])


def downgrade() -> None:
    if "call_sheets" not in _tables():
        return
    op.drop_index("ix_call_sheets_board_id", table_name="call_sheets")
    op.drop_index("ix_call_sheets_production_id", table_name="call_sheets")
    op.drop_table("call_sheets")
