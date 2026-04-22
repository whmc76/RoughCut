"""add recursive flag to watch roots

Revision ID: 0014_watch_root_recursive
Revises: 0013_watch_root_ingest_mode
Create Date: 2026-04-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0014_watch_root_recursive"
down_revision: str | None = "0013_watch_root_ingest_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watch_roots",
        sa.Column("recursive", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("watch_roots", "recursive")
