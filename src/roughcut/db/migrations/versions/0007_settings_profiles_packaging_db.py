"""store settings, profiles, and packaging state in database

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-26

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

TIMESTAMPTZ = sa.TIMESTAMP(timezone=True)

revision: str = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value_json", _json_type()),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )
    op.create_table(
        "config_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("settings_json", _json_type(), nullable=False),
        sa.Column("packaging_json", _json_type(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "packaging_assets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("stored_name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("watermark_preprocessed", sa.Boolean()),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("packaging_assets")
    op.drop_table("config_profiles")
    op.drop_table("app_settings")
