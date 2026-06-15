"""creator-bound agent asset workspace

Revision ID: 0020_creator_agent_assets
Revises: 0019_pub_retry_fp
Create Date: 2026-06-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0020_creator_assets"
down_revision: str | None = "0019_pub_retry_fp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_cards",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("positioning", sa.Text(), nullable=True),
        sa.Column("content_domains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("default_platforms", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("natural_language_profile", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "creator_assets",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("creator_card_id", sa.Uuid(), sa.ForeignKey("creator_cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "creator_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("creator_card_id", sa.Uuid(), sa.ForeignKey("creator_cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("preference_type", sa.Text(), nullable=False),
        sa.Column("natural_language_rule", sa.Text(), nullable=False),
        sa.Column("structured_payload", sa.JSON(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "creator_task_strategies",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("creator_card_id", sa.Uuid(), sa.ForeignKey("creator_cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("strategy_type", sa.Text(), nullable=False, server_default="generic"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("strategy_payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "task_strategy_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.Uuid(), sa.ForeignKey("creator_task_strategies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False, server_default="generate"),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "creator_visual_plans",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("creator_card_id", sa.Uuid(), sa.ForeignKey("creator_cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("visual_payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "visual_plan_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("visual_plan_id", sa.Uuid(), sa.ForeignKey("creator_visual_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False, server_default="generate"),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "creator_publication_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("creator_card_id", sa.Uuid(), sa.ForeignKey("creator_cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("publication_payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("creator_card_id"),
    )
    op.create_table(
        "creator_platform_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("publication_profile_id", sa.Uuid(), sa.ForeignKey("creator_publication_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("credential_ref", sa.Text(), nullable=True),
        sa.Column("binding_payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("publication_profile_id", "platform"),
    )
    op.create_table(
        "publication_profile_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("publication_profile_id", sa.Uuid(), sa.ForeignKey("creator_publication_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False, server_default="refine"),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "job_agent_plans",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creator_card_id", sa.Uuid(), sa.ForeignKey("creator_cards.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_strategy_id", sa.Uuid(), sa.ForeignKey("creator_task_strategies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("visual_plan_id", sa.Uuid(), sa.ForeignKey("creator_visual_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("publication_profile_id", sa.Uuid(), sa.ForeignKey("creator_publication_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("plan_payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id"),
    )
    op.add_column("jobs", sa.Column("creator_card_id", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("task_brief", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("execution_mode", sa.Text(), nullable=False, server_default="auto"))
    op.add_column("jobs", sa.Column("platform_targets_json", sa.JSON(), nullable=False, server_default="[]"))
    op.create_foreign_key(
        "fk_jobs_creator_card_id_creator_cards",
        "jobs",
        "creator_cards",
        ["creator_card_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_jobs_creator_card_id_creator_cards", "jobs", type_="foreignkey")
    op.drop_column("jobs", "platform_targets_json")
    op.drop_column("jobs", "execution_mode")
    op.drop_column("jobs", "task_brief")
    op.drop_column("jobs", "creator_card_id")
    op.drop_table("job_agent_plans")
    op.drop_table("publication_profile_versions")
    op.drop_table("creator_platform_bindings")
    op.drop_table("creator_publication_profiles")
    op.drop_table("visual_plan_versions")
    op.drop_table("creator_visual_plans")
    op.drop_table("task_strategy_versions")
    op.drop_table("creator_task_strategies")
    op.drop_table("creator_preferences")
    op.drop_table("creator_assets")
    op.drop_table("creator_cards")
