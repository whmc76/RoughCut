"""add output_dir fields to jobs and watch roots

Revision ID: 0012_output_dir
Revises: 0011_watch_root_cfg
Create Date: 2026-04-06

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0012_output_dir"
down_revision = "0011_watch_root_cfg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("output_dir", sa.Text(), nullable=True))
    op.add_column("watch_roots", sa.Column("output_dir", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("watch_roots", "output_dir")
    op.drop_column("jobs", "output_dir")
