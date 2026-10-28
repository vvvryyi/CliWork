import html
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest

from app.clients import HISTORY_DIVIDER
from app.extensions import db
from app.models import Attachment, CalendarEvent, Client, Interaction


def editor_text(page, editor_id):
    return html.unescape(re.search(
        rf'<textarea id="{editor_id}"[^>]*>(.*?)</textarea>', page, re.S
    ).group(1))


@pytest.fixture()
def d_client(app, sample_client):
    with app.app_context():
        contact = db.session.get(Client, sample_client)
        contact.client_group = "d"
        contact.flag_f = True
        contact.quarterly_reminder_mmdd = "1120"
        db.session.commit()
    return sample_client


def test_contact_panel_removed_and_d_editor_scoped_to_group(app, auth_client, sample_client):
    page = auth_client.get(f"/clients/{sample_client}").data.decode()
    assert 'contact-panel' not in page
    assert '<dt>Телефон</dt>' not in page
    assert '<dt>WhatsApp</dt>' not in page
    assert 'id="d-history-editor"' not in page
    assert auth_client.post(f"/clients/{sample_client}/d-comments").status_code == 404
    with app.app_context():
        contact = db.session.get(Client, sample_client)
        assert contact.phone == "+7 999 111-22-33"
        assert contact.telegram == "@ivan"


def test_d_comments_are_independent_dated_and_idempotent(app, auth_client, d_client, monkeypatch):
    monkeypatch.setattr("app.clients.utcnow", lambda: datetime(2026, 10, 27, 9))
    auth_client.post(f"/clients/{d_client}/interactions", data={"text": "Основная история 301201"})
    with app.app_context():
        contact = db.session.get(Client, d_client)
        contact.flag_f = True
        contact.quarterly_reminder_mmdd = "1120"
        db.session.commit()
    page = auth_client.get(f"/clients/{d_client}").data.decode()
    assert editor_text(page, "d-history-editor") == "261027 "
    assert 'Основная история' in editor_text(page, "history-editor")
    assert page.count('<form') == page.count('</form>')
    payload = {"history_text": "261027 Документы на согласовании 301202", "submission_token": "d-comment-token-1234"}
    response = auth_client.post(f"/clients/{d_client}/d-comments", data=payload)
    assert response.headers["Location"] == f"/clients/{d_client}#d-comments"
    # An immediate duplicate from an old page cannot create a second comment.
    assert auth_client.post(f"/clients/{d_client}/d-comments", data=payload).status_code == 400
    with app.app_context():
        comments = db.session.scalars(db.select(Interaction).where(Interaction.history_kind == "d")).all()
        assert len(comments) == 1
        assert comments[0].text == payload["history_text"]
        contact = db.session.get(Client, d_client)
        assert contact.flag_f is True
        assert contact.quarterly_reminder_mmdd == "1120"
        event = db.session.scalar(db.select(CalendarEvent))
        assert event.status == "planned"
        assert db.session.scalar(db.select(db.func.count(CalendarEvent.id))) == 1
    page = auth_client.get(f"/clients/{d_client}").data.decode()
    assert 'Документы на согласовании' not in editor_text(page, "history-editor")
    assert 'Основная история' not in editor_text(page, "d-history-editor")
    # Saving the general stream works even though D comments also exist.
    response = auth_client.post(f"/clients/{d_client}/history", data={
        "history_ids": "1", "history_text": editor_text(page, "history-editor") + "Новый звонок",
    })
    assert response.status_code == 302
    assert 'Документы на согласовании' in auth_client.get(f"/clients/{d_client}").data.decode()


