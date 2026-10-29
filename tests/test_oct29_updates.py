from datetime import datetime
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.extensions import db
from app.models import CalendarEvent, Client, Interaction, Attachment
from app.utils import local_to_utc_naive


def test_starred_completed_meeting_stays_on_original_day(app, auth_client, sample_client):
    with app.app_context():
        event = CalendarEvent(client_id=sample_client, starts_at=local_to_utc_naive('2026-10-15T10:00'), status='planned')
        db.session.add(event)
        db.session.commit()
        id_ = event.id
    url = f'/clients/contacts-today/events/{id_}/star'
    assert auth_client.post(url, data={'starred': '1'}).get_json() == {'starred': True}
    auth_client.post(f'/clients/{sample_client}/interactions', data={'text': 'Встреча прошла'})
    with app.app_context():
        event = db.session.get(CalendarEvent, id_)
        assert event.status == 'completed' and event.is_starred
        assert not event.is_important
    page = auth_client.get('/calendar/?view=month&date=2026-10-15').data.decode()
    assert 'aria-label="Связаться сегодня: 1"' in page
    assert 'Иван Петров' in auth_client.get('/clients/contacts-today?date=2026-10-15').data.decode()
    assert 'Иван Петров' not in auth_client.get('/clients/contacts-today?date=2026-10-16').data.decode()
    assert auth_client.post(url, data={'starred': 'bad'}).status_code == 400
    assert auth_client.post(url, data={'starred': '0'}).get_json() == {'starred': False}
    assert 'aria-label="Связаться сегодня: 1"' not in auth_client.get('/calendar/?view=month&date=2026-10-15').data.decode()


def test_general_and_trading_plans_remain_independent(app, auth_client, sample_client):
    with app.app_context():
        db.session.get(Client, sample_client).client_group = 'd'
        db.session.commit()
    auth_client.post(f'/clients/{sample_client}/history', data={'history_text': 'Позвонить 301015'})
    auth_client.post(f'/clients/{sample_client}/d-comments', data={'history_text': 'Купить 301015'})
    page = auth_client.get('/clients/contacts-today?date=2030-10-15').data.decode()
    assert page.count('>Иван Петров</a>') == 2
    assert 'Комментарий' in page and 'Торговля' in page
    assert 'Связаться сегодня: 2' in auth_client.get('/calendar/?view=month&date=2030-10-15').data.decode()
    with app.app_context():
        general = db.session.scalar(db.select(Interaction).where(Interaction.history_kind == 'general'))
        trading = db.session.scalar(db.select(Interaction).where(Interaction.history_kind == 'd'))
        assert general.calendar_event.status == trading.calendar_event.status == 'planned'
        trading_id = trading.id
        text = trading.text
    auth_client.post(f'/clients/{sample_client}/d-comments', data={'history_ids': str(trading_id), 'history_text': text + '\n\u2063Продолжить 301016'})
    with app.app_context():
        general = db.session.scalar(db.select(Interaction).where(Interaction.history_kind == 'general'))
        assert general.calendar_event.status == 'planned'
        assert db.session.get(Interaction, trading_id).calendar_event.status == 'completed'


@pytest.mark.parametrize('scope,url', [('daily', '/tasks/'), ('general', '/tasks/all')])
def test_task_search_across_dates_and_cyrillic_case(auth_client, scope, url):
    for text, date in [('Обсудить ДОГОВОР', '2020-01-01'), ('Другая задача', '2030-01-02')]:
        auth_client.post('/tasks/save', data={'task_scope': scope, 'text': text, 'due_date': date})
    page = auth_client.get(url + '?q=дого').data.decode()
    assert 'Обсудить ДОГОВОР' in page and 'Другая задача' not in page
    assert 'data-allow-create="0"' in page
    assert 'Введите не менее 3' in auth_client.get(url + '?q=до').data.decode()


def test_attachment_preview_and_download_are_separate(app, auth_client, sample_client):
    auth_client.post(f'/clients/{sample_client}/history', data={'history_text': 'Файлы', 'files': (BytesIO(b'%PDF-1.4 test'), 'file.pdf')}, content_type='multipart/form-data')
    with app.app_context():
        id_ = db.session.scalar(db.select(Attachment.id))
    card = auth_client.get(f'/clients/{sample_client}').data.decode()
    assert f'href="/clients/attachments/{id_}/preview"' in card
    assert '>Скачать</a>' in card
    assert '<iframe' in auth_client.get(f'/clients/attachments/{id_}/preview').data.decode()
    content = auth_client.get(f'/clients/attachments/{id_}/content')
    assert content.mimetype == 'application/pdf'
    assert not content.headers['Content-Disposition'].startswith('attachment')
    assert auth_client.get(f'/clients/attachments/{id_}').headers['Content-Disposition'].startswith('attachment')
    doc = BytesIO()
    with ZipFile(doc, 'w') as archive:
        archive.writestr('word/document.xml', '<document><t>Текст документа</t></document>')
    doc.seek(0)
    auth_client.post(f'/clients/{sample_client}/interactions', data={'text': 'Документ', 'files': (doc, 'document.docx')}, content_type='multipart/form-data')
    with app.app_context():
        id_ = db.session.scalar(db.select(Attachment.id).order_by(Attachment.id.desc()))
    assert 'Текст документа' in auth_client.get(f'/clients/attachments/{id_}/preview').data.decode()
    assert auth_client.get(f'/clients/attachments/{id_}/content').status_code == 415


def test_client_controls_removed_and_filter_order(auth_client, sample_client):
    page = auth_client.get('/clients/').data.decode()
    assert page.index('>Найти</button>') < page.index('<select name="channel">')
    page = auth_client.get(f'/clients/{sample_client}').data.decode()
    assert 'data-history-record' not in page
    assert '>Отметки<' not in page
    assert '<label>Действие' not in page
