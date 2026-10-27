"""Separate group D comments from the general client history.

Revision ID: 7a24c19e6b50
Revises: f05a1005c321
"""

from alembic import op
import sqlalchemy as sa


revision = "7a24c19e6b50"
down_revision = "f05a1005c321"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("interactions") as batch_op:
        batch_op.add_column(
            sa.Column("history_kind", sa.String(20), nullable=False, server_default="general")
        )
        batch_op.create_index("ix_interactions_history_kind", ["history_kind"])


def downgrade():
    with op.batch_alter_table("interactions") as batch_op:
        batch_op.drop_index("ix_interactions_history_kind")
        batch_op.drop_column("history_kind")
