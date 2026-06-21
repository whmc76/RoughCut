"""watch root product controls

Revision ID: 0021_watch_root_product_controls
Revises: 0020_creator_assets
Create Date: 2026-06-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0021_watch_root_product_controls"
down_revision: str | None = "0020_creator_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("watch_roots", sa.Column("edit_mode", sa.Text(), nullable=False, server_default="auto"))
    op.add_column("watch_roots", sa.Column("automation_level", sa.Text(), nullable=False, server_default="standard"))
    op.add_column("watch_roots", sa.Column("material_usage", sa.Text(), nullable=False, server_default="all_uploaded"))


def downgrade() -> None:
    op.drop_column("watch_roots", "material_usage")
    op.drop_column("watch_roots", "automation_level")
    op.drop_column("watch_roots", "edit_mode")
