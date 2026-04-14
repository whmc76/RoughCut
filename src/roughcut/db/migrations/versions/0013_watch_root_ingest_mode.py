"""add ingest mode for watch roots

Revision ID: 0013_watch_root_ingest_mode
Revises: 0012_output_dir
Create Date: 2026-04-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision: str = "0013_watch_root_ingest_mode"
down_revision: str | None = "0012_output_dir"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "watch_roots",
        sa.Column("ingest_mode", sa.Text(), nullable=False, server_default="full_auto"),
    )


def downgrade() -> None:
    op.drop_column("watch_roots", "ingest_mode")
