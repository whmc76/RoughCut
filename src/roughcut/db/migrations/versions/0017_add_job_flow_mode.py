"""add job flow mode

Revision ID: 0017_job_flow_mode
Revises: 0016_publication_attempts
Create Date: 2026-05-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0017_job_flow_mode"
down_revision: str | None = "0016_publication_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("job_flow_mode", sa.Text(), nullable=False, server_default="auto"))


def downgrade() -> None:
    op.drop_column("jobs", "job_flow_mode")
