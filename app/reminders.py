from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .extensions import db
from .models import Client, Reminder, utcnow
from .utils import STATUS_LABELS, local_to_utc_naive


bp = Blueprint("reminders", __name__, url_prefix="/reminders")


@bp.get("/")
@login_required
def index():
    selected_type = request.args.get("type", "")
    selected_status = request.args.get("status", "")
    statement = db.select(Reminder)
    if selected_type in {"call", "meeting"}:
        statement = statement.where(Reminder.reminder_type == selected_type)
    if selected_status in STATUS_LABELS:
        statement = statement.where(Reminder.status == selected_status)
    reminders = db.session.scalars(statement.order_by(Reminder.starts_at)).all()
    return render_template(
        "reminders/index.html",
        reminders=reminders,
        selected_type=selected_type,
        selected_status=selected_status,
        now=utcnow(),
    )


def apply_reminder_form(reminder):
    reminder.client_id = request.form.get("client_id", type=int)
    reminder.reminder_type = request.form.get("reminder_type", "")
    reminder.starts_at = local_to_utc_naive(request.form.get("starts_at"))
    reminder.topic = request.form.get("topic", "").strip()
    reminder.comment = request.form.get("comment", "").strip()
    reminder.status = request.form.get("status", "planned")
    reminder.notify_before_minutes = request.form.get(
        "notify_before_minutes", 60, type=int
    )
    reminder.meeting_format = request.form.get("meeting_format", "").strip()
    reminder.location_or_url = request.form.get("location_or_url", "").strip()


def validate_reminder(reminder):
    if reminder.reminder_type not in {"call", "meeting"}:
        return "Выберите тип напоминания."
    if not reminder.client_id or not reminder.starts_at or not reminder.topic:
        return "Выберите клиента, дату и укажите тему."
    if reminder.notify_before_minutes < 0:
        return "Время уведомления не может быть отрицательным."
    if reminder.reminder_type == "meeting" and reminder.meeting_format not in {
        "online",
        "in_person",
    }:
        return "Выберите формат встречи."
    return None


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    reminder = Reminder(reminder_type=request.args.get("type", "call"))
    clients = db.session.scalars(
        db.select(Client)
        .where(Client.archived_at.is_(None))
        .order_by(Client.full_name)
    ).all()
    if request.method == "POST":
        apply_reminder_form(reminder)
        error = validate_reminder(reminder)
        if error:
            flash(error, "error")
        else:
            db.session.add(reminder)
            db.session.commit()
            flash("Напоминание создано.", "success")
            return redirect(url_for("reminders.index"))
    return render_template(
        "reminders/form.html",
        reminder=reminder,
        clients=clients,
        statuses=STATUS_LABELS,
        title="Новое напоминание",
    )


@bp.route("/<int:reminder_id>/edit", methods=["GET", "POST"])
@login_required
def edit(reminder_id):
    reminder = db.get_or_404(Reminder, reminder_id)
    clients = db.session.scalars(
        db.select(Client)
        .where(Client.archived_at.is_(None))
        .order_by(Client.full_name)
    ).all()
    if request.method == "POST":
        apply_reminder_form(reminder)
        error = validate_reminder(reminder)
        if error:
            flash(error, "error")
        else:
            db.session.commit()
            flash("Напоминание обновлено.", "success")
            return redirect(url_for("reminders.index"))
    return render_template(
        "reminders/form.html",
        reminder=reminder,
        clients=clients,
        statuses=STATUS_LABELS,
        title="Редактирование напоминания",
    )


@bp.post("/<int:reminder_id>/status")
@login_required
def update_status(reminder_id):
    reminder = db.get_or_404(Reminder, reminder_id)
    status = request.form.get("status", "")
    if status not in STATUS_LABELS:
        flash("Некорректный статус.", "error")
    else:
        reminder.status = status
        db.session.commit()
        flash("Статус обновлён.", "success")
    return redirect(url_for("reminders.index"))


@bp.post("/<int:reminder_id>/delete")
@login_required
def delete(reminder_id):
    reminder = db.get_or_404(Reminder, reminder_id)
    db.session.delete(reminder)
    db.session.commit()
    flash("Напоминание удалено.", "success")
    return redirect(url_for("reminders.index"))
