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
