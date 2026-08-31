"""Initial Coverset service schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[import-not-found]
from sqlalchemy import inspect

from coverset.api.models import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "scene_candidates" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("scene_candidates")
        }
        if "proposal_scene_json" not in columns:
            op.add_column(
                "scene_candidates",
                sa.Column("proposal_scene_json", sa.JSON(), nullable=True),
            )
    if "screenplay_assets" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("screenplay_assets")
        }
        if "normalized_text_uri" not in columns:
            op.add_column(
                "screenplay_assets",
                sa.Column("normalized_text_uri", sa.Text(), nullable=True),
            )
        if "extraction_metadata" not in columns:
            op.add_column(
                "screenplay_assets",
                sa.Column("extraction_metadata", sa.JSON(), nullable=True),
            )
        if "extraction_error" not in columns:
            op.add_column(
                "screenplay_assets",
                sa.Column("extraction_error", sa.Text(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
