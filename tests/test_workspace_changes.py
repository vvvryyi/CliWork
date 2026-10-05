from app.extensions import db
from app.models import CalendarEvent, GeneralTask
from app.utils import utc_naive_to_local


def test_workspace_navigation_and_client_date_redirect(auth_client, sample_client):
    page = auth_client.get("/clients/").data.decode()
    assert "<header class=\"topbar\">" not in page
    labels = (
        "Дела", "Связаться сегодня", "Клиенты", "Календарь",
        "Сообщение", "Все дела", "Настройки", "Выйти",
    )
    nav = page.split('<nav class="main-nav workspace-tabs"', 1)[1].split("</nav>", 1)[0]
    positions = [nav.index(f">{label}<") for label in labels]
    assert positions == sorted(positions)
    assert "— Workspace" in page

    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "", "history_text": "Позвонить 301201"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/clients/contacts-today")


def test_general_task_date_creates_and_updates_single_calendar_event(app, auth_client):
    task_id = auth_client.post(
        "/tasks/save", data={"task_scope": "general", "text": "Общее дело"}
    ).get_json()["task_id"]
    detail_url = f"/tasks/all/{task_id}"
    detail = auth_client.get(detail_url).data.decode()
    assert 'name="due_date" type="date"' in detail

    response = auth_client.post(
        detail_url,
        data={"text": "Общее дело", "comment": "Пояснение", "due_date": "2030-12-01"},
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
        data={"client_id": sample_client, "starts_at": "2030-12-05T10:00"},
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
