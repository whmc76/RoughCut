"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-10

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

TIMESTAMPTZ = sa.TIMESTAMP(timezone=True)

revision: str = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column("source_name", sa.Text, nullable=False),
        sa.Column("file_hash", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text),
        sa.Column("channel_profile", sa.Text),
        sa.Column("language", sa.Text, server_default="zh-CN"),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "job_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("step_name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer, server_default="0"),
        sa.Column("started_at", TIMESTAMPTZ),
        sa.Column("finished_at", TIMESTAMPTZ),
        sa.Column("error_message", sa.Text),
        sa.Column("metadata", postgresql.JSONB),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("job_steps.id")),
        sa.Column("artifact_type", sa.Text, nullable=False),
        sa.Column("storage_path", sa.Text),
        sa.Column("data_json", postgresql.JSONB),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "transcript_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("segment_index", sa.Integer, nullable=False),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
        sa.Column("speaker", sa.Text),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("words_json", postgresql.JSONB),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "subtitle_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("item_index", sa.Integer, nullable=False),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
        sa.Column("text_raw", sa.Text, nullable=False),
        sa.Column("text_norm", sa.Text),
        sa.Column("text_final", sa.Text),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "subtitle_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("subtitle_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subtitle_items.id")),
        sa.Column("original_span", sa.Text, nullable=False),
        sa.Column("suggested_span", sa.Text, nullable=False),
        sa.Column("change_type", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("source", sa.Text),
        sa.Column("auto_applied", sa.Boolean, server_default="false"),
        sa.Column("human_decision", sa.Text),
        sa.Column("human_override", sa.Text),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "fact_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("subtitle_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subtitle_items.id")),
        sa.Column("claim_text", sa.Text, nullable=False),
        sa.Column("risk_level", sa.Text, nullable=False),
        sa.Column("category", sa.Text),
        sa.Column("verdict", sa.Text),
        sa.Column("suggested_fix", sa.Text),
        sa.Column("confidence", sa.Float),
        sa.Column("human_decision", sa.Text),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "fact_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fact_claims.id", ondelete="CASCADE")),
        sa.Column("source_url", sa.Text),
        sa.Column("source_title", sa.Text),
        sa.Column("snippet", sa.Text),
        sa.Column("supports_claim", sa.Boolean),
        sa.Column("source_rank", sa.Integer),
        sa.Column("cached_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "timelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("timeline_type", sa.Text, nullable=False),
        sa.Column("data_json", postgresql.JSONB, nullable=False),
        sa.Column("otio_data", sa.Text),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "render_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("timeline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("timelines.id")),
        sa.Column("output_path", sa.Text),
        sa.Column("status", sa.Text, server_default="pending"),
        sa.Column("progress", sa.Float, server_default="0"),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "review_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("target_type", sa.Text, nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("override_text", sa.Text),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "watch_roots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("path", sa.Text, nullable=False, unique=True),
        sa.Column("channel_profile", sa.Text),
        sa.Column("enabled", sa.Boolean, server_default="true"),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "glossary_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("wrong_forms", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("correct_form", sa.Text, nullable=False),
        sa.Column("category", sa.Text),
        sa.Column("context_hint", sa.Text),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    op.create_table(
        "channel_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("config_json", postgresql.JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )

    # Indexes
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_file_hash", "jobs", ["file_hash"])
    op.create_index("ix_job_steps_job_id", "job_steps", ["job_id"])
    op.create_index("ix_job_steps_status", "job_steps", ["status"])
    op.create_index("ix_transcript_segments_job_id", "transcript_segments", ["job_id"])
    op.create_index("ix_subtitle_items_job_id", "subtitle_items", ["job_id"])


def downgrade() -> None:
    for tbl in [
        "channel_profiles",
        "glossary_terms",
        "watch_roots",
        "review_actions",
        "render_outputs",
        "timelines",
        "fact_evidence",
        "fact_claims",
        "subtitle_corrections",
        "subtitle_items",
        "transcript_segments",
        "artifacts",
        "job_steps",
        "jobs",
    ]:
        op.drop_table(tbl)
