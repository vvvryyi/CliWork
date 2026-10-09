from app.extensions import db
from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.models import CalendarEvent, DailyTask, GeneralTask, Interaction
from app.utils import local_to_utc_naive, utc_naive_to_local


def test_workspace_navigation_and_client_date_redirect(auth_client, sample_client):
    page = auth_client.get("/clients/").data.decode()
    assert "<header class=\"topbar\">" not in page
    nav = page.split('<nav class="main-nav workspace-tabs"', 1)[1].split("</nav>", 1)[0]
    assert ">Настройки</a>" in nav and ">Выйти</button>" in nav
    assert ">Дела</a>" not in nav and ">Клиенты</a>" not in nav
    assert '<details class="mobile-menu">' in page
    home = auth_client.get("/").data.decode()
    assert '<div class="stat-grid">' not in home
    assert '<h1>Workspace</h1>' not in home
    assert 'class="home-tab-count"' in home
    assert "— Workspace" in page
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "", "history_text": "Позвонить 301201"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == f"/clients/{sample_client}"


def test_general_task_date_creates_and_updates_single_calendar_event(app, auth_client):
    task_id = auth_client.post(
        "/tasks/save", data={"task_scope": "general", "text": "Общее дело"}
    ).get_json()["task_id"]
    detail_url = f"/tasks/all/{task_id}"
    detail = auth_client.get(detail_url).data.decode()
    assert 'name="due_date" type="text"' in detail
    assert 'placeholder="ГГ.ММ.ДД"' in detail

    response = auth_client.post(
        detail_url,
        data={"text": "Общее дело", "comment": "Пояснение", "due_date": "30.12.01"},
    )
    assert response.status_code == 302
    with app.app_context():
        task = db.session.get(GeneralTask, task_id)
        event_id = task.calendar_event_id
        assert task.due_date.isoformat() == "2030-12-01"
        assert event_id is not None
        assert task.calendar_event.origin == "general_task"
        assert task.calendar_event.comment == "Пояснение"

    auth_client.post(
        "/tasks/save",
        data={
            "task_scope": "general", "task_id": task_id, "text": "Общее дело с правкой",
            "due_date": "", "comment": "Устаревший комментарий",
        },
    )
    with app.app_context():
        task = db.session.get(GeneralTask, task_id)
        assert task.due_date.isoformat() == "2030-12-01"
        assert task.comment == "Пояснение"

    response = auth_client.post(
        detail_url,
        data={"text": "Общее дело", "comment": "Пояснение", "due_date": "2030-12-02"},
    )
    assert response.status_code == 302
    with app.app_context():
        task = db.session.get(GeneralTask, task_id)
        assert task.calendar_event_id == event_id
        assert utc_naive_to_local(task.calendar_event.starts_at).date().isoformat() == "2030-12-02"
        assert db.session.scalar(db.select(db.func.count(CalendarEvent.id))) == 1

    day = auth_client.get("/calendar/?view=day&date=2030-12-02")
    assert "Общее дело".encode() in day.data
    assert detail_url.encode() in day.data

    auth_client.post(
        detail_url, data={"text": "Общее дело", "comment": "Пояснение", "due_date": ""}
    )
    with app.app_context():
        task = db.session.get(GeneralTask, task_id)
        assert task is not None
        assert task.due_date is None
        assert task.calendar_event_id is None
        assert db.session.get(CalendarEvent, event_id) is None


