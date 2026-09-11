"""unify calendar planning

Revision ID: 6c6404762d3e
Revises: ee79d7c7ccb1
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa


revision = "6c6404762d3e"
down_revision = "ee79d7c7ccb1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.alter_column(
            "client_id", existing_type=sa.Integer(), nullable=True
        )
        batch_op.add_column(
            sa.Column("source_interaction_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("title", sa.String(length=250), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("origin", sa.String(length=30), nullable=False, server_default="manual")
        )
        batch_op.add_column(
            sa.Column("meeting_format", sa.String(length=20), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("location_or_url", sa.String(length=500), nullable=False, server_default="")
        )
        batch_op.create_foreign_key(
            "fk_calendar_events_source_interaction",
            "interactions",
            ["source_interaction_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_calendar_events_source_interaction_id",
            ["source_interaction_id"],
            unique=True,
        )

    op.execute(
        sa.text(
            """
            INSERT INTO calendar_events
                (client_id, title, origin, event_type, starts_at, ends_at,
                 comment, status, meeting_format, location_or_url,
                 created_at, updated_at)
            SELECT client_id, topic, 'migrated_reminder', reminder_type,
                   starts_at, NULL, comment, status, meeting_format,
                   location_or_url, created_at, updated_at
            FROM reminders
            """
        )
    )
    op.drop_table("reminders")


def downgrade():
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("reminder_type", sa.String(length=20), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("topic", sa.String(length=250), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("notify_before_minutes", sa.Integer(), nullable=False),
        sa.Column("meeting_format", sa.String(length=20), nullable=False),
        sa.Column("location_or_url", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("reminders", schema=None) as batch_op:
        batch_op.create_index("ix_reminders_client_id", ["client_id"], unique=False)
        batch_op.create_index("ix_reminders_reminder_type", ["reminder_type"], unique=False)
        batch_op.create_index("ix_reminders_starts_at", ["starts_at"], unique=False)
    op.execute(
        sa.text(
            """
            INSERT INTO reminders
                (client_id, reminder_type, starts_at, topic, comment, status,
                 notify_before_minutes, meeting_format, location_or_url,
                 created_at, updated_at)
            SELECT client_id, event_type, starts_at, title, comment, status,
                   60, meeting_format, location_or_url, created_at, updated_at
            FROM calendar_events
            WHERE origin = 'migrated_reminder' AND client_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text("DELETE FROM calendar_events WHERE origin = 'migrated_reminder'")
    )
    op.execute(sa.text("DELETE FROM calendar_events WHERE client_id IS NULL"))
    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.drop_index("ix_calendar_events_source_interaction_id")
        batch_op.drop_constraint(
            "fk_calendar_events_source_interaction", type_="foreignkey"
        )
        batch_op.drop_column("location_or_url")
        batch_op.drop_column("meeting_format")
        batch_op.drop_column("origin")
        batch_op.drop_column("title")
        batch_op.drop_column("source_interaction_id")
        batch_op.alter_column(
            "client_id", existing_type=sa.Integer(), nullable=False
        )
