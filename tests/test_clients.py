import html
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import CalendarEvent, Client, Interaction
from app.utils import interaction_text_body, utc_naive_to_local


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


def test_client_history_is_one_editor_and_saves_old_and_new_entries(
    app, auth_client, sample_client
):
    original_text = "Строка один\nСтрока два 260920"
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": original_text},
    )

    detail = auth_client.get(f"/clients/{sample_client}")
    assert b'class="timeline client-history"' in detail.data
    assert detail.data.count(b"<textarea") == 1
    assert b'name="history_text"' in detail.data
    assert b"data-history-editor" in detail.data
    assert b"data-dated-interaction" not in detail.data
    assert original_text.encode() in detail.data
    assert f'action="/clients/{sample_client}/history"'.encode() in detail.data
    assert detail.data.count(b"data-history-edit>") == 1
    assert b"client-history-record-actions" not in detail.data
    assert "Запись 1".encode() not in detail.data
    assert "Новую запись добавьте внизу истории".encode() not in detail.data
    assert detail.data.count(b"<form") == detail.data.count(b"</form>")
    history_text = html.unescape(
        re.search(rb'<textarea id="history-editor"[^>]*>(.*?)</textarea>', detail.data, re.S)
        .group(1)
        .decode()
    )
    assert "──────────" not in history_text
    assert "\n\u2063" in history_text
    updated_text = "Новая запись\nСледующий шаг 260921 11:00"
    history_text = history_text.replace("Строка один", "Исправленная строка") + updated_text
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "1", "history_text": history_text},
    )
    assert response.status_code == 302
    with app.app_context():
        interactions = db.session.scalars(
            db.select(Interaction).order_by(Interaction.id)
        ).all()
        assert len(interactions) == 2
        assert interactions[0].text.endswith("Исправленная строка\nСтрока два 260920")
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

    detail = auth_client.get(f"/clients/{sample_client}")
    assert f'href="/clients/attachments/{attachment_id}"'.encode() in detail.data
    response = auth_client.get(f"/clients/attachments/{attachment_id}")
    assert response.status_code == 200
    assert response.data == b"test document"


def test_heic_attachment_is_allowed(app, auth_client, sample_client):
    response = auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={
            "text": "Фото документа",
            "files": (BytesIO(b"heic image"), "document.HEIC"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        assert interaction.attachments[0].stored_name.endswith(".heic")


def test_history_uses_compact_date(auth_client, sample_client):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"interaction_type": "note", "text": "Новая запись"},
    )
    response = auth_client.get(f"/clients/{sample_client}")
    assert response.status_code == 200
    assert "Новая запись".encode() in response.data
    assert re.search(rb'<textarea id="history-editor"[^>]+>\d{6}\n', response.data)
    assert "──────────".encode() not in response.data
    assert "\n\u2063".encode() in response.data
    assert re.search(rb'\d{6} </textarea>', response.data)


def test_inline_history_edit_keeps_record_date_and_updates_its_event(
    app, auth_client, sample_client
):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Следующий шаг 301201"},
    )
    with app.app_context():
        original = db.session.scalar(db.select(Interaction))
        created_at = original.created_at
        original_prefix = original.text.split(" ", 1)[0]
        event_id = original.calendar_event.id

    detail = auth_client.get(f"/clients/{sample_client}")
    history_text = html.unescape(
        re.search(rb'<textarea id="history-editor"[^>]*>(.*?)</textarea>', detail.data, re.S)
        .group(1)
        .decode()
    ).replace("Следующий шаг 301201", "Исправленный шаг 301202 14:00!")
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "1", "history_text": history_text},
    )
    assert response.status_code == 302
    with app.app_context():
        interaction = db.session.get(Interaction, 1)
        event = db.session.get(CalendarEvent, event_id)
        assert interaction.created_at == created_at
        assert interaction.text == f"{original_prefix} Исправленный шаг 301202 14:00!"
        saved_text = interaction.text
        assert utc_naive_to_local(event.starts_at).strftime("%y%m%d %H:%M") == "301202 14:00"
        assert event.is_important is True

    invalid = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "1", "history_text": "260101\nПовреждённая история"},
    )
    assert invalid.status_code == 400
    with app.app_context():
        assert db.session.get(Interaction, 1).text == saved_text


