"""allow multiple publication attempts per fingerprint

Revision ID: 0019_publication_attempt_retry_fingerprints
Revises: 0018_watch_root_job_flow
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op


revision: str = "0019_pub_retry_fp"
down_revision: str | None = "0018_watch_root_job_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE publication_attempts DROP CONSTRAINT IF EXISTS publication_attempts_semantic_fingerprint_key"
    )
    op.create_index("idx_publication_attempts_fingerprint", "publication_attempts", ["semantic_fingerprint"])


def downgrade() -> None:
    op.drop_index("idx_publication_attempts_fingerprint", table_name="publication_attempts")
    op.create_unique_constraint(
        "publication_attempts_semantic_fingerprint_key",
        "publication_attempts",
        ["semantic_fingerprint"],
    )
