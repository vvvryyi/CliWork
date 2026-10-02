from datetime import datetime

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
    assert '<span class="stat-value">2</span>' in dashboard

    response = auth_client.get("/clients/contacts-today")
    assert response.status_code == 200
    page = response.data.decode()
    assert f'href="/clients/{sample_client}"' in page
    assert f'href="/clients/{overdue_id}"' in page
    assert page.count("Иван Петров") == 1
    assert "Просроченный клиент" in page
    assert "23.09.2026 · Просрочено" in page
    assert "Будущий клиент" not in page
    assert "Завершённый клиент" not in page
    assert "Архивный клиент" not in page


def test_contacts_today_shows_empty_message(auth_client):
    page = auth_client.get("/clients/contacts-today")
    assert page.status_code == 200
    assert "На сегодня нет клиентов, с которыми нужно связаться.".encode() in page.data
