from datetime import timedelta

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from .extensions import db
from .models import CalendarEvent, Client, utcnow
from .utils import local_to_utc_naive, utc_naive_to_local


bp = Blueprint("main", __name__)


@bp.get("/")
@login_required
def dashboard():
    now = utcnow()
    local_today = utc_naive_to_local(now).date()
    week_start = local_today - timedelta(days=local_today.weekday())
    week_end = week_start + timedelta(days=7)
    query_start = local_to_utc_naive(f"{week_start.isoformat()}T00:00")
    query_end = local_to_utc_naive(f"{week_end.isoformat()}T00:00")
    client_count = db.session.scalar(
        db.select(func.count(Client.id)).where(Client.archived_at.is_(None))
    )
    overdue_count = db.session.scalar(
        db.select(func.count(CalendarEvent.id)).where(
            CalendarEvent.starts_at < now,
            CalendarEvent.status == "planned",
        )
    )
    week_events = db.session.scalars(
        db.select(CalendarEvent)
        .where(
            CalendarEvent.starts_at >= query_start,
            CalendarEvent.starts_at < query_end,
            CalendarEvent.status == "planned",
        )
        .order_by(CalendarEvent.starts_at)
    ).all()
    return render_template(
        "dashboard.html",
        client_count=client_count or 0,
        overdue_count=overdue_count or 0,
        week_events=week_events,
        week_start=week_start,
        week_end=week_end - timedelta(days=1),
    )
