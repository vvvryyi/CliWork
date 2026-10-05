"""Link optional general task execution dates to calendar events.

Revision ID: f05a1005c321
Revises: 8c7d2e1f4a90
"""

from alembic import op
import sqlalchemy as sa


revision = "f05a1005c321"
down_revision = "8c7d2e1f4a90"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("general_tasks") as batch_op:
        batch_op.add_column(sa.Column("due_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("calendar_event_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_general_tasks_calendar_event_id",
            "calendar_events",
            ["calendar_event_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_general_tasks_calendar_event_id", ["calendar_event_id"]
        )
        batch_op.create_index("ix_general_tasks_due_date", ["due_date"])
        batch_op.create_index("ix_general_tasks_calendar_event_id", ["calendar_event_id"])


def downgrade():
    with op.batch_alter_table("general_tasks") as batch_op:
        batch_op.drop_index("ix_general_tasks_calendar_event_id")
        batch_op.drop_index("ix_general_tasks_due_date")
        batch_op.drop_constraint("uq_general_tasks_calendar_event_id", type_="unique")
        batch_op.drop_constraint("fk_general_tasks_calendar_event_id", type_="foreignkey")
        batch_op.drop_column("calendar_event_id")
        batch_op.drop_column("due_date")
