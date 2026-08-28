from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .extensions import db
from .models import CalendarEvent, Client, utcnow
from .utils import (
    EVENT_TYPE_LABELS,
    STATUS_LABELS,
    local_to_utc_naive,
    month_grid,
    utc_naive_to_local,
)


bp = Blueprint("calendar", __name__, url_prefix="/calendar")


def parse_date(value, fallback=None):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return fallback or utc_naive_to_local(utcnow()).date()


def local_day_bounds(day):
    start = local_to_utc_naive(f"{day.isoformat()}T00:00")
    end = local_to_utc_naive(f"{(day + timedelta(days=1)).isoformat()}T00:00")
    return start, end


@bp.get("/")
@login_required
def index():
    view = request.args.get("view", "month")
    if view not in {"day", "week", "month"}:
        view = "month"
    selected_date = parse_date(request.args.get("date"))

    if view == "day":
        first_day = selected_date
        last_day = selected_date
        weeks = None
    elif view == "week":
        first_day = selected_date - timedelta(days=selected_date.weekday())
        last_day = first_day + timedelta(days=6)
        weeks = [list(first_day + timedelta(days=i) for i in range(7))]
    else:
        first_day = selected_date.replace(day=1)
        if first_day.month == 12:
            next_month = first_day.replace(
                year=first_day.year + 1, month=1, day=1
            )
        else:
            next_month = first_day.replace(month=first_day.month + 1, day=1)
        last_day = next_month - timedelta(days=1)
        weeks = month_grid(first_day.year, first_day.month)

    query_start, _ = local_day_bounds(first_day)
    _, query_end = local_day_bounds(last_day)
    events = db.session.scalars(
        db.select(CalendarEvent)
        .where(
            CalendarEvent.starts_at >= query_start,
            CalendarEvent.starts_at < query_end,
        )
        .order_by(CalendarEvent.starts_at)
    ).all()
    events_by_date = {}
    for event in events:
        local_date = utc_naive_to_local(event.starts_at).date()
        events_by_date.setdefault(local_date, []).append(event)

    previous_date = (
        first_day - timedelta(days=1 if view == "day" else 7)
        if view != "month"
        else (first_day - timedelta(days=1)).replace(day=1)
    )
    next_date = (
        first_day + timedelta(days=1 if view == "day" else 7)
        if view != "month"
        else (last_day + timedelta(days=1))
    )
    return render_template(
        "calendar/index.html",
        view=view,
        selected_date=selected_date,
        first_day=first_day,
        last_day=last_day,
        weeks=weeks,
        events=events,
        events_by_date=events_by_date,
        previous_date=previous_date,
        next_date=next_date,
        today=utc_naive_to_local(utcnow()).date(),
    )


def apply_event_form(event):
    event.client_id = request.form.get("client_id", type=int)
    event.event_type = request.form.get("event_type", "other")
    event.starts_at = local_to_utc_naive(request.form.get("starts_at"))
    event.ends_at = local_to_utc_naive(request.form.get("ends_at"))
    event.comment = request.form.get("comment", "").strip()
    event.status = request.form.get("status", "planned")


@bp.route("/events/new", methods=["GET", "POST"])
@login_required
def create_event():
    event = CalendarEvent()
    clients = db.session.scalars(
        db.select(Client)
        .where(Client.archived_at.is_(None))
        .order_by(Client.full_name)
    ).all()
    preset_date = parse_date(request.args.get("date"))
    if request.method == "POST":
        apply_event_form(event)
        if not event.client_id or not event.starts_at:
            flash("Выберите клиента и дату события.", "error")
        elif event.ends_at and event.ends_at < event.starts_at:
            flash("Окончание не может быть раньше начала.", "error")
        else:
            db.session.add(event)
            db.session.commit()
            flash("Событие создано.", "success")
            return redirect(url_for("calendar.index"))
    return render_template(
        "calendar/form.html",
        event=event,
        clients=clients,
        event_types=EVENT_TYPE_LABELS,
        statuses=STATUS_LABELS,
        title="Новое событие",
        preset_date=preset_date,
    )


@bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    event = db.get_or_404(CalendarEvent, event_id)
    clients = db.session.scalars(
        db.select(Client)
        .where(Client.archived_at.is_(None))
        .order_by(Client.full_name)
    ).all()
    if request.method == "POST":
        apply_event_form(event)
        if not event.client_id or not event.starts_at:
            flash("Выберите клиента и дату события.", "error")
        elif event.ends_at and event.ends_at < event.starts_at:
            flash("Окончание не может быть раньше начала.", "error")
        else:
            db.session.commit()
            flash("Событие обновлено.", "success")
            return redirect(url_for("calendar.index"))
    return render_template(
        "calendar/form.html",
        event=event,
        clients=clients,
        event_types=EVENT_TYPE_LABELS,
        statuses=STATUS_LABELS,
        title="Редактирование события",
        preset_date=None,
    )


@bp.post("/events/<int:event_id>/delete")
@login_required
def delete_event(event_id):
    event = db.get_or_404(CalendarEvent, event_id)
    db.session.delete(event)
    db.session.commit()
    flash("Событие удалено.", "success")
    return redirect(url_for("calendar.index"))
