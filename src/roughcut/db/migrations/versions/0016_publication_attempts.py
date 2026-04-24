"""add publication attempts

Revision ID: 0016_publication_attempts
Revises: 0015_learned_hotwords
Create Date: 2026-04-24 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

TIMESTAMPTZ = sa.TIMESTAMP(timezone=True)

revision: str = "0016_publication_attempts"
down_revision: str | None = "0015_learned_hotwords"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publication_attempts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("creator_profile_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("creator_profile_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("platform_label", sa.Text(), nullable=False, server_default=""),
        sa.Column("account_label", sa.Text(), nullable=False, server_default=""),
        sa.Column("credential_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("semantic_fingerprint", sa.Text(), nullable=False, unique=True),
        sa.Column("adapter", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("run_status", sa.Text()),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("external_receipt_id", sa.Text()),
        sa.Column("external_post_id", sa.Text()),
        sa.Column("external_url", sa.Text()),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("request_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("response_payload", sa.JSON()),
        sa.Column("next_retry_at", TIMESTAMPTZ),
        sa.Column("scheduled_at", TIMESTAMPTZ),
        sa.Column("submitted_at", TIMESTAMPTZ),
        sa.Column("published_at", TIMESTAMPTZ),
        sa.Column("execution_mode", sa.Text(), nullable=False, server_default="browser_agent"),
        sa.Column("content_kind", sa.Text(), nullable=False, server_default="video"),
        sa.Column("provider_task_id", sa.Text()),
        sa.Column("provider_execution_id", sa.Text()),
        sa.Column("provider_status", sa.Text()),
        sa.Column("operator_summary", sa.Text()),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )
    op.create_index("idx_publication_attempts_job_platform", "publication_attempts", ["job_id", "platform"])
    op.create_index("idx_publication_attempts_status", "publication_attempts", ["status"])
    op.create_index("idx_publication_attempts_adapter_status", "publication_attempts", ["adapter", "status"])
    op.create_index("idx_publication_attempts_creator", "publication_attempts", ["creator_profile_id", "created_at"])

    op.create_table(
        "publication_attempt_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attempt_id", sa.Text(), sa.ForeignKey("publication_attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("platform", sa.Text(), nullable=False, server_default=""),
        sa.Column("adapter", sa.Text(), nullable=False, server_default=""),
        sa.Column("execution_mode", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_kind", sa.Text(), nullable=False, server_default=""),
        sa.Column("consumer_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("phase", sa.Text()),
        sa.Column("started_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("heartbeat_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("lease_expires_at", TIMESTAMPTZ),
        sa.Column("completed_at", TIMESTAMPTZ),
        sa.Column("provider_task_id", sa.Text()),
        sa.Column("provider_execution_id", sa.Text()),
        sa.Column("provider_status", sa.Text()),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )
    op.create_index("idx_publication_attempt_runs_attempt", "publication_attempt_runs", ["attempt_id", "created_at"])
    op.create_index("idx_publication_attempt_runs_status", "publication_attempt_runs", ["status", "heartbeat_at"])


def downgrade() -> None:
    op.drop_index("idx_publication_attempt_runs_status", table_name="publication_attempt_runs")
    op.drop_index("idx_publication_attempt_runs_attempt", table_name="publication_attempt_runs")
    op.drop_table("publication_attempt_runs")
    op.drop_index("idx_publication_attempts_creator", table_name="publication_attempts")
    op.drop_index("idx_publication_attempts_adapter_status", table_name="publication_attempts")
    op.drop_index("idx_publication_attempts_status", table_name="publication_attempts")
    op.drop_index("idx_publication_attempts_job_platform", table_name="publication_attempts")
    op.drop_table("publication_attempts")
