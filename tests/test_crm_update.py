from datetime import date, datetime, timezone

from icalendar import Event

from app.calendar_sync import sync_icloud_calendar
from app.extensions import db
from app.models import CalendarEvent, Client, DailyTask, Interaction
from app.utils import add_months, local_to_utc_naive, utc_naive_to_local


def test_client_and_note_redirects(app, auth_client, sample_client):
    client_save = auth_client.post(
        f"/clients/{sample_client}/edit",
        data={"full_name": "Иван Петров"},
    )
    note_save = auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Позвонили"},
    )
    assert client_save.headers["Location"].endswith("/")
    assert note_save.headers["Location"].endswith("/clients/")


def test_opening_card_adds_a_fresh_dated_row_below_history(app, auth_client, sample_client, monkeypatch):
    import app.clients as clients_module

    fixed_now = datetime(2026, 9, 18, 9)
    monkeypatch.setattr(clients_module, "utcnow", lambda: fixed_now)
    with app.app_context():
        db.session.add(Interaction(client_id=sample_client, text="250101 Старый текст 261201"))
        db.session.commit()

    page = auth_client.get(f"/clients/{sample_client}")
    assert "Старый текст 261201".encode() in page.data
    assert b">260918 </textarea>" in page.data
    assert page.data.index("Старый текст 261201".encode()) < page.data.index(b">260918 </textarea>")
    with app.app_context():
        assert db.session.get(Interaction, 1).text.startswith("250101")

    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={
            "text": "260918 Новая запись 261201",
            "workflow_fields_present": "1",
        },
    )
    with app.app_context():
        assert db.session.get(Interaction, 1).text.startswith("250101")
        assert db.session.get(Interaction, 2).text.startswith("260918")


def test_client_flags_and_compact_upload_are_saved(app, auth_client, sample_client):
    response = auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={
            "text": "",
            "workflow_fields_present": "1",
            "flag_f": "on",
            "flag_ks": "on",
            "flag_kr": "on",
            "percent_value": "35",
        },
    )
    assert response.headers["Location"].endswith("/clients/")
    with app.app_context():
        client = db.session.get(Client, sample_client)
        assert client.flag_f is True
        assert client.flag_ks is True
        assert client.flag_kr is True
        assert client.flag_d is False
        assert client.percent_value == 35

    detail = auth_client.get(f"/clients/{sample_client}")
    assert b"data-file-input" in detail.data
    assert "Файл не выбран".encode() not in detail.data
    assert "До 20 МБ".encode() in detail.data


def test_quarterly_reminders_fill_calendar_for_active_client(app, auth_client, sample_client, monkeypatch):
    import app.utils as utils_module

    monkeypatch.setattr(utils_module, "utcnow", lambda: datetime(2026, 9, 18, 9))
    auth_client.post(f"/clients/{sample_client}/group", data={"group": "a"})
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={
            "text": "",
            "workflow_fields_present": "1",
            "quarterly_reminder_mmdd": "0918",
        },
    )
    with app.app_context():
        events = db.session.scalars(
            db.select(CalendarEvent)
            .where(CalendarEvent.origin == "quarterly")
            .order_by(CalendarEvent.starts_at)
        ).all()
        dates = [utc_naive_to_local(item.starts_at).strftime("%y%m%d") for item in events]
        assert dates[:4] == ["260918", "261218", "270318", "270618"]
        assert dates[-1] <= "311231"


def test_quarterly_dates_keep_original_day_after_short_month():
    assert add_months(date(2027, 11, 30), 3, 30) == date(2028, 2, 29)
    assert add_months(date(2028, 2, 29), 3, 30) == date(2028, 5, 30)


def test_rescheduling_removes_client_from_dashboard_overdue_list(app, auth_client, sample_client):
    with app.app_context():
        interaction = Interaction(client_id=sample_client, text="250101 Позвонить 250101")
        db.session.add(interaction)
        db.session.flush()
        db.session.add(
            CalendarEvent(
                client_id=sample_client,
                source_interaction_id=interaction.id,
                origin="interaction",
                event_type="task",
                starts_at=local_to_utc_naive("2025-01-01T09:00"),
                status="overdue",
            )
        )
        db.session.commit()

    before = auth_client.get("/")
    assert b"overdue-client-panel" in before.data
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Новая запись и дата 311231", "workflow_fields_present": "1"},
    )
    after = auth_client.get("/")
    assert b"overdue-client-panel" not in after.data


def test_every_day_has_its_own_tasks(app, auth_client):
    auth_client.post("/tasks/new", data={"text": "Позвонить", "due_date": "2026-09-17"})
    assert "Позвонить".encode() not in auth_client.get("/tasks/?date=2026-09-18").data
    assert "Позвонить".encode() in auth_client.get("/tasks/?date=2026-09-17").data

    auth_client.post("/tasks/1/toggle", data={"date": "2026-09-17"})
    assert "Позвонить".encode() in auth_client.get("/tasks/?date=2026-09-17").data


