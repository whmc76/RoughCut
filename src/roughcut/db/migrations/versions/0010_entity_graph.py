"""entity graph memory tables

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-01

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

TIMESTAMPTZ = sa.TIMESTAMP(timezone=True)

revision: str = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_profile_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject_domain", sa.Text, nullable=False, server_default=""),
        sa.Column("brand", sa.Text, nullable=False, server_default=""),
        sa.Column("model", sa.Text, nullable=False, server_default=""),
        sa.Column("subject_type", sa.Text),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.UniqueConstraint("subject_domain", "brand", "model"),
    )

    op.create_table(
        "content_profile_entity_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_profile_entities.id", ondelete="CASCADE")),
        sa.Column("field_name", sa.Text, nullable=False),
        sa.Column("alias_value", sa.Text, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.UniqueConstraint("entity_id", "field_name", "alias_value"),
    )

    op.create_table(
        "content_profile_entity_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_profile_entities.id", ondelete="CASCADE")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("source_name", sa.Text),
        sa.Column("observation_type", sa.Text, nullable=False, server_default="manual_confirm"),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "content_profile_entity_rejections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("subject_domain", sa.Text, nullable=False, server_default=""),
        sa.Column("field_name", sa.Text, nullable=False),
        sa.Column("alias_value", sa.Text, nullable=False),
        sa.Column("canonical_value", sa.Text, nullable=False),
        sa.Column("override_value", sa.Text, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.UniqueConstraint("subject_domain", "field_name", "alias_value", "canonical_value", "override_value"),
    )


def downgrade() -> None:
    op.drop_table("content_profile_entity_rejections")
    op.drop_table("content_profile_entity_observations")
    op.drop_table("content_profile_entity_aliases")
    op.drop_table("content_profile_entities")
