"""Add independent color labels for contacts and comments.

Revision ID: 2d8b6e41c930
Revises: 7a24c19e6b50
"""

from alembic import op
import sqlalchemy as sa


revision = "2d8b6e41c930"
down_revision = "7a24c19e6b50"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(sa.Column("color_label", sa.String(20), nullable=False, server_default=""))
        batch_op.create_index("ix_clients_color_label", ["color_label"])
    with op.batch_alter_table("interactions") as batch_op:
        batch_op.add_column(sa.Column("color_label", sa.String(20), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("interactions") as batch_op:
        batch_op.drop_column("color_label")
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_index("ix_clients_color_label")
        batch_op.drop_column("color_label")
