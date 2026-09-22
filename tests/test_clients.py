import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import CalendarEvent, Client, Interaction
from app.utils import utc_naive_to_local


def test_create_client_form_replaces_notes_with_interaction_field(
    auth_client, monkeypatch
):
    import app.clients as clients_module

    monkeypatch.setattr(clients_module, "utcnow", lambda: datetime(2026, 9, 16, 9))
    response = auth_client.get("/clients/new")

    assert response.status_code == 200
    assert "Общий комментарий".encode() not in response.data
    assert b'name="notes"' not in response.data
    assert "Запись о работе с клиентом".encode() in response.data
    assert b'name="interaction_text"' in response.data
    assert "ГГММДД".encode() in response.data
    assert b"data-dated-interaction" in response.data
    assert (
        'data-current-date="260916">260916 </textarea>'.encode()
        in response.data
    )


def test_create_client_with_interaction_and_next_action(app, auth_client):
    response = auth_client.post(
        "/clients/new",
        data={
            "full_name": "Анна Смирнова",
            "interaction_text": "Провели первую консультацию 260920 14:30!",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "дело добавлено на 20.09.2026 14:30".encode() in response.data
    assert response.request.path == "/"
    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        event = db.session.scalar(db.select(CalendarEvent))
        assert interaction.client.full_name == "Анна Смирнова"
        assert interaction.text.endswith("Провели первую консультацию 260920 14:30!")
        assert re.match(r"\d{6} ", interaction.text)
        assert event.source_interaction_id == interaction.id
        assert event.is_important is True
        assert utc_naive_to_local(event.starts_at).strftime("%y%m%d %H:%M") == "260920 14:30"


def test_client_card_shows_history_and_opens_a_new_note_below_it(
    app, auth_client, sample_client
):
    original_text = "Строка один\nСтрока два 260920"
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": original_text},
    )

    detail = auth_client.get(f"/clients/{sample_client}")
    assert b'class="timeline client-history"' in detail.data
    assert f'<textarea name="text" rows="5"'.encode() in detail.data
    assert original_text.encode() in detail.data
    assert f'action="/clients/{sample_client}/interactions"'.encode() in detail.data
    assert f'action="/clients/{sample_client}/interactions/1/delete"'.encode() in detail.data
    assert detail.data.index(original_text.encode()) < detail.data.index(b'<textarea name="text"')

    updated_text = "Новая запись\nСледующий шаг 260921 11:00"
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": updated_text},
    )
    with app.app_context():
        interactions = db.session.scalars(
            db.select(Interaction).order_by(Interaction.id)
        ).all()
        assert len(interactions) == 2
        assert interactions[0].text.endswith(original_text)
        assert interactions[1].text.endswith(updated_text)


def test_create_search_edit_and_archive_client(app, auth_client, sample_client):
    response = auth_client.get("/clients/?q=Иван")
    assert response.status_code == 200
    assert "Иван Петров".encode() in response.data

    response = auth_client.post(
        f"/clients/{sample_client}/edit",
        data={
            "full_name": "Иван Сергеевич Петров",
            "phone": "+7 999 111-22-33",
            "email": "ivan@example.com",
            "preferred_channel": "whatsapp",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        stored = db.session.get(Client, sample_client)
        assert stored.full_name == "Иван Сергеевич Петров"

    response = auth_client.post(f"/clients/{sample_client}/archive")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Client, sample_client).is_archived


def test_archived_client_can_be_deleted_permanently_with_files(
    app, auth_client, sample_client
):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={
            "text": "Старая запись 311231",
            "files": (BytesIO(b"old file"), "old.txt"),
        },
        content_type="multipart/form-data",
    )
    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        attachment_path = Path(interaction.attachments[0].file_path)
        assert attachment_path.exists()

    assert (
        auth_client.post(f"/clients/{sample_client}/delete-permanently").status_code
        == 400
    )
    auth_client.post(f"/clients/{sample_client}/archive")
    archive_page = auth_client.get("/clients/?archived=1")
    assert f'action="/clients/{sample_client}/delete-permanently"'.encode() in archive_page.data

    response = auth_client.post(
        f"/clients/{sample_client}/delete-permanently", follow_redirects=True
    )
    assert "удалён навсегда".encode() in response.data
    with app.app_context():
        assert db.session.get(Client, sample_client) is None
        assert db.session.scalar(db.select(Interaction)) is None
        assert db.session.scalar(db.select(CalendarEvent)) is None
    assert not attachment_path.exists()


def test_interaction_with_attachment(
    app, auth_client, sample_client, monkeypatch
):
    import app.clients as clients_module

    monkeypatch.setattr(clients_module, "utcnow", lambda: datetime(2026, 9, 16, 9))
    response = auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={
            "interaction_type": "call",
            "text": "Обсудили документы",
            "files": (BytesIO(b"test document"), "note.txt"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        assert interaction.text == "260916 Обсудили документы"
        assert len(interaction.attachments) == 1
        attachment_id = interaction.attachments[0].id

    response = auth_client.get(f"/clients/attachments/{attachment_id}")
    assert response.status_code == 200
    assert response.data == b"test document"


def test_history_uses_compact_date(auth_client, sample_client):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"interaction_type": "note", "text": "Новая запись"},
    )
    response = auth_client.get(f"/clients/{sample_client}")
    assert response.status_code == 200
    assert "Новая запись".encode() in response.data
    assert re.search(rb'class="timeline-date">\d{6}</time>', response.data)
    assert re.search(rb'<textarea[^>]+>\d{6} </textarea>', response.data)