def test_task_sheet_autosaves_and_stays_linked_to_calendar(app, auth_client):
    created = auth_client.post(
        "/tasks/save",
        data={"text": "Подготовить документы", "due_date": "2026-09-20"},
    )
    assert created.status_code == 200
    task_id = created.get_json()["task_id"]

    with app.app_context():
        task = db.session.get(DailyTask, task_id)
        event_id = task.calendar_event_id
        assert task.calendar_event.title == "Подготовить документы"
        assert utc_naive_to_local(task.calendar_event.starts_at).date() == date(2026, 9, 20)

    updated = auth_client.post(
        "/tasks/save",
        data={
            "task_id": task_id,
            "text": "Документы готовы",
            "due_date": "2026-09-20",
            "completed": "1",
        },
    )
    assert updated.get_json()["completed"] is True
    with app.app_context():
        event = db.session.get(CalendarEvent, event_id)
        assert event.title == "Документы готовы"
        assert event.status == "completed"

    auth_client.post("/tasks/save", data={"task_id": task_id, "delete": "1"})
    with app.app_context():
        assert db.session.get(DailyTask, task_id) is None
        assert db.session.get(CalendarEvent, event_id) is None


def test_calendar_deal_creates_daily_task(app, auth_client):
    response = auth_client.post(
        "/calendar/events/new",
        data={
            "title": "Встреча по договору",
            "event_type": "meeting",
            "starts_at": "2026-09-22T14:30",
            "ends_at": "",
            "comment": "",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        task = db.session.scalar(
            db.select(DailyTask).where(DailyTask.text == "Встреча по договору")
        )
        assert task is not None
        assert task.due_date == date(2026, 9, 22)
        assert task.calendar_event.origin == "manual"


def test_client_and_iphone_calendar_events_do_not_create_daily_tasks(
    app, auth_client, sample_client
):
    auth_client.post(
        "/calendar/events/new",
        data={
            "client_id": sample_client,
            "title": "Контакт с клиентом",
            "event_type": "meeting",
            "starts_at": "2026-09-22T14:30",
        },
    )
    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert event.client_id == sample_client
        assert event.daily_task is None


def test_task_page_and_dashboard_use_new_compact_wording(auth_client):
    tasks_page = auth_client.get("/tasks/?date=2026-09-18")
    assert b"data-task-editor" in tasks_page.data
    assert "⌘/Ctrl + Z".encode() in tasks_page.data

    dashboard = auth_client.get("/")
    assert "Активные клиенты".encode() in dashboard.data
    assert "Просроченные клиенты".encode() in dashboard.data
    assert dashboard.data.index("Дела".encode()) < dashboard.data.index("Новый клиент".encode())

    calendar_form = auth_client.get("/calendar/events/new?date=2026-09-18")
    assert b"calendar-form-grid" in calendar_form.data
    assert "Новое дело".encode() in calendar_form.data
    assert "Название дела".encode() in calendar_form.data


class FakeRemoteEvent:
    def __init__(self, uid, summary, starts_at):
        component = Event()
        component.add("uid", uid)
        component.add("summary", summary)
        component.add("dtstart", starts_at)
        self.component = component
        self.etag = '"remote-etag"'
        self.url = f"https://icloud.test/{uid}.ics"
        self.data = None

    def save(self):
        return self

    def delete(self):
        return None


class FakeCalendar:
    def __init__(self, events):
        self.events = events
        self.added = []

    def get_events(self):
        return self.events

    def add_event(self, ical):
        remote = FakeRemoteEvent("pushed", "pushed", datetime.now(timezone.utc))
        remote.data = ical
        self.added.append(remote)
        return remote


class FakeCalendarResult:
    def __init__(self, calendar):
        self.calendar = calendar

    def __enter__(self):
        return self.calendar

    def __exit__(self, *_):
        return False


def test_icloud_sync_pulls_and_pushes_events(app, monkeypatch):
    remote = FakeRemoteEvent(
        "iphone-meeting",
        "Встреча из iPhone",
        datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
    )
    fake_calendar = FakeCalendar([remote])
    app.config.update(
        ICLOUD_USERNAME="user@example.com",
        ICLOUD_APP_PASSWORD="app-password",
        ICLOUD_CALENDAR_NAME="CRM",
    )

    import caldav

    monkeypatch.setattr(
        caldav,
        "get_calendar",
        lambda **kwargs: FakeCalendarResult(fake_calendar),
    )
    with app.app_context():
        db.session.add(
            CalendarEvent(
                title="Встреча из CRM",
                origin="manual",
                event_type="meeting",
                starts_at=datetime(2026, 10, 2, 10),
                status="planned",
            )
        )
        db.session.commit()
        result = sync_icloud_calendar()
        imported = db.session.scalar(
            db.select(CalendarEvent).where(CalendarEvent.external_uid == "iphone-meeting")
        )
        assert imported.title == "Встреча из iPhone"
        assert imported.daily_task is None
        assert result["pulled"] == 1
        assert result["pushed"] == 1
        assert len(fake_calendar.added) == 1