def test_history_date_can_be_removed_without_deleting_record_or_event(
    app, auth_client, sample_client
):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "Позвонить 301201"},
    )
    with app.app_context():
        interaction = db.session.get(Interaction, 1)
        created_at = interaction.created_at
        event_id = interaction.calendar_event.id

    detail = auth_client.get(f"/clients/{sample_client}")
    history_text = html.unescape(
        re.search(rb'<textarea id="history-editor"[^>]*>(.*?)</textarea>', detail.data, re.S)
        .group(1)
        .decode()
    )
    history_text = history_text.split("\n", 1)[1]
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "1", "history_text": history_text},
    )
    assert response.status_code == 302

    with app.app_context():
        interaction = db.session.get(Interaction, 1)
        assert interaction.created_at == created_at
        assert interaction.show_history_date is False
        assert db.session.get(CalendarEvent, event_id) is not None

    detail = auth_client.get(f"/clients/{sample_client}")
    history_text = html.unescape(
        re.search(rb'<textarea id="history-editor"[^>]*>(.*?)</textarea>', detail.data, re.S)
        .group(1)
        .decode()
    )
    assert history_text.startswith("Позвонить 301201")
    edit_page = auth_client.get(f"/clients/{sample_client}/interactions/1/edit")
    assert b"data-dated-interaction" not in edit_page.data
    assert "<textarea name=\"text\" rows=\"7\" >Позвонить 301201</textarea>".encode() in edit_page.data


def test_new_history_entry_can_be_saved_without_visible_date(
    app, auth_client, sample_client
):
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "", "history_text": "Запись без даты"},
    )
    assert response.status_code == 302
    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        assert interaction.show_history_date is False
        assert interaction_text_body(interaction.text) == "Запись без даты"

    detail = auth_client.get(f"/clients/{sample_client}")
    history_text = html.unescape(
        re.search(rb'<textarea id="history-editor"[^>]*>(.*?)</textarea>', detail.data, re.S)
        .group(1)
        .decode()
    )
    assert history_text.startswith("Запись без даты")


def test_clearing_history_entry_removes_record_event_and_attachment(
    app, auth_client, sample_client
):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={
            "text": "Созвон 301201",
            "files": (BytesIO(b"note"), "note.txt"),
        },
        content_type="multipart/form-data",
    )
    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        attachment_path = Path(interaction.attachments[0].file_path)
        assert attachment_path.exists()

    detail = auth_client.get(f"/clients/{sample_client}")
    history_text = html.unescape(
        re.search(rb'<textarea id="history-editor"[^>]*>(.*?)</textarea>', detail.data, re.S)
        .group(1)
        .decode()
    ).replace("Созвон 301201", "")
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "1", "history_text": history_text},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Interaction, 1) is None
        assert db.session.scalar(db.select(CalendarEvent)) is None
    assert not attachment_path.exists()


def test_unchanged_attachment_only_history_entry_is_kept(app, auth_client, sample_client):
    auth_client.post(
        f"/clients/{sample_client}/interactions",
        data={"text": "", "files": (BytesIO(b"note"), "note.txt")},
        content_type="multipart/form-data",
    )
    detail = auth_client.get(f"/clients/{sample_client}")
    history_text = html.unescape(
        re.search(rb'<textarea id="history-editor"[^>]*>(.*?)</textarea>', detail.data, re.S)
        .group(1)
        .decode()
    )
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "1", "history_text": history_text},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Interaction, 1) is not None

    cleared = "\n\u2063" + history_text.split("\n\u2063", 1)[1]
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_ids": "1", "history_text": cleared},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Interaction, 1) is None


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

    day = auth_client.get("/calendar/?view=day&date=2026-09-11&tab=contacts")
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
    labels = ("Д", "Б", "В", "Р", "М", "П", "А", "Н")
    for label in labels:
        assert f"<span>{label}</span>".encode() in listing.data
    positions = [listing.data.index(f"<span>{label}</span>".encode()) for label in labels]
    assert positions == sorted(positions)
    assert "<span>Х</span>".encode() not in listing.data
    assert b'data-client-segment-open="client-segment-a"' in listing.data
    assert b'id="client-segment-a" data-client-segment-dialog' in listing.data
    assert f'href="/clients/{sample_client}"'.encode() in listing.data
    assert "Иван Петров".encode() in listing.data

    detail = auth_client.get(f"/clients/{sample_client}")
    assert b'<option value="b"' in detail.data
    auth_client.post(
        f"/clients/{sample_client}/group", data={"group": "b"}
    )
    with app.app_context():
        assert db.session.get(Client, sample_client).client_group == "b"
    listing = auth_client.get("/clients/")
    assert b'data-client-segment-open="client-segment-b"' in listing.data
    assert b'id="client-segment-b" data-client-segment-dialog' in listing.data
    assert f'href="/clients/{sample_client}"'.encode() in listing.data
    assert "Группа В".encode() in auth_client.get(f"/clients/{sample_client}").data

    auth_client.post(
        f"/clients/{sample_client}/group", data={"group": "p"}
    )
    with app.app_context():
        assert db.session.get(Client, sample_client).client_group == "p"

    auth_client.post(
        f"/clients/{sample_client}/group", data={"group": "none"}
    )
    with app.app_context():
        assert db.session.get(Client, sample_client).client_group == "none"


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
