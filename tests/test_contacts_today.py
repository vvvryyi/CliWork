from datetime import datetime

import pytest

from app.extensions import db
from app.models import CalendarEvent, Client
from app.utils import local_to_utc_naive


def test_contact_card_opens_only_due_active_clients(app, auth_client, sample_client, monkeypatch):
    import app.clients as clients_module
    import app.main as main_module

    fixed_now = datetime(2026, 9, 24, 9)
    monkeypatch.setattr(clients_module, "utcnow", lambda: fixed_now)
    monkeypatch.setattr(main_module, "utcnow", lambda: fixed_now)

    with app.app_context():
        overdue = Client(full_name="Просроченный клиент")
        future = Client(full_name="Будущий клиент")
        completed = Client(full_name="Завершённый клиент")
        archived = Client(full_name="Архивный клиент", archived_at=fixed_now)
        db.session.add_all([overdue, future, completed, archived])
        db.session.flush()
        overdue_id = overdue.id
        db.session.add_all(
            [
                CalendarEvent(
                    client_id=sample_client,
                    title="Звонок сегодня",
                    starts_at=local_to_utc_naive("2026-09-24T10:00"),
                    status="planned",
                ),
                CalendarEvent(
                    client_id=sample_client,
                    title="Повторный звонок",
                    starts_at=local_to_utc_naive("2026-09-24T11:00"),
                    status="planned",
                ),
                CalendarEvent(
                    client_id=overdue_id,
                    title="Позвонить вчера",
                    starts_at=local_to_utc_naive("2026-09-23T09:00"),
                    status="overdue",
                ),
                CalendarEvent(
                    client_id=future.id,
                    starts_at=local_to_utc_naive("2026-09-25T09:00"),
                    status="planned",
                ),
                CalendarEvent(
                    client_id=completed.id,
                    starts_at=local_to_utc_naive("2026-09-24T09:00"),
                    status="completed",
                ),
                CalendarEvent(
                    client_id=archived.id,
                    starts_at=local_to_utc_naive("2026-09-24T09:00"),
                    status="planned",
                ),
            ]
        )
        db.session.commit()

    dashboard = auth_client.get("/").data.decode()
    assert 'href="/clients/contacts-today"' in dashboard
    assert '<span class="home-tab-count">2</span><span>Связаться сегодня</span>' in dashboard

    response = auth_client.get("/clients/contacts-today")
    assert response.status_code == 200
    page = response.data.decode()
    assert f'href="/clients/{sample_client}?event_id=' in page
    assert f'href="/clients/{overdue_id}?event_id=' in page
    assert page.count(">Иван Петров</a>") == 1
    assert "Просроченный клиент" in page
    assert "23.09.2026 · Просрочено" in page
    assert "Будущий клиент" not in page
    assert "Завершённый клиент" not in page
    assert "Архивный клиент" not in page


def test_contacts_today_shows_empty_message(auth_client):
    page = auth_client.get("/clients/contacts-today")
    assert page.status_code == 200
    assert "На сегодня нет клиентов, с которыми нужно связаться.".encode() in page.data


def test_contact_importance_is_saved_and_shared_with_calendar(app, auth_client, sample_client):
    with app.app_context():
        event = CalendarEvent(
            client_id=sample_client,
            title="Позвонить",
            starts_at=local_to_utc_naive("2026-09-24T10:00"),
            status="planned",
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    url = f"/clients/contacts-today/events/{event_id}/importance"
    for important in (True, False):
        response = auth_client.post(url, data={"important": str(int(important))})
        assert response.status_code == 200
        assert response.get_json() == {"important": important}
        with app.app_context():
            event = db.session.get(CalendarEvent, event_id)
            assert event.is_important is important
            assert event.client_id == sample_client
            assert event.title == "Позвонить"
        page = auth_client.get("/clients/contacts-today?date=2026-09-24").data.decode()
        assert f'action="{url}"' in page
        assert ('contact-agenda-item event-important' in page) is important
        calendar = auth_client.get("/calendar/?view=day&date=2026-09-24&tab=contacts").data.decode()
        assert ('agenda-item event-important' in calendar) is important

    assert auth_client.post(url, data={"important": "invalid"}).status_code == 400
    assert auth_client.post(url, data={}).status_code == 400
    with app.app_context():
        assert db.session.get(CalendarEvent, event_id).is_important is False


@pytest.mark.parametrize("archived", [False, True])
def test_contact_importance_rejects_personal_and_archived_events(app, auth_client, sample_client, archived):
    with app.app_context():
        if archived:
            db.session.get(Client, sample_client).archived_at = datetime(2026, 9, 24)
        event = CalendarEvent(
            client_id=sample_client if archived else None,
            starts_at=local_to_utc_naive("2026-09-24T10:00"),
            status="planned",
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id
    response = auth_client.post(
        f"/clients/contacts-today/events/{event_id}/importance", data={"important": "1"}
    )
    assert response.status_code == 404
    with app.app_context():
        assert db.session.get(CalendarEvent, event_id).is_important is False