def test_d_comments_edit_hide_date_delete_and_survive_group_change(app, auth_client, d_client, monkeypatch):
    with app.app_context():
        comment = Interaction(client_id=d_client, history_kind="d", text="250101 Старая запись")
        db.session.add(comment)
        db.session.commit()
        comment_id = comment.id
    monkeypatch.setattr("app.clients.utcnow", lambda: datetime(2026, 10, 27, 9))
    page = auth_client.get(f"/clients/{d_client}").data.decode()
    text = editor_text(page, "d-history-editor").replace("Старая запись", "Правка")
    response = auth_client.post(f"/clients/{d_client}/d-comments", data={
        "history_ids": str(comment_id), "history_text": text,
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Interaction, comment_id).text == "250101 Правка"
    auth_client.post(f"/clients/{d_client}/group", data={"group": "b"})
    assert '250101 Правка' in auth_client.get(f"/clients/{d_client}").data.decode()
    auth_client.post(f"/clients/{d_client}/d-comments", data={
        "history_ids": str(comment_id), "history_text": "Правка" + HISTORY_DIVIDER + "261027 ",
    })
    with app.app_context():
        assert db.session.get(Interaction, comment_id).show_history_date is False
    response = auth_client.post(f"/clients/{d_client}/d-comments", data={
        "history_ids": str(comment_id), "history_text": HISTORY_DIVIDER + "261027 ",
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Interaction, comment_id) is None


def test_d_comments_multiple_documents_download_and_delete(app, auth_client, d_client):
    documents = {"Договор.pdf": b"pdf", "Анкета.docx": b"docx", "Расчёт.xlsx": b"xlsx", "Фото.png": b"png"}
    response = auth_client.post(f"/clients/{d_client}/d-comments", data={
        "history_text": "", "files": [(BytesIO(content), name) for name, content in documents.items()],
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with app.app_context():
        comment = db.session.scalar(db.select(Interaction))
        assert comment.history_kind == "d"
        assert len(comment.attachments) == len(documents)
        files = [(file.id, file.original_name, Path(file.file_path)) for file in comment.attachments]
        comment_id = comment.id
    page = auth_client.get(f"/clients/{d_client}").data.decode()
    general_form = page.split('class="panel form-stack client-detail-form"', 1)[1].split('</form>', 1)[0]
    for file_id, name, path in files:
        assert name in page
        assert name not in general_form
        assert path.read_bytes() == documents[name]
        assert auth_client.get(f"/clients/attachments/{file_id}").data == documents[name]
    # Individual attachment deletion and removal of a whole comment both clean up disk files.
    auth_client.post(f"/clients/attachments/{files[0][0]}/delete")
    assert not files[0][2].exists()
    page = auth_client.get(f"/clients/{d_client}").data.decode()
    auth_client.post(f"/clients/{d_client}/d-comments", data={
        "history_ids": str(comment_id), "history_text": HISTORY_DIVIDER + "261027 ",
    })
    assert all(not path.exists() for _, _, path in files)
    with app.app_context():
        assert db.session.scalar(db.select(Attachment)) is None


def test_d_invalid_upload_rolls_back_and_preserves_both_editors(app, auth_client, d_client):
    auth_client.post(f"/clients/{d_client}/interactions", data={"text": "Обычный комментарий"})
    response = auth_client.post(f"/clients/{d_client}/d-comments", data={
        "history_text": "Не потерять текст", "files": [(BytesIO(b"pdf"), "valid.pdf"), (BytesIO(b"exe"), "bad.exe")],
    }, content_type="multipart/form-data")
    assert response.status_code == 400
    page = response.data.decode()
    assert 'Формат .exe не разрешён.' in page
    assert 'Не потерять текст' in editor_text(page, "d-history-editor")
    assert 'Обычный комментарий' in editor_text(page, "history-editor")
    with app.app_context():
        assert db.session.scalar(db.select(Interaction).where(Interaction.history_kind == "d")) is None
        assert db.session.scalar(db.select(Attachment)) is None
        assert list(Path(app.config["UPLOAD_FOLDER"]).iterdir()) == []


def test_d_comment_requires_login_and_active_contact(client, auth_client, d_client):
    auth_client.post(f"/clients/{d_client}/archive")
    assert auth_client.post(f"/clients/{d_client}/d-comments").status_code == 404
    auth_client.post("/auth/logout")
    response = client.post(f"/clients/{d_client}/d-comments")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_migration_preserves_existing_history_and_attachments(tmp_path):
    from flask_migrate import downgrade, upgrade
    from sqlalchemy import text

    from app import create_app

    application = create_app({
        "TESTING": True, "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'migration.sqlite3').as_posix()}",
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
    })
    with application.app_context():
        upgrade(revision="f05a1005c321")
        db.session.execute(text("""
            INSERT INTO clients (id, full_name, phone, email, additional_contacts, notes,
                preferred_channel, whatsapp, telegram, max_contact, instagram, facebook,
                created_at, updated_at)
            VALUES (1, 'Legacy', '', '', '', '', '', '', '', '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        db.session.execute(text("""
            INSERT INTO interactions (id, client_id, text, interaction_type, channel,
                delivery_status, created_at, updated_at)
            VALUES (1, 1, '250101 Original', 'call', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        db.session.execute(text("""
            INSERT INTO attachments (client_id, interaction_id, original_name, stored_name,
                file_path, mime_type, file_size, created_at, updated_at)
            VALUES (1, 1, 'old.pdf', 'old.pdf', 'old.pdf', 'application/pdf', 12, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        db.session.commit()
        upgrade()
        record = db.session.get(Interaction, 1)
        assert record.history_kind == "general"
        assert record.color_label == ""
        assert record.client.color_label == ""
        assert record.text == "250101 Original"
        assert record.attachments[0].original_name == "old.pdf"
        db.session.remove()
        downgrade(revision="f05a1005c321")
        assert db.session.execute(text("SELECT text FROM interactions WHERE id=1")).scalar() == "250101 Original"
        db.session.remove()
        upgrade()
        assert db.session.get(Interaction, 1).history_kind == "general"
