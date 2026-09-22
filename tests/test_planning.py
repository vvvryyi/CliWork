from app.extensions import db
from datetime import datetime

from app.models import CalendarEvent
from app.utils import (
    local_to_utc_naive,
    normalize_interaction_text,
    parse_planning_details,
    parse_planning_suffix,
)


def test_create_calendar_event(app, auth_client, sample_client):
    response = auth_client.post(
        "/calendar/events/new",
        data={
            "client_id": sample_client,
            "title": "",
            "event_type": "meeting",
            "starts_at": "2026-07-28T10:00",
            "ends_at": "2026-07-28T11:00",
            "status": "planned",
            "comment": "Первая встреча",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert event.comment == "Первая встреча"

    response = auth_client.get("/calendar/?view=month&date=2026-07-01")
    assert response.status_code == 200
    assert '<span class="calendar-count">1</span>'.encode() in response.data
    assert "/calendar/?view=day&amp;date=2026-07-28".encode() in response.data


def test_calendar_year_view_and_planning_limit(app, auth_client, sample_client):
    response = auth_client.get("/calendar/?view=year&date=2031-01-01")
    assert response.status_code == 200
    assert "2031 год".encode() in response.data
    assert "Январь".encode() in response.data
    assert "Декабрь".encode() in response.data

    response = auth_client.post(
        "/calendar/events/new",
        data={
            "client_id": sample_client,
            "event_type": "meeting",
            "starts_at": "2032-01-01T10:00",
            "status": "planned",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "не позднее 31.12.2031".encode() in response.data
    with app.app_context():
        assert db.session.scalar(db.select(CalendarEvent)) is None


def test_quick_planning_forms_preselect_client(auth_client, sample_client):
    event_form = auth_client.get(f"/calendar/events/new?client_id={sample_client}")
    selected = f'<option value="{sample_client}" selected>'.encode()
    assert selected in event_form.data


def test_create_personal_event_without_client(app, auth_client):
    response = auth_client.post(
        "/calendar/events/new",
        data={
            "client_id": "",
            "title": "Личное дело",
            "event_type": "task",
            "starts_at": "2026-07-28T12:00",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert event.client_id is None
        assert event.title == "Личное дело"


def test_personal_event_requires_title(app, auth_client):
    response = auth_client.post(
        "/calendar/events/new",
        data={"client_id": "", "title": "", "starts_at": "2026-07-28T12:00"},
        follow_redirects=True,
    )
    assert "Для личного дела укажите название".encode() in response.data
    with app.app_context():
        assert db.session.scalar(db.select(CalendarEvent)) is None


def test_planning_suffix_uses_yymmdd_and_default_time():
    planned, found = parse_planning_suffix("Позвонить повторно 260911")
    assert found is True
    assert planned == datetime(2026, 9, 11, 9, 0)

    planned, found = parse_planning_suffix("Позвонить повторно 260911 15:30")
    assert found is True
    assert planned == datetime(2026, 9, 11, 15, 30)


def test_planning_suffix_rejects_invalid_or_non_trailing_dates():
    assert parse_planning_suffix("Дата 260911 не в конце") == (None, False)
    assert parse_planning_suffix("Некорректная дата 261332") == (None, True)
    assert parse_planning_suffix("Старый формат 26.09.11") == (None, False)


def test_planning_suffix_marks_important_events():
    planned, found, important = parse_planning_details("Срочный звонок 311231!")
    assert found is True
    assert important is True
    assert planned == datetime(2031, 12, 31, 9, 0)

    planned, found, important = parse_planning_details(
        "Срочная встреча 311231 15:30!"
    )
    assert found is True
    assert important is True
    assert planned == datetime(2031, 12, 31, 15, 30)


def test_interaction_text_always_uses_current_date(app):
    fixed_now = datetime(2026, 9, 16, 9)
    with app.app_context():
        assert (
            normalize_interaction_text("Обсудили документы", fixed_now)
            == "260916 Обсудили документы"
        )
        assert (
            normalize_interaction_text("Обсудили следующий шаг 260920", fixed_now)
            == "260916 Обсудили следующий шаг 260920"
        )
        assert (
            normalize_interaction_text(
                "260916 Обсудили следующий шаг 260920", fixed_now
            )
            == "260916 Обсудили следующий шаг 260920"
        )


def test_calendar_marks_important_event_red_only_on_its_day(app, auth_client, sample_client, monkeypatch):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Важная задача 311231!"},
    )
    response = auth_client.get("/calendar/?view=month&date=2031-12-01")
    assert response.status_code == 200
    assert "has-important".encode() not in response.data
    future_day = auth_client.get("/calendar/?view=day&date=2031-12-31")
    assert b"agenda-item event-important" not in future_day.data
    future_week = auth_client.get("/calendar/?view=week&date=2031-12-31")
    assert b"event-bg-task event-important" not in future_week.data
    future_year = auth_client.get("/calendar/?view=year&date=2031-01-01")
    assert "has-important".encode() not in future_year.data

    import app.calendar_routes as calendar_module
    monkeypatch.setattr(calendar_module, "utcnow", lambda: datetime(2031, 12, 31, 8))
    response = auth_client.get("/calendar/?view=month&date=2031-12-01")
    assert "has-important".encode() in response.data

    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert event.is_important is True


def test_past_planned_event_becomes_overdue(app, auth_client, sample_client):
    with app.app_context():
        db.session.add(
            CalendarEvent(
                client_id=sample_client,
                starts_at=local_to_utc_naive("2020-01-01T09:00"),
                status="planned",
            )
        )
        db.session.commit()

    response = auth_client.get("/calendar/?view=overdue")
    assert response.status_code == 200
    assert "Просрочено".encode() in response.data
    with app.app_context():
        assert db.session.scalar(db.select(CalendarEvent)).status == "overdue"


def test_dashboard_shows_only_todays_daily_tasks(app, auth_client, sample_client, monkeypatch):
    import app.main as main_module

    fixed_now = datetime(2026, 9, 9, 12, 0)
    monkeypatch.setattr(main_module, "utcnow", lambda: fixed_now)
    with app.app_context():
        from app.models import DailyTask
        db.session.add_all(
            [
                DailyTask(text="Сегодня", due_date=datetime(2026, 9, 9).date()),
                DailyTask(text="Вчера", due_date=datetime(2026, 9, 8).date()),
                CalendarEvent(
                    client_id=sample_client,
                    starts_at=local_to_utc_naive("2026-09-09T18:00"),
                    title="Клиентское событие",
                    status="planned",
                ),
            ]
        )
        db.session.commit()

    response = auth_client.get("/")
    assert "Сегодня".encode() in response.data
    assert "Вчера".encode() not in response.data
    assert "Клиентское событие".encode() not in response.data
    assert "Дела на сегодня".encode() in response.data


def test_prepare_and_confirm_message(app, auth_client, sample_client):
    response = auth_client.post(
        "/messages/compose",
        data={
            "client_id": sample_client,
            "channel": "telegram",
            "message": "Здравствуйте!",
        },
    )
    assert response.status_code == 200
    assert "Сообщение сохранено".encode() in response.data

    from app.models import Interaction

    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        interaction_id = interaction.id
        assert interaction.delivery_status == "prepared"

    response = auth_client.post(f"/messages/{interaction_id}/mark-sent")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Interaction, interaction_id).delivery_status == "sent"
