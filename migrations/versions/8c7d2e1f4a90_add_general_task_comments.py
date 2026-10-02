"""Add comments to standalone general tasks.

Revision ID: 8c7d2e1f4a90
Revises: 3e2d60c8a174
"""

from alembic import op
import sqlalchemy as sa


revision = "8c7d2e1f4a90"
down_revision = "3e2d60c8a174"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("general_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("comment", sa.Text(), nullable=False, server_default="")
        )


def downgrade():
    with op.batch_alter_table("general_tasks", schema=None) as batch_op:
        batch_op.drop_column("comment")
