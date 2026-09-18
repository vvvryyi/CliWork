from datetime import datetime, time

from .extensions import db
from .models import CalendarEvent, DailyTask, utcnow
from .utils import local_to_utc_naive, utc_naive_to_local


TASK_EVENT_ORIGINS = {"daily_task", "manual", "icloud"}


def _event_title(event):
    if event.title:
        return event.title.strip()[:500]
    if event.client:
        return event.client.full_name[:500]
    return "Дело"


def _event_status(starts_at, completed_at=None):
    if completed_at:
        return "completed"
    return "overdue" if starts_at < utcnow() else "planned"


def create_daily_task(text, due_date, completed=False):
    task = DailyTask(
        text=text.strip()[:500],
        due_date=due_date,
        completed_at=utcnow() if completed else None,
    )
    db.session.add(task)
    db.session.flush()
    sync_event_from_task(task)
    return task


def sync_event_from_task(task):
    event = task.calendar_event
    if event is None:
        event = CalendarEvent(
            origin="daily_task",
            event_type="task",
            starts_at=local_to_utc_naive(
                datetime.combine(task.due_date, time(hour=9)).isoformat(
                    timespec="minutes"
                )
            ),
            comment="",
            status="planned",
        )
        db.session.add(event)
        db.session.flush()
        task.calendar_event = event
    else:
        local_start = utc_naive_to_local(event.starts_at)
        event.starts_at = local_to_utc_naive(
            datetime.combine(task.due_date, local_start.time()).isoformat(
                timespec="minutes"
            )
        )

    event.title = task.text[:250]
    event.completed_at = task.completed_at
    event.status = _event_status(event.starts_at, task.completed_at)
    return event


def sync_task_from_event(event):
    if event.origin not in TASK_EVENT_ORIGINS or not event.starts_at:
        return None

    text = _event_title(event)
    due_date = utc_naive_to_local(event.starts_at).date()
    completed_at = (
        (event.completed_at or utcnow())
        if event.status in {"completed", "cancelled"}
        else None
    )
    task = event.daily_task
    if task is None:
        task = DailyTask(
            calendar_event=event,
            text=text,
            due_date=due_date,
            completed_at=completed_at,
        )
        db.session.add(task)
    else:
        task.text = text
        task.due_date = due_date
        task.completed_at = completed_at
    return task


def delete_task_and_event(task):
    event = task.calendar_event
    task.calendar_event = None
    db.session.delete(task)
    if event is None:
        return
    if event.external_uid:
        event.status = "cancelled"
        event.completed_at = utcnow()
    else:
        db.session.delete(event)


def delete_event_and_task(event):
    task = event.daily_task
    if task is not None:
        task.calendar_event = None
        db.session.delete(task)
    if event.external_uid:
        event.status = "cancelled"
        event.completed_at = utcnow()
    else:
        db.session.delete(event)
