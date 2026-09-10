from app.extensions import db
from app.models import CalendarEvent, Reminder


def test_create_calendar_event(app, auth_client, sample_client):
    response = auth_client.post(
        "/calendar/events/new",
        data={
            "client_id": sample_client,
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
    assert "Иван Петров".encode() in response.data


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
    reminder_form = auth_client.get(f"/reminders/new?client_id={sample_client}")
    selected = f'<option value="{sample_client}" selected>'.encode()
    assert selected in event_form.data
    assert selected in reminder_form.data


def test_create_call_and_meeting_reminders(app, auth_client, sample_client):
    call = auth_client.post(
        "/reminders/new",
        data={
            "client_id": sample_client,
            "reminder_type": "call",
            "starts_at": "2026-07-28T12:00",
            "topic": "Обсудить документы",
            "status": "planned",
            "notify_before_minutes": 60,
        },
    )
    meeting = auth_client.post(
        "/reminders/new",
        data={
            "client_id": sample_client,
            "reminder_type": "meeting",
            "starts_at": "2026-07-29T15:00",
            "topic": "Онлайн-встреча",
            "status": "planned",
            "notify_before_minutes": 1440,
            "meeting_format": "online",
            "location_or_url": "https://example.com/meeting",
        },
    )
    assert call.status_code == 302
    assert meeting.status_code == 302
    with app.app_context():
        reminders = db.session.scalars(
            db.select(Reminder).order_by(Reminder.id)
        ).all()
        assert [item.reminder_type for item in reminders] == ["call", "meeting"]


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