def test_calendar_separates_task_and_contact_counts(auth_client, sample_client):
    auth_client.post(
        "/tasks/save",
        data={"task_scope": "daily", "text": "Личное", "due_date": "2030-12-05"},
    )
    auth_client.post(
        "/calendar/events/new",
        data={"client_id": sample_client, "starts_at": "30.12.05 10:00"},
    )
    month = auth_client.get("/calendar/?view=month&date=2030-12-01").data.decode()
    assert 'aria-label="Дела: 1"' in month
    assert 'aria-label="Связаться сегодня: 1"' in month
    assert "/calendar/?view=day&amp;date=2030-12-05&amp;tab=tasks" in month
    assert "/calendar/?view=day&amp;date=2030-12-05&amp;tab=contacts" in month

    tasks = auth_client.get("/calendar/?view=day&date=2030-12-05&tab=tasks").data.decode()
    contacts = auth_client.get("/calendar/?view=day&date=2030-12-05&tab=contacts").data.decode()
    assert "Личное" in tasks
    assert "Иван Петров" not in tasks
    assert "Иван Петров" in contacts
    assert "Личное" not in contacts


def test_calendar_event_has_back_button_before_calendar_link(auth_client):
    page = auth_client.get("/calendar/events/new").data.decode()
    heading = page.split('class="calendar-form-heading"', 1)[1].split("</div>", 1)[0]
    assert heading.index("data-history-back") < heading.index(">Календарь</a>")
    assert 'name="starts_at" type="text"' in page
    assert 'placeholder="ГГДДММ"' in page
    assert 'Начало <span class="required">' not in page
    assert 'name="ends_at"' not in page


def test_calendar_date_field_uses_year_day_month_and_keeps_existing_time(
    app, auth_client
):
    response = auth_client.post(
        "/calendar/events/new",
        data={"title": "Дело", "starts_at": "301202"},
    )
    assert response.status_code == 302
    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert utc_naive_to_local(event.starts_at).strftime("%Y-%m-%d %H:%M") == "2030-02-12 09:00"
        event_id = event.id
        event.starts_at = local_to_utc_naive("2030-02-12T14:30")
        db.session.commit()

    edit_page = auth_client.get(f"/calendar/events/{event_id}/edit").data.decode()
    assert 'value="301202"' in edit_page
    auth_client.post(
        f"/calendar/events/{event_id}/edit",
        data={"title": "Дело", "starts_at": "301302"},
    )
    with app.app_context():
        event = db.session.get(CalendarEvent, event_id)
        assert utc_naive_to_local(event.starts_at).strftime("%Y-%m-%d %H:%M") == "2030-02-13 14:30"


def test_deleting_scheduled_general_task_removes_only_its_event(app, auth_client):
    created = auth_client.post(
        "/tasks/save",
        data={
            "task_scope": "general", "text": "Временное дело",
            "comment": "Сохранить при отмене", "due_date": "2030-12-10",
        },
    ).get_json()
    task_id = created["task_id"]
    with app.app_context():
        event_id = db.session.get(GeneralTask, task_id).calendar_event_id

    auth_client.post(
        "/tasks/save", data={"task_scope": "general", "task_id": task_id, "delete": "1"}
    )
    with app.app_context():
        assert db.session.get(GeneralTask, task_id) is None
        assert db.session.get(CalendarEvent, event_id) is None

    restored = auth_client.post(
        "/tasks/save",
        data={
            "task_scope": "general", "text": "Временное дело",
            "comment": "Сохранить при отмене", "due_date": "2030-12-10",
        },
    ).get_json()
    with app.app_context():
        task = db.session.get(GeneralTask, restored["task_id"])
        assert task.comment == "Сохранить при отмене"
        assert task.due_date.isoformat() == "2030-12-10"
        assert task.calendar_event is not None


