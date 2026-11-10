from datetime import datetime
from io import BytesIO
from pathlib import Path

from app.clients import build_history_text, HISTORY_DIVIDER
from app.extensions import db
from app.models import Client, Interaction, CalendarEvent, DailyTask, GeneralTask


def test_joint_save_keeps_two_events(app, auth_client, sample_client):
    with app.app_context():
        db.session.get(Client, sample_client).client_group = 'd'
        db.session.commit()
    response = auth_client.post(f'/clients/{sample_client}/history', data={
        'history_text': '301201', 'trading_history_text': '301201', 'trading_history_ids': '',
        'files': (BytesIO(b'main'), 'main.txt'), 'trading_files': (BytesIO(b'trade'), 'trade.txt'),
    }, content_type='multipart/form-data')
    assert response.status_code == 302
    assert response.headers['Location'] == '/clients/'
    with app.app_context():
        records = db.session.scalars(db.select(Interaction)).all()
        assert {item.history_kind for item in records} == {'general', 'd'}
        assert all(len(item.attachments) == 1 for item in records)
        events = db.session.scalars(db.select(CalendarEvent)).all()
        assert len(events) == 2
        assert all(item.status == 'planned' for item in events)
        assert events[0].starts_at == events[1].starts_at
    page = auth_client.get(f'/clients/{sample_client}').data.decode()
    trade = page.split('<form id="d-comments"', 1)[1].split('</form>', 1)[0]
    assert '>Сохранить</button>' not in trade


def test_joint_save_rolls_back_both_streams_and_files(app, auth_client, sample_client):
    with app.app_context():
        db.session.get(Client, sample_client).client_group = 'd'
        db.session.commit()
    result = auth_client.post(f'/clients/{sample_client}/history', data={
        'history_text': '301201', 'trading_history_text': '301202', 'trading_history_ids': '999',
        'files': (BytesIO(b'file'), 'test.txt'),
    }, content_type='multipart/form-data')
    assert result.status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(Interaction)) is None
        assert db.session.scalar(db.select(CalendarEvent)) is None
        assert not list(Path(app.config['UPLOAD_FOLDER']).iterdir())


def test_current_date_does_not_repeat_when_opening_card(app):
    with app.app_context():
        item = Interaction(text='261110 Обсудили', created_at=datetime(2026, 11, 10), show_history_date=True)
        text = build_history_text([item], datetime(2026, 11, 10, 12))
        assert text.count('261110') == 1
        assert text.endswith(HISTORY_DIVIDER)
        item.text = '261109 Позвонить 261110'
        assert build_history_text([item], datetime(2026, 11, 10, 12)).count('261110') == 1


def test_calendar_search_all_texts_and_dates(app, auth_client, sample_client):
    with app.app_context():
        db.session.add_all([
            DailyTask(text='ДОГОВОР дневной', due_date=datetime(2020, 1, 1).date()),
            GeneralTask(text='Общее', comment='Условия договора'),
            Interaction(client_id=sample_client, text='261110 Согласовать договор', history_kind='d'),
            CalendarEvent(title='Давнее', comment='Договор', starts_at=datetime(2020, 1, 1), status='completed'),
        ])
        db.session.commit()
    page = auth_client.get('/calendar/search?q=дого').data.decode()
    for text in ['ДОГОВОР дневной', 'Общее', 'Согласовать договор', 'Давнее']:
        assert text in page
    assert 'Иван Петров' in auth_client.get('/calendar/search?q=пет').data.decode()
    assert 'Введите не менее 3' in auth_client.get('/calendar/search?q=до').data.decode()
