from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_glossary_term_scope"
down_revision = "0005_job_creative_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("glossary_terms", sa.Column("scope_type", sa.Text(), nullable=False, server_default="global"))
    op.add_column("glossary_terms", sa.Column("scope_value", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("glossary_terms", "scope_value")
    op.drop_column("glossary_terms", "scope_type")
