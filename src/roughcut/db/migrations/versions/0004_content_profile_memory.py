"""content profile memory tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-12

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

TIMESTAMPTZ = sa.TIMESTAMP(timezone=True)

revision: str = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_profile_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("source_name", sa.Text, nullable=False),
        sa.Column("channel_profile", sa.Text),
        sa.Column("field_name", sa.Text, nullable=False),
        sa.Column("original_value", sa.Text),
        sa.Column("corrected_value", sa.Text, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_content_profile_corrections_field_name",
        "content_profile_corrections",
        ["field_name"],
    )

    op.create_table(
        "content_profile_keyword_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope_type", sa.Text, nullable=False, server_default="global"),
        sa.Column("scope_value", sa.Text, nullable=False, server_default=""),
        sa.Column("keyword", sa.Text, nullable=False),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("last_used_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.UniqueConstraint("scope_type", "scope_value", "keyword"),
    )
    op.create_index(
        "ix_content_profile_keyword_stats_scope",
        "content_profile_keyword_stats",
        ["scope_type", "scope_value"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_profile_keyword_stats_scope", table_name="content_profile_keyword_stats")
    op.drop_table("content_profile_keyword_stats")
    op.drop_index("ix_content_profile_corrections_field_name", table_name="content_profile_corrections")
    op.drop_table("content_profile_corrections")
