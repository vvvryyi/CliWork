"""Retain starred contact events in calendar history."""
from alembic import op
import sqlalchemy as sa

revision = "4f7b9a20d831"
down_revision = "2d8b6e41c930"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calendar_events") as batch_op:
        batch_op.add_column(sa.Column("is_starred", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("calendar_events") as batch_op:
        batch_op.drop_column("is_starred")
