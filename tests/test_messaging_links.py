from html import unescape
from io import BytesIO
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from app.extensions import db
from app.models import Attachment, Client, Interaction
from app.utils import build_channel_url


@pytest.mark.parametrize("contact,parameter,value", [
    ("@ivan", "domain", "ivan"),
    ("https://t.me/ivan/", "domain", "ivan"),
    ("t.me/ivan", "domain", "ivan"),
    ("tg://resolve?domain=ivan", "domain", "ivan"),
    ("+7 (999) 111-22-33", "phone", "79991112233"),
    ("https://t.me/+79991112233", "phone", "79991112233"),
])
def test_telegram_opens_app_with_recipient_and_text(contact, parameter, value):
    client = Client(telegram=contact)
    link = urlsplit(build_channel_url(client, "telegram", "Привет & +?\nТекст"))
    assert (link.scheme, link.netloc) == ("tg", "resolve")
    assert parse_qs(link.query) == {parameter: [value], "text": ["Привет & +?\nТекст"]}


@pytest.mark.parametrize("contact", ["+7 (999) 111-22-33", "8 999 111 22 33", "wa.me/79991112233"])
def test_whatsapp_opens_app_and_normalizes_phone(contact):
    client = Client(whatsapp=contact)
    link = urlsplit(build_channel_url(client, "whatsapp", "Привет!"))
    assert (link.scheme, link.netloc) == ("whatsapp", "send")
    assert parse_qs(link.query) == {"phone": ["79991112233"], "text": ["Привет!"]}
    assert build_channel_url(client, "whatsapp", "", web=True).startswith("https://wa.me/79991112233")


@pytest.mark.parametrize("contact,expected", [
    ("max.ru/u/AbC_123-x", "https://max.ru/u/AbC_123-x"),
    ("http://max.ru/u/AbC_123-x", "https://max.ru/u/AbC_123-x"),
    ("https://www.max.ru/u/AbC_123-x", "https://max.ru/u/AbC_123-x"),
    ("+79991112233", ""),
    ("https://example.org/u/abc", ""),
    ("javascript:alert(1)", ""),
    ("https://[broken", ""),
])
def test_max_uses_profile_link(contact, expected):
    assert build_channel_url(Client(max_contact=contact), "max", "Текст") == expected


def test_message_can_be_prepared_from_client_card(app, auth_client, sample_client):
    page = auth_client.get(f"/clients/{sample_client}").data.decode()
    assert 'id="client-message"' in page
    assert 'action="/messages/compose"' in page
    assert '<option value="mailing">Рассылка</option>' in page
    for event_type in ("call", "meeting", "mailing"):
        assert f"event_type={event_type}" in unescape(page)
        event_form = auth_client.get(f"/calendar/events/new?client_id={sample_client}&event_type={event_type}").data.decode()
        assert f'<option value="{event_type}" selected>' in event_form
    prepared = auth_client.post("/messages/compose", data={
        "client_id": sample_client, "channel": "telegram", "message": "Текст из карточки",
        "files": (BytesIO(b"pdf"), "Документ.pdf"),
    }).data.decode()
    href = unescape(re.search(r'href="(tg://[^"]+)"', prepared).group(1))
    assert parse_qs(urlsplit(href).query)["text"] == ["Текст из карточки"]
    assert 'href="tg://' in prepared
    assert 'target="_blank"' not in prepared.split('href="tg://', 1)[1].split(">", 1)[0]
    with app.app_context():
        interaction = db.session.scalar(db.select(Interaction))
        assert interaction.delivery_status == "prepared"
        assert db.session.scalar(db.select(Attachment)).interaction_id == interaction.id


def test_invalid_contact_keeps_draft_without_creating_history(app, auth_client, sample_client):
    response = auth_client.post("/messages/compose", data={
        "client_id": sample_client, "channel": "max", "message": "Сохранить этот текст",
    })
    assert response.status_code == 200
    assert "Сохранить этот текст" in response.data.decode()
    assert '<option value="max" selected>' in response.data.decode()
    with app.app_context():
        assert db.session.scalar(db.select(Interaction)) is None


def test_history_supports_mailing_action(app, auth_client, sample_client):
    saved = auth_client.post(f"/clients/{sample_client}/history", data={
        "history_text": "Проведена рассылка", "interaction_type": "mailing",
    })
    assert saved.headers["Location"] == "/clients/"
    with app.app_context():
        assert db.session.scalar(db.select(Interaction)).interaction_type == "mailing"
