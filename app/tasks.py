from datetime import date, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from .extensions import db
from .models import DailyTask, GeneralTask, utcnow
from .task_service import (
    create_daily_task,
    daily_task_sort_key,
    delete_task_and_event,
    sync_event_from_task,
    sync_event_from_general_task,
)
from .utils import PLANNING_END_YEAR, parse_display_date, utc_naive_to_local


bp = Blueprint("tasks", __name__, url_prefix="/tasks")

WEEKDAY_ABBREVIATIONS = ("пн.", "вт.", "ср.", "чт.", "пт.", "сб.", "вс.")


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return utc_naive_to_local(utcnow()).date()


@bp.get("/")
@login_required
def index():
    selected_date = parse_date(request.args.get("date"))
    tasks = db.session.scalars(
        db.select(DailyTask)
        .where(DailyTask.due_date == selected_date)
        .order_by(DailyTask.id)
    ).all()
    tasks.sort(key=daily_task_sort_key)
    return render_template(
        "tasks/index.html",
        tasks=tasks,
        selected_date=selected_date,
        weekday_abbreviation=WEEKDAY_ABBREVIATIONS[selected_date.weekday()],
        previous_date=selected_date - timedelta(days=1),
        next_date=selected_date + timedelta(days=1),
        today=utc_naive_to_local(utcnow()).date(),
        show_all=False,
    )


@bp.get("/all")
@login_required
def all_tasks():
    today = utc_naive_to_local(utcnow()).date()
    tasks = db.session.scalars(
        db.select(GeneralTask)
        .where(GeneralTask.completed_at.is_(None))
        .order_by(GeneralTask.id)
    ).all()
    tasks.sort(key=daily_task_sort_key)
    return render_template(
        "tasks/index.html",
        tasks=tasks,
        selected_date=today,
        today=today,
        show_all=True,
    )


@bp.route("/all/<int:task_id>", methods=["GET", "POST"])
@login_required
def general_detail(task_id):
    task = db.get_or_404(GeneralTask, task_id)
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if not text or len(text) > 500:
            flash("Введите название дела длиной до 500 символов.", "error")
        else:
            raw_date = request.form.get("due_date", "").strip()
            try:
                due_date = parse_display_date(raw_date) if raw_date else None
            except ValueError:
                due_date = None
                flash("Укажите корректную дату исполнения.", "error")
            else:
                if due_date and due_date.year > PLANNING_END_YEAR:
                    flash("Дела можно планировать не позднее 31.12.2031.", "error")
                else:
                    task.text = text
                    task.comment = request.form.get("comment", "").strip()
                    task.is_important = request.form.get("important") == "1"
                    task.due_date = due_date
                    sync_event_from_general_task(task)
                    db.session.commit()
                    flash("Дело обновлено.", "success")
                    return redirect(url_for("tasks.all_tasks"))
    return render_template("tasks/detail.html", task=task, planning_end=date(PLANNING_END_YEAR, 12, 31))


@bp.post("/new")
@login_required
def create():
    text = request.form.get("text", "").strip()
    due_date = parse_date(request.form.get("due_date"))
    if not text:
        flash("Введите текст дела.", "error")
    else:
        create_daily_task(text, due_date)
        db.session.commit()
        flash("Дело добавлено.", "success")
    return redirect(url_for("tasks.index", date=due_date.isoformat()))


@bp.post("/<int:task_id>/toggle")
@login_required
def toggle(task_id):
    task = db.get_or_404(DailyTask, task_id)
    task.completed_at = None if task.completed_at else utcnow()
    sync_event_from_task(task)
    db.session.commit()
    selected_date = parse_date(request.form.get("date"))
    return redirect(url_for("tasks.index", date=selected_date.isoformat()))


@bp.post("/<int:task_id>/delete")
@login_required
def delete(task_id):
    task = db.get_or_404(DailyTask, task_id)
    selected_date = parse_date(request.form.get("date"))
    delete_task_and_event(task)
    db.session.commit()
    flash("Дело удалено.", "success")
    return redirect(url_for("tasks.index", date=selected_date.isoformat()))


@bp.post("/save")
@login_required
def save():
    task_id = request.form.get("task_id", type=int)
    text = request.form.get("text", "").strip()[:500]
    due_date = parse_date(request.form.get("due_date"))
    task_scope = request.form.get("task_scope", "daily")
    is_general = task_scope == "general"
    should_delete = request.form.get("delete") == "1"
    completed = request.form.get("completed") == "1"
    important = request.form.get("important") == "1"

    task_model = GeneralTask if is_general else DailyTask
    task = db.get_or_404(task_model, task_id) if task_id else None

    general_due_date = None
    if is_general and task is None and request.form.get("due_date"):
        try:
            general_due_date = date.fromisoformat(request.form["due_date"])
        except ValueError:
            return jsonify({"error": "Укажите корректную дату исполнения."}), 400
        if general_due_date.year > PLANNING_END_YEAR:
            return jsonify({"error": "Дела можно планировать не позднее 31.12.2031."}), 400

    if should_delete or (task is not None and not text):
        if task is not None:
            if is_general:
                if task.calendar_event is not None:
                    db.session.delete(task.calendar_event)
                    task.calendar_event = None
                db.session.delete(task)
            else:
                delete_task_and_event(task)
        db.session.commit()
        return jsonify({"deleted": True, "task_id": task_id})
    if not text:
        return jsonify({"error": "Введите текст дела."}), 400

    if task is None:
        if is_general:
            task = GeneralTask(
                text=text,
                comment=request.form.get("comment", "").strip(),
                due_date=general_due_date,
                is_important=important,
                completed_at=utcnow() if completed else None,
            )
            db.session.add(task)
            sync_event_from_general_task(task)
        else:
            task = create_daily_task(
                text, due_date, completed=completed, important=important
            )
    else:
        task.text = text
        task.is_important = important
        task.completed_at = utcnow() if completed else None
        if is_general:
            sync_event_from_general_task(task)
        else:
            task.due_date = due_date
            sync_event_from_task(task)
    db.session.commit()
    return jsonify(
        {
            "task_id": task.id,
            "text": task.text,
            "due_date": task.due_date.isoformat() if task.due_date else "",
            "comment": task.comment if is_general else "",
            "completed": task.is_completed,
            "important": task.is_important,
            "calendar_url": url_for("tasks.general_detail", task_id=task.id)
            if is_general
            else url_for("calendar.edit_event", event_id=task.calendar_event_id),
            "has_comment": bool(task.comment.strip())
            if is_general
            else bool(task.calendar_event.comment.strip()),
        }
    )
