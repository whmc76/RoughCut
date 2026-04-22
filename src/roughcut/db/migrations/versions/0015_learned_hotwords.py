"""add learned hotword memory

Revision ID: 0015_learned_hotwords
Revises: 0014_watch_root_recursive
Create Date: 2026-04-22 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

TIMESTAMPTZ = sa.TIMESTAMP(timezone=True)

revision: str = "0015_learned_hotwords"
down_revision: str | None = "0014_watch_root_recursive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learned_hotwords",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_domain", sa.Text(), nullable=False, server_default=""),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("canonical_form", sa.Text(), nullable=False, server_default=""),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source", sa.Text(), nullable=False, server_default="content_profile_feedback"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("positive_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("negative_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.65"),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("last_seen_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("last_prompted_at", TIMESTAMPTZ),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.UniqueConstraint("subject_domain", "term", "canonical_form", "source"),
    )
    op.create_index(
        "ix_learned_hotwords_subject_domain_status",
        "learned_hotwords",
        ["subject_domain", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_learned_hotwords_subject_domain_status", table_name="learned_hotwords")
    op.drop_table("learned_hotwords")
