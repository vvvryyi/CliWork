from datetime import timedelta

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from .extensions import db
from .models import CalendarEvent, Client, DailyTask, utcnow
from .utils import (
    local_to_utc_naive,
    synchronize_event_statuses,
    utc_naive_to_local,
)


bp = Blueprint("main", __name__)


@bp.get("/")
@login_required
def dashboard():
    now = utcnow()
    synchronize_event_statuses(now)
    local_today = utc_naive_to_local(now).date()
    week_start = local_today - timedelta(days=local_today.weekday())
    week_end = week_start + timedelta(days=7)
    query_start = local_to_utc_naive(f"{week_start.isoformat()}T00:00")
    query_end = local_to_utc_naive(f"{week_end.isoformat()}T00:00")
    client_count = db.session.scalar(
        db.select(func.count(Client.id)).where(
            Client.archived_at.is_(None),
            Client.client_group == "active",
        )
    )
    overdue_events = db.session.scalars(
        db.select(CalendarEvent)
        .join(Client, CalendarEvent.client_id == Client.id)
        .where(
            CalendarEvent.status == "overdue",
            Client.archived_at.is_(None),
        )
        .order_by(CalendarEvent.starts_at)
    ).all()
    overdue_clients = []
    seen_client_ids = set()
    for event in overdue_events:
        if event.client_id in seen_client_ids:
            continue
        seen_client_ids.add(event.client_id)
        overdue_clients.append(event)
    overdue_count = len(overdue_clients)
    task_count = db.session.scalar(
        db.select(func.count(DailyTask.id)).where(
            DailyTask.completed_at.is_(None),
            DailyTask.due_date <= local_today,
        )
    )
    week_events = db.session.scalars(
        db.select(CalendarEvent)
        .where(
            CalendarEvent.starts_at >= query_start,
            CalendarEvent.starts_at < query_end,
            CalendarEvent.status.in_(("planned", "overdue")),
        )
        .order_by(CalendarEvent.starts_at)
    ).all()
    return render_template(
        "dashboard.html",
        client_count=client_count or 0,
        overdue_count=overdue_count or 0,
        overdue_clients=overdue_clients,
        task_count=task_count or 0,
        week_events=week_events,
        week_start=week_start,
        week_end=week_end - timedelta(days=1),
    )
