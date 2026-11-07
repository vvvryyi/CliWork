"""Add accounts and preserve existing workspace ownership."""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = "5a81e2c9d401"
down_revision = "4f7b9a20d831"
branch_labels = None
depends_on = None

TABLES = ("clients", "interactions", "attachments", "calendar_events", "daily_tasks", "general_tasks")


def upgrade():
    users = op.create_table("users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    for table in TABLES:
        op.add_column(table, sa.Column("owner_id", sa.String(64), nullable=False, server_default="local-user"))
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])
    op.bulk_insert(users, [{"id": "workspace-admin", "email": "da332381@gmail.com",
        "password_hash": 'scrypt:32768:8:1$RFvaoZsJVcxwvfCG$ca14f3c45a4d679100d51b2422c4d92d551e1d64659dc1cabc55e6bff5281271411c06c3fa9077bbc75a4d3fb05d935463beaf0fb0e03c5810f85e794d8f2c78', "is_admin": True,
        "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()}])


def downgrade():
    connection = op.get_bind()
    for table in TABLES:
        if connection.execute(sa.text(f"SELECT count(*) FROM {table} WHERE owner_id != 'local-user'")).scalar():
            raise RuntimeError("Private workspace data exists; restore a backup instead of downgrading.")
    if connection.execute(sa.text("SELECT count(*) FROM users WHERE id != 'workspace-admin'")).scalar():
        raise RuntimeError("Registered accounts exist; restore a backup instead of downgrading.")
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_owner_id")
            batch.drop_column("owner_id")
    op.drop_table("users")
