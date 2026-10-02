"""Allow history dates to be removed from client records.

Revision ID: 3e2d60c8a174
Revises: d7e5b3a9c1f2
"""

from alembic import op
import sqlalchemy as sa


revision = "3e2d60c8a174"
down_revision = "d7e5b3a9c1f2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("interactions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("show_history_date", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade():
    with op.batch_alter_table("interactions", schema=None) as batch_op:
        batch_op.drop_column("show_history_date")
