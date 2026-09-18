from datetime import date, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import or_

from .extensions import db
from .models import DailyTask, utcnow
from .task_service import create_daily_task, delete_task_and_event, sync_event_from_task
from .utils import utc_naive_to_local


bp = Blueprint("tasks", __name__, url_prefix="/tasks")


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
        .where(
            or_(
                DailyTask.completed_at.is_(None) & (DailyTask.due_date <= selected_date),
                DailyTask.completed_at.is_not(None) & (DailyTask.due_date == selected_date),
            )
        )
        .order_by(DailyTask.completed_at.is_not(None), DailyTask.due_date, DailyTask.id)
    ).all()
    return render_template(
        "tasks/index.html",
        tasks=tasks,
        selected_date=selected_date,
        previous_date=selected_date - timedelta(days=1),
        next_date=selected_date + timedelta(days=1),
        today=utc_naive_to_local(utcnow()).date(),
    )


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
    should_delete = request.form.get("delete") == "1"
    completed = request.form.get("completed") == "1"

    task = db.get_or_404(DailyTask, task_id) if task_id else None
    if should_delete or (task is not None and not text):
        if task is not None:
            delete_task_and_event(task)
        db.session.commit()
        return jsonify({"deleted": True, "task_id": task_id})
    if not text:
        return jsonify({"error": "Введите текст дела."}), 400

    if task is None:
        task = create_daily_task(text, due_date, completed=completed)
    else:
        task.text = text
        task.completed_at = utcnow() if completed else None
        sync_event_from_task(task)
    db.session.commit()
    return jsonify(
        {
            "task_id": task.id,
            "text": task.text,
            "due_date": task.due_date.isoformat(),
            "completed": task.is_completed,
        }
    )
