"""P2 async jobs and grounding persistence.

Revision ID: 0002_p2_jobs_grounding
Revises: 0001_initial_schema
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[import-not-found]
from sqlalchemy import inspect

revision = "0002_p2_jobs_grounding"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _unique_constraints(table: str) -> set[str]:
    return {
        str(constraint["name"])
        for constraint in inspect(op.get_bind()).get_unique_constraints(table)
        if constraint.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "grounding_evidence" not in tables:
        op.create_table(
            "grounding_evidence",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("production_id", sa.String(48), sa.ForeignKey("productions.id"), nullable=False),
            sa.Column("location_id", sa.String(120), nullable=False),
            sa.Column("fact_kind", sa.String(40), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_grounding_evidence_production_id",
            "grounding_evidence",
            ["production_id"],
        )

    if "constraints" in tables and "uq_constraints_id" not in _unique_constraints(
        "constraints"
    ):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("constraints") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_constraints_id", ["production_id", "constraint_id"]
                )
        else:
            op.create_unique_constraint(
                "uq_constraints_id", "constraints", ["production_id", "constraint_id"]
            )

    if "jobs" in tables:
        columns = _columns("jobs")
        if "production_id" not in columns:
            op.add_column("jobs", sa.Column("production_id", sa.String(48), nullable=True))
            op.create_index("ix_jobs_production_id", "jobs", ["production_id"])
        if "payload_json" not in columns:
            op.add_column("jobs", sa.Column("payload_json", sa.JSON(), nullable=True))
        if "result_json" not in columns:
            op.add_column("jobs", sa.Column("result_json", sa.JSON(), nullable=True))
        if "claimed_at" not in columns:
            op.add_column("jobs", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
        if "completed_at" not in columns:
            op.add_column("jobs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "grounding_evidence" in tables:
        op.drop_index("ix_grounding_evidence_production_id", table_name="grounding_evidence")
        op.drop_table("grounding_evidence")
    if "jobs" in tables:
        columns = _columns("jobs")
        for name in (
            "completed_at",
            "claimed_at",
            "result_json",
            "payload_json",
            "production_id",
        ):
            if name in columns:
                if name == "production_id":
                    op.drop_index("ix_jobs_production_id", table_name="jobs")
                op.drop_column("jobs", name)
    if "constraints" in tables and "uq_constraints_id" in _unique_constraints("constraints"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("constraints") as batch_op:
                batch_op.drop_constraint("uq_constraints_id", type_="unique")
        else:
            op.drop_constraint("uq_constraints_id", "constraints", type_="unique")
