"""add config profile binding for watch roots and job snapshots

Revision ID: 0011_watch_root_cfg
Revises: 0010
Create Date: 2026-04-02

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0011_watch_root_cfg"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("watch_roots", sa.Column("config_profile_id", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("config_profile_id", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("config_profile_snapshot_json", sa.JSON(), nullable=True))
    op.add_column("jobs", sa.Column("packaging_snapshot_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("watch_roots") as batch_op:
        batch_op.create_foreign_key(
            "fk_watch_roots_config_profile_id",
            "config_profiles",
            ["config_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.create_foreign_key(
            "fk_jobs_config_profile_id",
            "config_profiles",
            ["config_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("fk_jobs_config_profile_id", type_="foreignkey")

    with op.batch_alter_table("watch_roots") as batch_op:
        batch_op.drop_constraint("fk_watch_roots_config_profile_id", type_="foreignkey")

    op.drop_column("jobs", "packaging_snapshot_json")
    op.drop_column("jobs", "config_profile_snapshot_json")
    op.drop_column("jobs", "config_profile_id")
    op.drop_column("watch_roots", "config_profile_id")
