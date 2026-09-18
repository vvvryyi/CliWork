"""add client workflow tasks and calendar sync

Revision ID: f4a81b2c7d90
Revises: 9b71d2c4a8e3
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa


revision = "f4a81b2c7d90"
down_revision = "9b71d2c4a8e3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients", schema=None) as batch_op:
        for name in ("flag_f", "flag_d", "flag_b", "flag_n", "flag_percent", "flag_ki", "flag_ku", "flag_ks", "flag_kr"):
            batch_op.add_column(sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("quarterly_reminder_mmdd", sa.String(length=4), nullable=False, server_default=""))

    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("external_uid", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("external_href", sa.String(length=1000), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("external_etag", sa.String(length=255), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("external_hash", sa.String(length=64), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("last_synced_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_calendar_events_external_uid"), ["external_uid"], unique=True)

    op.create_table(
        "daily_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("daily_tasks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_daily_tasks_due_date"), ["due_date"], unique=False)


def downgrade():
    with op.batch_alter_table("daily_tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_daily_tasks_due_date"))
    op.drop_table("daily_tasks")

    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_calendar_events_external_uid"))
        batch_op.drop_column("last_synced_at")
        batch_op.drop_column("external_etag")
        batch_op.drop_column("external_hash")
        batch_op.drop_column("external_href")
        batch_op.drop_column("external_uid")

    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.drop_column("quarterly_reminder_mmdd")
        for name in reversed(("flag_f", "flag_d", "flag_b", "flag_n", "flag_percent", "flag_ki", "flag_ku", "flag_ks", "flag_kr")):
            batch_op.drop_column(name)
