from datetime import date
import re

import pytest

from app.extensions import db
from app.models import CalendarEvent, DailyTask, GeneralTask


@pytest.mark.parametrize("scope,model", [("daily", DailyTask), ("general", GeneralTask)])
def test_calendar_keeps_completed_tasks_on_original_day(app, auth_client, scope, model):
    due_date = "2026-10-20"
    tasks = []
    for text in ("Альфа — завершено", "Ясень — выполнить"):
        response = auth_client.post(
            "/tasks/save", data={"task_scope": scope, "text": text, "due_date": due_date}
        )
        assert response.status_code == 200
        tasks.append(response.get_json())

    finished, pending = tasks
    payload = {
        "task_scope": scope, "task_id": finished["task_id"],
        "text": finished["text"], "due_date": due_date, "completed": "1",
    }
    assert auth_client.post("/tasks/save", data=payload).get_json()["completed"] is True

    # Repeated visits must retain the checked row below unfinished work.
    url = f"/calendar/?view=day&date={due_date}"
    for _ in range(2):
        page = auth_client.get(url).data.decode()
        assert page.index(pending["text"]) < page.index(finished["text"])
        assert 'data-hide-completed="0"' in page
        row = re.search(
            rf'<div class="task-line is-completed"[^>]*data-task-id="{finished["task_id"]}"[^>]*>(.*?)</div>',
            page, re.S,
        ).group(1)
        assert re.search(r'data-task-check[^>]*checked', row)

    with app.app_context():
        task = db.session.get(model, finished["task_id"])
        event_id = task.calendar_event_id
        completed_at = task.completed_at
        assert task.due_date == date(2026, 10, 20)
        assert task.calendar_event.status == "completed"
        assert task.calendar_event.completed_at == completed_at

    overdue = auth_client.get("/calendar/?view=overdue").data.decode()
    assert finished["text"] not in overdue
    assert pending["text"] in overdue
    assert 'data-hide-completed="1"' in overdue

    # History remains reachable in every calendar period.
    week = auth_client.get(f"/calendar/?view=week&date={due_date}").data.decode()
    assert finished["text"] in week
    for view in ("month", "year"):
        page = auth_client.get(f"/calendar/?view={view}&date={due_date}").data.decode()
        if view == "month":
            assert 'aria-label="Дела: 2"' in page
        else:
            assert re.search(
                rf'class="mini-day [^"]*has-events[^"]*"\s+href="{re.escape(url.replace("&", "&amp;"))}"',
                page,
            )
        assert url.replace("&", "&amp;") in page
    assert finished["text"] not in auth_client.get(
        "/calendar/?view=day&date=2026-10-21"
    ).data.decode()

    # The same row can be reopened without losing its calendar link or date.
    payload["completed"] = "0"
    assert auth_client.post("/tasks/save", data=payload).get_json()["completed"] is False
    page = auth_client.get(url).data.decode()
    assert page.index(finished["text"]) < page.index(pending["text"])
    with app.app_context():
        task = db.session.get(model, finished["task_id"])
        assert task.completed_at is None
        assert task.calendar_event_id == event_id
        assert db.session.get(CalendarEvent, event_id).status == "overdue"


def test_contacts_page_uses_contacts_heading(auth_client):
    page = auth_client.get("/clients/").data.decode()
    assert "<h1>Контакты</h1>" in page
    assert "<title>Контакты — WorkSpace</title>" in page
    archive = auth_client.get("/clients/?archived=1").data.decode()
    assert "<h1>Архив контактов</h1>" in archive
