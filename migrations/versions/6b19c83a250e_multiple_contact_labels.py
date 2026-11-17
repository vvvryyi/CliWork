"""Allow multiple labels while retaining the existing primary label."""
from alembic import op
import sqlalchemy as sa

revision = "6b19c83a250e"
down_revision = "5a81e2c9d401"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(sa.Column("color_labels", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_column("color_labels")