def test_client_list_is_grouped_and_only_shows_names(auth_client, sample_client):
    response = auth_client.get("/clients/")
    assert response.status_code == 200
    assert "<summary><span>И</span>".encode() in response.data
    assert f'/clients/{sample_client}'.encode() in response.data
    assert "+7 999 111-22-33".encode() not in response.data
    assert "ivan@example.com".encode() not in response.data


def test_interaction_defaults_to_call_and_note_is_not_available(app, auth_client, sample_client):
    detail = auth_client.get(f"/clients/{sample_client}")
    assert b'<option value="note">' not in detail.data

    response = auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Позвонили клиенту"},
    )
    assert response.status_code == 302
    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        assert interaction.interaction_type == "call"


def test_interaction_date_creates_calendar_event_without_copying_text(
    app, auth_client, sample_client
):
    note = "Позвонить клиенту повторно 260911"
    response = auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"interaction_type": "call", "text": note},
        follow_redirects=True,
    )
    assert "дело добавлено на 11.09.2026 09:00".encode() in response.data

    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert event.client_id == sample_client
        assert event.comment == ""
        assert event.source_interaction_id is not None
        assert utc_naive_to_local(event.starts_at).strftime("%y%m%d %H:%M") == "260911 09:00"

    day = auth_client.get("/calendar/?view=day&date=2026-09-11")
    assert "Иван Петров".encode() in day.data
    assert note.encode() not in day.data
    assert f'/clients/{sample_client}'.encode() in day.data


def test_editing_interaction_reschedules_without_duplicate(
    app, auth_client, sample_client
):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Первый срок 260911"},
    )
    response = auth_client.post(
        f"/clients/{sample_client}/interactions/1/edit",
        data={"interaction_type": "call", "text": "Новый срок 260912 16:10"},
    )
    assert response.status_code == 302
    with app.app_context():
        events = db.session.scalars(db.select(CalendarEvent)).all()
        assert len(events) == 1
        assert utc_naive_to_local(events[0].starts_at).strftime("%y%m%d %H:%M") == "260912 16:10"


def test_deleting_interaction_deletes_generated_event(app, auth_client, sample_client):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Созвон 260911"},
    )
    auth_client.post(f"/clients/{sample_client}/interactions/1/delete")
    with app.app_context():
        assert db.session.scalar(db.select(CalendarEvent)) is None


def test_cleaning_newer_history_keeps_previous_event_completed(
    app, auth_client, sample_client
):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Первое дело 250101"},
    )
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Выполнено"},
    )
    auth_client.post(f"/clients/{sample_client}/interactions/2/delete")

    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert event.status == "completed"
        assert event.completed_at is not None
        assert event.completed_by_interaction_id is None


def test_archiving_client_hides_its_planned_events(app, auth_client, sample_client):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Созвон 260911"},
    )
    auth_client.post(f"/clients/{sample_client}/archive")
    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert event.status == "cancelled"

    response = auth_client.get("/calendar/?view=month&date=2026-09-01")
    assert '<span class="calendar-count">1</span>'.encode() not in response.data


def test_client_categories_are_in_one_row_and_mutually_exclusive(
    app, auth_client, sample_client
):
    response = auth_client.post(
        f"/clients/{sample_client}/group",
        data={"group": "a"},
        follow_redirects=True,
    )
    assert "Группа А".encode() in response.data
    with app.app_context():
        assert db.session.get(Client, sample_client).client_group == "a"

    listing = auth_client.get("/clients/")
    for label in ("А", "В", "Д", "К", "КН", "М", "П", "Р"):
        assert f"<span>{label}</span>".encode() in listing.data
    assert b'data-client-segment-open="client-segment-a"' in listing.data
    assert b'id="client-segment-a" data-client-segment-dialog' in listing.data
    assert f'href="/clients/{sample_client}"'.encode() in listing.data
    assert "Иван Петров".encode() in listing.data

    auth_client.post(
        f"/clients/{sample_client}/group", data={"group": "p"}
    )
    with app.app_context():
        assert db.session.get(Client, sample_client).client_group == "p"


def test_new_interaction_completes_previous_event_and_creates_next(
    app, auth_client, sample_client
):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Первый следующий шаг 311230"},
    )
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Выполнили и назначили следующий шаг 311231!"},
    )

    with app.app_context():
        events = db.session.scalars(
            db.select(CalendarEvent).order_by(CalendarEvent.id)
        ).all()
        assert len(events) == 2
        assert events[0].status == "completed"
        assert events[0].completed_by_interaction_id == 2
        assert events[0].completed_at is not None
        assert events[1].status == "planned"
        assert events[1].is_important is True


def test_interaction_submission_token_prevents_duplicate(
    app, auth_client, sample_client
):
    payload = {
        "text": "Один следующий шаг 311231",
        "submission_token": "fixed-interaction-token-123",
    }
    auth_client.post(f"/clients/{sample_client}/interactions", data=payload)
    auth_client.post(f"/clients/{sample_client}/interactions", data=payload)

    with app.app_context():
        assert len(db.session.scalars(db.select(Interaction)).all()) == 1
        assert len(db.session.scalars(db.select(CalendarEvent)).all()) == 1


def test_search_interactions_is_case_insensitive_and_returns_anchor(
    auth_client, sample_client
):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Обсудили договор и сроки поставки"},
    )
    response = auth_client.get("/clients/search?q=ДОГОВОР")
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["results"]) == 1
    assert payload["results"][0]["client_name"] == "Иван Петров"
    assert payload["results"][0]["match"] == "договор"
    assert payload["results"][0]["url"].endswith("#interaction-1")
