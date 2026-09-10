from io import BytesIO

from app.extensions import db
from app.models import Client, Interaction


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


def test_interaction_with_attachment(app, auth_client, sample_client):
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
        assert interaction.text == "Обсудили документы"
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


def test_client_cards_have_prefilled_quick_actions(auth_client, sample_client):
    response = auth_client.get("/clients/")
    assert response.status_code == 200
    assert f"/messages/compose?client_id={sample_client}".encode() in response.data
    assert f"/calendar/events/new?client_id={sample_client}".encode() in response.data
    assert f"/reminders/new?client_id={sample_client}".encode() in response.data


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
