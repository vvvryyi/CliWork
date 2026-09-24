"""add importance marker to daily tasks

Revision ID: c3f8a1d9e2b4
Revises: b17c2e91f4aa
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "c3f8a1d9e2b4"
down_revision = "b17c2e91f4aa"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("daily_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_important",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("daily_tasks", schema=None) as batch_op:
        batch_op.drop_column("is_important")
