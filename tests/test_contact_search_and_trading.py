from datetime import datetime

from app.extensions import db
from app.models import Client, Interaction, CalendarEvent


def test_unicode_search_matches_name_and_both_comment_streams_once(app, auth_client):
    with app.app_context():
        names = ['Договоров', 'Анна', 'Мария', 'Другой', 'Архивный']
        clients = [Client(full_name=name, client_group='d') for name in names]
        clients[-1].archived_at = datetime(2026, 1, 1)
        clients[1].color_label = 'red'
        db.session.add_all(clients)
        db.session.flush()
        db.session.add_all([
            Interaction(client_id=clients[1].id, text='261106 Согласовать ДОГОВОР'),
            Interaction(client_id=clients[1].id, text='261106 Другой договор'),
            Interaction(client_id=clients[2].id, text='261106 Обсудить договор', history_kind='d'),
            Interaction(client_id=clients[-1].id, text='261106 ДОГОВОР'),
        ])
        db.session.commit()
        ids = [item.id for item in clients]
    for query in ['гово', 'ГОВО', 'гОвО']:
        page = auth_client.get('/clients/', query_string={'q': query}).data.decode()
        for id_ in ids[:3]:
            assert f'href="/clients/{id_}"' in page
        for id_ in ids[3:]:
            assert f'href="/clients/{id_}"' not in page
        results = auth_client.get('/clients/search', query_string={'q': query}).get_json()['results']
        assert len(results) == 3
        assert {item['client_name'] for item in results} == set(names[:3])
    filtered = auth_client.get('/clients/?q=ГОВО&color_label=red').data.decode()
    assert f'href="/clients/{ids[1]}"' in filtered
    assert f'href="/clients/{ids[0]}"' not in filtered
    assert auth_client.get('/clients/search?q=гов').get_json()['results'] == []


def test_search_returns_all_matching_contacts_and_literal_substrings(app, auth_client):
    with app.app_context():
        for i in range(55):
            contact = Client(full_name=f'Контакт {i}')
            db.session.add(contact)
            db.session.flush()
            db.session.add(Interaction(client_id=contact.id, text='Записка: АбВг_% literal'))
        db.session.commit()
    assert len(auth_client.get('/clients/search?q=аБвГ').get_json()['results']) == 55
    assert len(auth_client.get('/clients/search?q=г_% l').get_json()['results']) == 55
    assert auth_client.get('/clients/search?q=абв%').get_json()['results'] == []


def test_trading_stays_on_card_and_general_returns_to_contacts_without_merging_events(app, auth_client, sample_client):
    with app.app_context():
        db.session.get(Client, sample_client).client_group = 'd'
        db.session.commit()
    trading = auth_client.post(f'/clients/{sample_client}/d-comments', data={'history_text': '301201'})
    assert trading.status_code == 302
    assert trading.headers['Location'] == f'/clients/{sample_client}#d-comments'
    assert auth_client.get(trading.headers['Location']).status_code == 200
    general = auth_client.post(f'/clients/{sample_client}/history', data={'history_text': '301201'})
    assert general.status_code == 302
    assert general.headers['Location'] == '/clients/'
    with app.app_context():
        events = db.session.scalars(db.select(CalendarEvent)).all()
        assert len(events) == 2
        assert len({item.id for item in events}) == 2
        assert {item.source_interaction.history_kind for item in events} == {'d', 'general'}
        assert all(item.status == 'planned' for item in events)
        assert events[0].starts_at == events[1].starts_at
    calendar = auth_client.get('/calendar/?view=month&date=2030-12-01').data.decode()
    assert 'Связаться сегодня: 2' in calendar
    contacts = auth_client.get('/clients/contacts-today?date=2030-12-01').data.decode()
    assert contacts.count('>Иван Петров</a>') == 2
