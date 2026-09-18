"""link daily tasks to calendar and add numeric percent

Revision ID: a92d4e71bc03
Revises: f4a81b2c7d90
Create Date: 2026-09-18
"""

from datetime import datetime, time, timedelta, timezone

from alembic import op
import sqlalchemy as sa


revision = "a92d4e71bc03"
down_revision = "f4a81b2c7d90"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("percent_value", sa.Integer(), nullable=True))

    with op.batch_alter_table("daily_tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("calendar_event_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_daily_tasks_calendar_event_id",
            "calendar_events",
            ["calendar_event_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_daily_tasks_calendar_event_id",
            ["calendar_event_id"],
            unique=True,
        )

    bind = op.get_bind()
    metadata = sa.MetaData()
    tasks = sa.Table("daily_tasks", metadata, autoload_with=bind)
    events = sa.Table("calendar_events", metadata, autoload_with=bind)
    clients = sa.Table("clients", metadata, autoload_with=bind)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for task in bind.execute(sa.select(tasks)).mappings():
        starts_at = datetime.combine(task["due_date"], time(hour=6))
        result = bind.execute(
            events.insert().values(
                client_id=None,
                source_interaction_id=None,
                completed_by_interaction_id=None,
                title=task["text"][:250],
                origin="daily_task",
                event_type="task",
                starts_at=starts_at,
                ends_at=None,
                comment="",
                status=(
                    "completed"
                    if task["completed_at"]
                    else ("overdue" if starts_at < now else "planned")
                ),
                is_important=False,
                completed_at=task["completed_at"],
                meeting_format="",
                location_or_url="",
                external_uid=None,
                external_href="",
                external_etag="",
                external_hash="",
                last_synced_at=None,
                created_at=task["created_at"],
                updated_at=task["updated_at"],
            )
        )
        event_id = result.inserted_primary_key[0]
        bind.execute(
            tasks.update()
            .where(tasks.c.id == task["id"])
            .values(calendar_event_id=event_id)
        )

    client_names = dict(
        bind.execute(sa.select(clients.c.id, clients.c.full_name)).tuples().all()
    )
    linked_event_ids = set(
        bind.execute(
            sa.select(tasks.c.calendar_event_id).where(
                tasks.c.calendar_event_id.is_not(None)
            )
        ).scalars()
    )
    existing_events = bind.execute(
        sa.select(events).where(events.c.origin.in_(("manual", "icloud")))
    ).mappings()
    for event in existing_events:
        if event["id"] in linked_event_ids:
            continue
        title = (event["title"] or "").strip()
        if not title and event["client_id"]:
            title = client_names.get(event["client_id"], "")
        bind.execute(
            tasks.insert().values(
                calendar_event_id=event["id"],
                text=(title or "Дело")[:500],
                due_date=(event["starts_at"] + timedelta(hours=3)).date(),
                completed_at=(
                    event["completed_at"]
                    if event["status"] in ("completed", "cancelled")
                    else None
                ),
                created_at=event["created_at"],
                updated_at=event["updated_at"],
            )
        )


def downgrade():
    op.execute(
        sa.text(
            "DELETE FROM daily_tasks WHERE calendar_event_id IN "
            "(SELECT id FROM calendar_events WHERE origin IN ('manual', 'icloud'))"
        )
    )
    op.execute(sa.text("DELETE FROM calendar_events WHERE origin = 'daily_task'"))

    with op.batch_alter_table("daily_tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_daily_tasks_calendar_event_id")
        batch_op.drop_constraint(
            "fk_daily_tasks_calendar_event_id", type_="foreignkey"
        )
        batch_op.drop_column("calendar_event_id")

    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.drop_column("percent_value")
