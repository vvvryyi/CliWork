from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from .extensions import db
from .models import DailyTask, GeneralTask, utcnow
from .task_service import daily_task_sort_key
from .utils import (
    due_client_contact_events,
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
    contact_clients = due_client_contact_events(now)
    overdue_contact_ids = {
        event.id
        for event in contact_clients
        if utc_naive_to_local(event.starts_at).date() < local_today
    }
    contact_count = len(contact_clients)
    task_count = db.session.scalar(
        db.select(func.count(DailyTask.id)).where(
            DailyTask.completed_at.is_(None),
            DailyTask.due_date == local_today,
        )
    )
    general_task_count = db.session.scalar(
        db.select(func.count(GeneralTask.id)).where(
            GeneralTask.completed_at.is_(None)
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
        contact_count=contact_count,
        contact_clients=contact_clients,
        overdue_contact_ids=overdue_contact_ids,
        task_count=task_count or 0,
        general_task_count=general_task_count or 0,
        today_tasks=today_tasks,
        today=local_today,
    )
