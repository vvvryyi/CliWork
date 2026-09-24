from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .extensions import db
from .models import CalendarEvent, Client, utcnow
from .task_service import delete_event_and_task, sync_task_from_event
from .utils import (
    EVENT_TYPE_LABELS,
    local_to_utc_naive,
    month_grid,
    PLANNING_END_YEAR,
    PLANNING_START_YEAR,
    synchronize_event_statuses,
    utc_naive_to_local,
)


bp = Blueprint("calendar", __name__, url_prefix="/calendar")

PLANNING_END = date(PLANNING_END_YEAR, 12, 31)
CALENDAR_START_YEAR = PLANNING_START_YEAR
MONTH_NAMES = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)


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
    synchronize_event_statuses()
    view = request.args.get("view", "month")
    if view not in {"day", "week", "month", "year", "overdue"}:
        view = "month"
    selected_date = parse_date(request.args.get("date"))
    if selected_date > PLANNING_END:
        selected_date = PLANNING_END
    if selected_date.year < CALENDAR_START_YEAR:
        selected_date = date(CALENDAR_START_YEAR, 1, 1)

    if view == "overdue":
        first_day = selected_date
        last_day = selected_date
        weeks = None
    elif view == "day":
        first_day = selected_date
        last_day = selected_date
        weeks = None
    elif view == "week":
        first_day = selected_date - timedelta(days=selected_date.weekday())
        last_day = first_day + timedelta(days=6)
        weeks = [list(first_day + timedelta(days=i) for i in range(7))]
    elif view == "month":
        first_day = selected_date.replace(day=1)
        if first_day.month == 12:
            next_month = first_day.replace(
                year=first_day.year + 1, month=1, day=1
            )
        else:
            next_month = first_day.replace(month=first_day.month + 1, day=1)
        last_day = next_month - timedelta(days=1)
        weeks = month_grid(first_day.year, first_day.month)
    else:
        first_day = date(selected_date.year, 1, 1)
        last_day = date(selected_date.year, 12, 31)
        weeks = None

    if view == "overdue":
        events = db.session.scalars(
            db.select(CalendarEvent)
            .where(
                CalendarEvent.status == "overdue",
            )
            .order_by(CalendarEvent.starts_at)
        ).all()
    else:
        query_start, _ = local_day_bounds(first_day)
        _, query_end = local_day_bounds(last_day)
        events = db.session.scalars(
            db.select(CalendarEvent)
            .where(
                CalendarEvent.starts_at >= query_start,
                CalendarEvent.starts_at < query_end,
                CalendarEvent.status.in_(("planned", "overdue")),
            )
            .order_by(CalendarEvent.starts_at)
        ).all()
    events_by_date = {}
    for event in events:
        local_date = utc_naive_to_local(event.starts_at).date()
        events_by_date.setdefault(local_date, []).append(event)
    today = utc_naive_to_local(utcnow()).date()
    highlighted_event_ids = {
        event.id
        for event in events
        if event.is_important
    }

    if view == "overdue":
        previous_date = selected_date
        next_date = selected_date
    elif view == "day":
        previous_date = first_day - timedelta(days=1)
        next_date = first_day + timedelta(days=1)
    elif view == "week":
        previous_date = first_day - timedelta(days=7)
        next_date = first_day + timedelta(days=7)
    elif view == "month":
        previous_date = (first_day - timedelta(days=1)).replace(day=1)
        next_date = last_day + timedelta(days=1)
    else:
        previous_date = date(first_day.year - 1, 1, 1)
        next_date = date(first_day.year + 1, 1, 1)

    year_months = []
    if view == "year":
        for month in range(1, 13):
            month_first = date(selected_date.year, month, 1)
            year_months.append(
                (month_first, MONTH_NAMES[month - 1], month_grid(selected_date.year, month))
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
        today=today,
        highlighted_event_ids=highlighted_event_ids,
        year_months=year_months,
        calendar_years=range(CALENDAR_START_YEAR, PLANNING_END.year + 1),
        planning_end=PLANNING_END,
    )


def apply_event_form(event):
    event.client_id = request.form.get("client_id", type=int)
    event.title = request.form.get("title", "").strip()
    event.event_type = request.form.get("event_type", "other")
    event.starts_at = local_to_utc_naive(request.form.get("starts_at"))
    event.ends_at = local_to_utc_naive(request.form.get("ends_at"))
    event.comment = request.form.get("comment", "").strip()
    if not event.status:
        event.status = "planned"


def validate_event(event):
    if not event.starts_at:
        return "Укажите дату дела."
    if not event.client_id and not event.title:
        return "Для личного дела укажите название."
    local_start = utc_naive_to_local(event.starts_at)
    if local_start.date() > PLANNING_END:
        return "Дела можно планировать не позднее 31.12.2031."
    if event.ends_at and event.ends_at < event.starts_at:
        return "Окончание не может быть раньше начала."
    if event.ends_at and utc_naive_to_local(event.ends_at).date() > PLANNING_END:
        return "Дела можно планировать не позднее 31.12.2031."
    return None


@bp.route("/events/new", methods=["GET", "POST"])
@login_required
def create_event():
    event = CalendarEvent(
        client_id=request.args.get("client_id", type=int),
        origin="manual",
        status="planned",
    )
    clients = db.session.scalars(
        db.select(Client)
        .where(Client.archived_at.is_(None))
        .order_by(Client.full_name)
    ).all()
    preset_date = parse_date(request.args.get("date"))
    if request.method == "POST":
        apply_event_form(event)
        error = validate_event(event)
        if error:
            flash(error, "error")
        else:
            db.session.add(event)
            db.session.flush()
            sync_task_from_event(event)
            db.session.commit()
            flash("Дело создано.", "success")
            return redirect(url_for("calendar.index"))
    return render_template(
        "calendar/form.html",
        event=event,
        clients=clients,
        event_types=EVENT_TYPE_LABELS,
        title="Новое дело",
        preset_date=preset_date,
        planning_end=PLANNING_END,
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
        error = validate_event(event)
        if error:
            flash(error, "error")
        else:
            sync_task_from_event(event)
            db.session.commit()
            flash("Дело обновлено.", "success")
            return redirect(url_for("calendar.index"))
    return render_template(
        "calendar/form.html",
        event=event,
        clients=clients,
        event_types=EVENT_TYPE_LABELS,
        title="Редактирование дела",
        preset_date=None,
        planning_end=PLANNING_END,
    )


@bp.post("/events/<int:event_id>/delete")
@login_required
def delete_event(event_id):
    event = db.get_or_404(CalendarEvent, event_id)
    delete_event_and_task(event)
    db.session.commit()
    flash("Дело удалено.", "success")
    return redirect(url_for("calendar.index"))
