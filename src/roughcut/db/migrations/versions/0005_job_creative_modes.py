"""job creative modes

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-12

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("workflow_mode", sa.Text(), nullable=False, server_default="standard_edit"),
    )
    op.add_column(
        "jobs",
        sa.Column("enhancement_modes", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "enhancement_modes")
    op.drop_column("jobs", "workflow_mode")
