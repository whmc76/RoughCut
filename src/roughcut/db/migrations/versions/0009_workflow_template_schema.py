"""rename channel_profile schema to workflow_template/subject_domain

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-31

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _rename_column_if_needed(table_name: str, old_name: str, new_name: str) -> None:
    existing_columns = _column_names(table_name)
    if old_name not in existing_columns or new_name in existing_columns:
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            old_name,
            new_column_name=new_name,
            existing_type=sa.Text(),
            existing_nullable=True,
        )


def upgrade() -> None:
    _rename_column_if_needed("jobs", "channel_profile", "workflow_template")
    _rename_column_if_needed("watch_roots", "channel_profile", "workflow_template")
    _rename_column_if_needed("content_profile_corrections", "channel_profile", "subject_domain")

    op.execute(
        sa.text(
            "UPDATE content_profile_keyword_stats "
            "SET scope_type = 'subject_domain' "
            "WHERE scope_type = 'channel_profile'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE glossary_terms "
            "SET scope_type = 'workflow_template' "
            "WHERE scope_type = 'channel_profile'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE glossary_terms "
            "SET scope_type = 'channel_profile' "
            "WHERE scope_type = 'workflow_template'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE content_profile_keyword_stats "
            "SET scope_type = 'channel_profile' "
            "WHERE scope_type = 'subject_domain'"
        )
    )

    _rename_column_if_needed("content_profile_corrections", "subject_domain", "channel_profile")
    _rename_column_if_needed("watch_roots", "workflow_template", "channel_profile")
    _rename_column_if_needed("jobs", "workflow_template", "channel_profile")
