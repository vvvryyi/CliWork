from datetime import datetime

import pytest
from sqlalchemy import event as sql_event

from app.extensions import db
from app.models import CalendarEvent, Client, Interaction, utcnow
from app.utils import due_client_contact_events, local_to_utc_naive


@pytest.mark.parametrize('kind,endpoint', [('general', 'history'), ('d', 'd-comments')])
@pytest.mark.parametrize('text', ['301201', 'Обсудить\n301201\nЗапросить документы'])
def test_date_only_and_multiline_reminders(app, auth_client, sample_client, kind, endpoint, text):
    with app.app_context():
        db.session.get(Client, sample_client).client_group = 'd'
        db.session.commit()
    result = auth_client.post(f'/clients/{sample_client}/{endpoint}', data={'history_text': text})
    assert result.status_code == 302
    assert result.headers['Location'] == '/clients/'
    with app.app_context():
        item = db.session.scalar(db.select(Interaction))
        assert item.history_kind == kind
        assert '301201' in item.text
        assert item.calendar_event is not None
        assert item.calendar_event.starts_at == local_to_utc_naive('2030-12-01T09:00')
    assert 'Связаться сегодня: 1' in auth_client.get('/calendar/?view=month&date=2030-12-01').data.decode()
    assert '>Иван Петров</a>' in auth_client.get('/clients/contacts-today?date=2030-12-01').data.decode()


def test_dated_streams_stay_separate_after_plain_comment(app, auth_client, sample_client):
    with app.app_context():
        db.session.get(Client, sample_client).client_group = 'd'
        db.session.commit()
    auth_client.post(f'/clients/{sample_client}/history', data={'history_text': '301201'})
    auth_client.post(f'/clients/{sample_client}/d-comments', data={'history_text': '301201'})
    page = auth_client.get('/clients/contacts-today?date=2030-12-01').data.decode()
    assert page.count('>Иван Петров</a>') == 2
    assert 'Связаться сегодня: 2' in auth_client.get('/calendar/?view=month&date=2030-12-01').data.decode()
    # Automatic current date on a plain comment must not create a third event.
    auth_client.post(f'/clients/{sample_client}/interactions', data={'text': 'Обсудили'})
    with app.app_context():
        events = db.session.scalars(db.select(CalendarEvent)).all()
        assert len(events) == 2
        trading = next(item for item in events if item.source_interaction.history_kind == 'd')
        assert trading.status == 'planned'


def test_empty_prefilled_date_does_not_plan_a_task(app, auth_client, sample_client):
    from app.clients import build_history_text
    with app.app_context():
        text = build_history_text([], utcnow())
    auth_client.post(f'/clients/{sample_client}/history', data={'history_text': text})
    with app.app_context():
        assert db.session.scalar(db.select(CalendarEvent)) is None


def test_explicit_today_date_can_be_planned(app, auth_client, sample_client, monkeypatch):
    monkeypatch.setattr('app.clients.utcnow', lambda: datetime(2026, 10, 29, 9))
    result = auth_client.post(f'/clients/{sample_client}/history', data={'history_text': '261029'})
    assert result.headers['Location'] == '/clients/'
    with app.app_context():
        item = db.session.scalar(db.select(CalendarEvent))
        assert item is not None
        assert item.starts_at == local_to_utc_naive('2026-10-29T09:00')


def test_due_contacts_query_count_stays_bounded(app):
    with app.app_context():
        for i in range(100):
            contact = Client(full_name=f'Контакт {i}', client_group='d')
            db.session.add(contact)
            db.session.flush()
            item = Interaction(client_id=contact.id, history_kind='d', text='261029 Торговля')
            db.session.add(item)
            db.session.flush()
            db.session.add(CalendarEvent(client_id=contact.id, source_interaction_id=item.id, starts_at=datetime(2026, 10, 29, 6), status='planned'))
            db.session.add(CalendarEvent(client_id=contact.id, starts_at=datetime(2031, 1, 1, 6), status='planned'))
        db.session.commit()
        db.session.remove()
        statements = []
        def record(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        sql_event.listen(db.engine, 'before_cursor_execute', record)
        try:
            with app.test_request_context('/'):
                rows = due_client_contact_events(datetime(2026, 10, 29, 9))
                assert len(rows) == 100
                assert all(row.client.full_name and row.source_interaction.history_kind == 'd' for row in rows)
            assert len(statements) <= 4, f'{len(statements)} queries for 100 contacts'
        finally:
            sql_event.remove(db.engine, 'before_cursor_execute', record)
