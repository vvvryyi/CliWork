"""add client groups and event lifecycle

Revision ID: 9b71d2c4a8e3
Revises: 6c6404762d3e
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


revision = "9b71d2c4a8e3"
down_revision = "6c6404762d3e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "client_group",
                sa.String(length=20),
                nullable=False,
                server_default="none",
            )
        )
        batch_op.create_index(
            batch_op.f("ix_clients_client_group"), ["client_group"], unique=False
        )

    with op.batch_alter_table("interactions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("submission_token", sa.String(length=64), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_interactions_submission_token", ["submission_token"]
        )

    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("completed_by_interaction_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "is_important", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_calendar_events_completed_by_interaction_id"),
            ["completed_by_interaction_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_calendar_events_completed_by_interaction_id",
            "interactions",
            ["completed_by_interaction_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_calendar_events_completed_by_interaction_id", type_="foreignkey"
        )
        batch_op.drop_index(
            batch_op.f("ix_calendar_events_completed_by_interaction_id")
        )
        batch_op.drop_column("completed_at")
        batch_op.drop_column("is_important")
        batch_op.drop_column("completed_by_interaction_id")

    with op.batch_alter_table("interactions", schema=None) as batch_op:
        batch_op.drop_constraint("uq_interactions_submission_token", type_="unique")
        batch_op.drop_column("submission_token")

    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clients_client_group"))
        batch_op.drop_column("client_group")