def test_calendar_client_comment_completes_selected_event_and_plans_next(
    app, auth_client, sample_client
):
    with app.app_context():
        event = CalendarEvent(
            client_id=sample_client,
            title="Позвонить",
            origin="manual",
            starts_at=local_to_utc_naive("2030-12-01T09:00"),
            status="planned",
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    calendar_page = auth_client.get("/calendar/?view=day&date=2030-12-01&tab=contacts").data.decode()
    assert f"/clients/{sample_client}?event_id={event_id}" in calendar_page
    detail = auth_client.get(f"/clients/{sample_client}?event_id={event_id}").data.decode()
    assert f'name="event_id" value="{event_id}"' in detail

    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={
            "history_ids": "",
            "history_text": "Обсудили условия 301202",
            "event_id": event_id,
        },
    )
    assert response.headers["Location"] == f"/clients/{sample_client}"
    with app.app_context():
        completed = db.session.get(CalendarEvent, event_id)
        assert completed.status == "completed"
        assert completed.completed_by_interaction_id is not None
        new_event = db.session.scalar(
            db.select(CalendarEvent).where(CalendarEvent.id != event_id)
        )
        assert utc_naive_to_local(new_event.starts_at).date().isoformat() == "2030-12-02"
        assert db.session.scalar(db.select(db.func.count(Interaction.id))) == 1
    old_day = auth_client.get("/calendar/?view=day&date=2030-12-01&tab=contacts")
    assert "Иван Петров".encode() not in old_day.data


def test_daily_task_comment_date_moves_task_and_returns_to_tasks(app, auth_client):
    created = auth_client.post(
        "/tasks/save",
        data={"task_scope": "daily", "text": "Позвонить", "due_date": "2030-12-01"},
    ).get_json()
    with app.app_context():
        event_id = db.session.get(DailyTask, created["task_id"]).calendar_event_id
    response = auth_client.post(
        f"/calendar/events/{event_id}/edit",
        data={
            "title": "Позвонить",
            "event_type": "task",
            "starts_at": "2030-12-01T09:00",
            "comment": "Перенести звонок 301202",
        },
    )
    assert response.headers["Location"] == "/tasks/?date=2030-12-02"
    with app.app_context():
        task = db.session.get(DailyTask, created["task_id"])
        assert task.due_date.isoformat() == "2030-12-02"
        assert task.calendar_event.comment == "Перенести звонок 301202"


def test_cyrillic_xlsx_can_be_uploaded_and_deleted(app, auth_client, sample_client):
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={
            "history_ids": "",
            "history_text": "Документы получены",
            "files": (BytesIO(b"spreadsheet"), "договор.xlsx"),
        },
        content_type="multipart/form-data",
    )
    assert response.headers["Location"] == f"/clients/{sample_client}"
    with app.app_context():
        attachment = db.session.scalar(db.select(Interaction)).attachments[0]
        attachment_id = attachment.id
        path = Path(attachment.file_path)
        assert path.exists()
    page = auth_client.get(f"/clients/{sample_client}").data.decode()
    assert f'id="delete-attachment-{attachment_id}"' in page
    assert "договор.xlsx" in page
    deletion = auth_client.post(f"/clients/attachments/{attachment_id}/delete")
    assert deletion.headers["Location"] == f"/clients/{sample_client}"
    assert not path.exists()


def test_contacts_date_navigation_and_same_day_is_not_red(
    app, auth_client, sample_client, monkeypatch
):
    import app.main as main_module
    import app.clients as clients_module

    fixed_now = datetime(2026, 9, 24, 9)
    monkeypatch.setattr(main_module, "utcnow", lambda: fixed_now)
    monkeypatch.setattr(clients_module, "utcnow", lambda: fixed_now)
    with app.app_context():
        db.session.add(CalendarEvent(
            client_id=sample_client,
            title="Связаться",
            starts_at=local_to_utc_naive("2026-09-24T09:00"),
            status="overdue",
        ))
        db.session.commit()
    dashboard = auth_client.get("/").data.decode()
    assert 'class="stat-card stat-card-alert"' not in dashboard
    today_page = auth_client.get("/clients/contacts-today?date=2026-09-24").data.decode()
    assert "Иван Петров" in today_page
    assert 'href="/clients/contacts-today?date=2026-09-23"' in today_page
    assert 'href="/clients/contacts-today?date=2026-09-25"' in today_page
    tomorrow_page = auth_client.get("/clients/contacts-today?date=2026-09-25").data.decode()
    assert "Иван Петров" not in tomorrow_page
