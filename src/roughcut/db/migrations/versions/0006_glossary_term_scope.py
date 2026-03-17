from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0006_glossary_term_scope"
down_revision = "0005_job_creative_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("glossary_terms")}

    if "scope_type" not in existing_columns:
        op.add_column("glossary_terms", sa.Column("scope_type", sa.Text(), nullable=False, server_default="global"))
    if "scope_value" not in existing_columns:
        op.add_column("glossary_terms", sa.Column("scope_value", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("glossary_terms")}

    if "scope_value" in existing_columns:
        op.drop_column("glossary_terms", "scope_value")
    if "scope_type" in existing_columns:
        op.drop_column("glossary_terms", "scope_type")
