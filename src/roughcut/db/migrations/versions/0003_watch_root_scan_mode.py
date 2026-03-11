"""watch root scan mode

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-11

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("watch_roots", sa.Column("scan_mode", sa.Text(), nullable=False, server_default="fast"))


def downgrade() -> None:
    op.drop_column("watch_roots", "scan_mode")
