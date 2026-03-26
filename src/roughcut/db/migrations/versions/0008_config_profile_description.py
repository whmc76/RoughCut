"""add description to config profiles

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-26

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("config_profiles", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("config_profiles", "description")
