"""add watch root job flow mode

Revision ID: 0018_watch_root_job_flow
Revises: 0017_job_flow_mode
Create Date: 2026-05-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0018_watch_root_job_flow"
down_revision: str | None = "0017_job_flow_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("watch_roots", sa.Column("job_flow_mode", sa.Text(), nullable=False, server_default="auto"))


def downgrade() -> None:
    op.drop_column("watch_roots", "job_flow_mode")
