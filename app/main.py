from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from .extensions import db
from .models import CalendarEvent, Client, DailyTask, utcnow
from .task_service import daily_task_sort_key
from .utils import (
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
            DailyTask.due_date == local_today,
        )
    )
    today_tasks = db.session.scalars(
        db.select(DailyTask)
        .where(DailyTask.due_date == local_today)
        .order_by(DailyTask.id)
    ).all()
    today_tasks.sort(key=daily_task_sort_key)
    return render_template(
        "dashboard.html",
        overdue_count=overdue_count or 0,
        overdue_clients=overdue_clients,
        task_count=task_count or 0,
        today_tasks=today_tasks,
        today=local_today,
    )
