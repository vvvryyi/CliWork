from datetime import timedelta

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from .extensions import db
from .models import CalendarEvent, Client, Reminder, utcnow


bp = Blueprint("main", __name__)


@bp.get("/")
@login_required
def dashboard():
    now = utcnow()
    upcoming_limit = now + timedelta(days=7)
    client_count = db.session.scalar(
        db.select(func.count(Client.id)).where(Client.archived_at.is_(None))
    )
    overdue_count = db.session.scalar(
        db.select(func.count(Reminder.id)).where(
            Reminder.starts_at < now,
            Reminder.status == "planned",
        )
    )
    upcoming_reminders = db.session.scalars(
        db.select(Reminder)
        .where(
            Reminder.starts_at >= now,
            Reminder.starts_at <= upcoming_limit,
            Reminder.status == "planned",
        )
        .order_by(Reminder.starts_at)
        .limit(8)
    ).all()
    upcoming_events = db.session.scalars(
        db.select(CalendarEvent)
        .where(
            CalendarEvent.starts_at >= now,
            CalendarEvent.starts_at <= upcoming_limit,
            CalendarEvent.status == "planned",
        )
        .order_by(CalendarEvent.starts_at)
        .limit(8)
    ).all()
    return render_template(
        "dashboard.html",
        client_count=client_count or 0,
        overdue_count=overdue_count or 0,
        upcoming_reminders=upcoming_reminders,
        upcoming_events=upcoming_events,
    )
