from datetime import datetime
from io import BytesIO

import pytest

from app.clients import build_history_text
from app.color_labels import COLOR_LABELS
from app.extensions import db
from app.models import Attachment, CalendarEvent, Client, Interaction


@pytest.mark.parametrize("color", COLOR_LABELS)
def test_contact_label_create_change_and_clear(app, auth_client, color):
    response = auth_client.post("/clients/new", data={"full_name": "Цветной контакт", "color_label": color})
    assert response.status_code == 302
    with app.app_context():
        contact = db.session.scalar(db.select(Client))
        contact_id = contact.id
        assert contact.color_label == color
    listing = auth_client.get("/clients/").data.decode()
    assert f'data-color="{color}"' in listing
    assert COLOR_LABELS[color] in listing
    response = auth_client.post(f"/clients/{contact_id}/edit", data={"full_name": "Цветной контакт", "color_label": "gray"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Client, contact_id).color_label == "gray"
    # Older forms that do not send the new field cannot erase a saved label.
    auth_client.post(f"/clients/{contact_id}/edit", data={"full_name": "Цветной контакт"})
    with app.app_context():
        assert db.session.get(Client, contact_id).color_label == "gray"
    auth_client.post(f"/clients/{contact_id}/history", data={"history_text": "", "client_color_label": ""})
    with app.app_context():
        assert db.session.get(Client, contact_id).color_label == ""


def test_filter_contact_colors_in_groups_search_channels_and_archive(app, auth_client):
    with app.app_context():
        db.session.add_all([
            Client(full_name="Анна красная", color_label="red", client_group="d", preferred_channel="telegram"),
            Client(full_name="Антон серый", color_label="gray"),
            Client(full_name="Без цвета"),
            Client(full_name="Архив красный", color_label="red", archived_at=datetime(2026, 1, 1)),
            Client(full_name="Красный другой канал", color_label="red", preferred_channel="whatsapp"),
        ])
        db.session.commit()
    page = auth_client.get("/clients/?color_label=red").data.decode()
    assert "Анна красная" in page and "Красный другой канал" in page
    assert "Антон серый" not in page and "Без цвета" not in page and "Архив красный" not in page
    assert 'value="red" selected' in page
    assert 'Сбросить' in page
    page = auth_client.get("/clients/?color_label=red&channel=telegram&q=Анна").data.decode()
    assert "Анна красная" in page and "Красный другой канал" not in page
    page = auth_client.get("/clients/?color_label=unlabeled").data.decode()
    assert "Без цвета" in page and "Антон серый" not in page
    page = auth_client.get("/clients/?color_label=red&archived=1").data.decode()
    assert "Архив красный" in page and "Анна красная" not in page
    assert 'name="archived" value="1"' in page
    assert 'href="/clients/?archived=1"' in page
    assert auth_client.get("/clients/?color_label=purple").status_code == 400


@pytest.mark.parametrize("kind,endpoint", [("general", "history"), ("d", "d-comments")])
def test_comment_labels_independent_and_preserved_through_editing(app, auth_client, sample_client, kind, endpoint):
    with app.app_context():
        contact = db.session.get(Client, sample_client)
        contact.color_label = "yellow"
        contact.client_group = "d"
        records = [
            Interaction(client_id=contact.id, history_kind=kind, text="250101 Первая запись", color_label="red"),
            Interaction(client_id=contact.id, history_kind=kind, text="250102 Вторая запись", show_history_date=False, color_label="gray"),
        ]
        db.session.add_all(records)
        db.session.commit()
        ids = [item.id for item in records]
        dates = [item.created_at for item in records]
        history_text = build_history_text(records, datetime(2026, 10, 28))
    payload = {
        "history_ids": ",".join(map(str, ids)),
        "history_text": history_text.replace("Первая запись", "Первая правка") + "Третья запись",
        f"comment_color_{ids[0]}": "lemon",
        f"comment_color_{ids[1]}": "light_green",
        "new_comment_color": "orange",
    }
    response = auth_client.post(f"/clients/{sample_client}/{endpoint}", data=payload)
    assert response.status_code == 302
    with app.app_context():
        records = db.session.scalars(db.select(Interaction).order_by(Interaction.id)).all()
        assert [item.color_label for item in records] == ["lemon", "light_green", "orange"]
        assert [item.created_at for item in records[:2]] == dates
        assert records[0].text == "250101 Первая правка"
        assert records[1].show_history_date is False
        assert db.session.get(Client, sample_client).color_label == "yellow"
        ids = [item.id for item in records]
        # Removing a comment date does not remove its color; an omitted field preserves it.
        history_text = build_history_text(records, datetime(2026, 10, 28)).removeprefix("250101 ")
    response = auth_client.post(f"/clients/{sample_client}/{endpoint}", data={
        "history_ids": ",".join(map(str, ids)), "history_text": history_text,
        f"comment_color_{ids[1]}": "",
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Interaction, ids[0]).color_label == "lemon"
        assert db.session.get(Interaction, ids[0]).show_history_date is False
        assert db.session.get(Interaction, ids[1]).color_label == ""
        assert db.session.get(Interaction, ids[2]).color_label == "orange"
    page = auth_client.get(f"/clients/{sample_client}").data.decode()
    assert f'name="comment_color_{ids[0]}" value="lemon"' in page
    assert f'name="comment_color_{ids[2]}" value="orange"' in page
    assert 'Введите текст сразу после даты в той же строке.' not in page


def test_contact_and_comment_invalid_colors_roll_back(app, auth_client, sample_client):
    assert auth_client.post("/clients/new", data={"full_name": "Невалидный", "color_label": "purple"}).status_code == 400
    assert auth_client.post(f"/clients/{sample_client}/edit", data={"full_name": "Перезапись", "color_label": "purple"}).status_code == 400
    response = auth_client.post(f"/clients/{sample_client}/history", data={
        "history_text": "Комментарий", "client_color_label": "red", "new_comment_color": "purple",
    })
    assert response.status_code == 400
    response = auth_client.post(f"/clients/{sample_client}/history", data={
        "history_text": "Комментарий", "client_color_label": "purple", "new_comment_color": "red",
    })
    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(Client, sample_client).full_name == "Иван Петров"
        assert db.session.get(Client, sample_client).color_label == ""
        assert db.session.scalar(db.select(Interaction)) is None
        assert db.session.scalar(db.select(db.func.count(Client.id))) == 1


def test_comment_color_cannot_update_another_contact_or_stream(app, auth_client, sample_client):
    with app.app_context():
        other = Client(full_name="Другой")
        db.session.add(other)
        db.session.flush()
        record = Interaction(client_id=other.id, text="250101 Чужой", color_label="gray")
        d_record = Interaction(client_id=sample_client, history_kind="d", text="250101 Д", color_label="orange")
        db.session.add_all([record, d_record])
        db.session.commit()
        ids = [record.id, d_record.id]
    for record_id in ids:
        response = auth_client.post(f"/clients/{sample_client}/history", data={
            "history_text": "Попытка", f"comment_color_{record_id}": "red",
        })
        assert response.status_code == 400
    with app.app_context():
        assert [db.session.get(Interaction, id_).color_label for id_ in ids] == ["gray", "orange"]


def test_failed_upload_retains_selected_colors_and_text(app, auth_client, sample_client):
    with app.app_context():
        item = Interaction(client_id=sample_client, text="250101 Запись", color_label="gray")
        db.session.add(item)
        db.session.commit()
        record_id = item.id
        history_text = build_history_text([item], datetime(2026, 10, 28))
    response = auth_client.post(f"/clients/{sample_client}/history", data={
        "history_ids": str(record_id), "history_text": history_text + "Новая запись",
        f"comment_color_{record_id}": "yellow", "new_comment_color": "red",
        "files": (BytesIO(b"exe"), "bad.exe"),
    }, content_type="multipart/form-data")
    assert response.status_code == 400
    page = response.data.decode()
    assert f'name="comment_color_{record_id}" value="yellow"' in page
    assert 'name="new_comment_color" value="red"' in page
    assert 'Новая запись' in page
    with app.app_context():
        assert db.session.get(Interaction, record_id).color_label == "gray"
        assert db.session.scalar(db.select(Attachment)) is None
        assert db.session.scalar(db.select(CalendarEvent)) is None
