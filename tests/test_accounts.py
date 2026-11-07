import pytest
from flask import g


@pytest.fixture(autouse=True)
def independent_request_users(app):
    # The shared test fixture holds an app context across requests. Production
    # creates a fresh context per request, including Flask-Login's user cache.
    @app.before_request
    def clear_user_cache():
        g.pop("_login_user", None)


from app.extensions import db
from app.models import User, Client, CalendarEvent, Attachment
from werkzeug.security import generate_password_hash


def register(client, email):
    return client.post('/auth/register', data={'email': email, 'password': 'test-pass-123', 'password_confirm': 'test-pass-123'})


def test_accounts_keep_legacy_data_private(app, auth_client):
    auth_client.post('/clients/new', data={'full_name': 'Legacy private contact'})
    with app.app_context():
        contact = db.session.scalar(db.select(Client))
        contact_id = contact.id
    other = app.test_client()
    assert register(other, 'new@example.com').status_code == 302
    assert b'Legacy private contact' not in other.get('/clients/').data
    assert other.get(f'/clients/{contact_id}').status_code == 404
    assert other.post(f'/clients/{contact_id}/edit', data={'full_name': 'stolen'}).status_code == 404
    assert other.get('/auth/users').status_code == 403
    assert 'Пользователи'.encode() not in other.get('/').data
    other.post('/clients/new', data={'full_name': 'New private contact'})
    assert b'New private contact' not in auth_client.get('/clients/').data
    assert b'Legacy private contact' in auth_client.get('/clients/').data
    other.post('/auth/logout')
    assert other.post('/auth/login', data={'username': 'NEW@example.com', 'password': 'test-pass-123'}).status_code == 302
    assert b'New private contact' in other.get('/clients/').data


def test_admin_only_users_list(app, client):
    with app.app_context():
        db.session.add(User(id='admin-test', email='admin@example.com', password_hash=generate_password_hash('admin-pass'), is_admin=True))
        db.session.commit()
    register(client, 'member@example.com')
    client.post('/auth/logout')
    client.post('/auth/login', data={'username': 'admin@example.com', 'password': 'admin-pass'})
    page = client.get('/auth/users')
    assert page.status_code == 200
    assert b'member@example.com' in page.data
    assert b'password_hash' not in page.data
    assert 'Пользователи'.encode() in client.get('/').data


def test_duplicate_registration_and_password_storage(app, client):
    register(client, 'member@example.com')
    client.post('/auth/logout')
    page = register(client, 'MEMBER@example.com')
    assert 'уже зарегистрирован'.encode() in page.data
    with app.app_context():
        users = db.session.scalars(db.select(User)).all()
        assert len(users) == 1
        assert users[0].password_hash != 'test-pass-123'
        assert not users[0].is_admin


def test_settings_are_personal(app, auth_client):
    other = app.test_client()
    register(other, 'member@example.com')
    other.post('/settings/', data={'timezone': 'Asia/Tokyo'})
    assert b'Asia/Tokyo' in other.get('/settings/').data
    assert b'value="Asia/Tokyo"' not in auth_client.get('/settings/').data
    other.get('/settings/2fa/setup')
    assert auth_client.get('/settings/2fa/setup').status_code == 200


def test_foreign_files_and_calendar_links_are_blocked(app, auth_client):
    from datetime import datetime
    with app.app_context():
        contact = Client(full_name='Private')
        db.session.add(contact)
        db.session.flush()
        attachment = Attachment(client_id=contact.id, original_name='private.txt', stored_name='private.txt', file_path='private.txt')
        event = CalendarEvent(client_id=contact.id, starts_at=datetime(2027, 1, 1))
        db.session.add_all([attachment, event])
        db.session.commit()
        contact_id, attachment_id, event_id = contact.id, attachment.id, event.id
    other = app.test_client()
    register(other, 'outsider@example.com')
    for path in [f'/clients/attachments/{attachment_id}', f'/clients/attachments/{attachment_id}/content', f'/clients/attachments/{attachment_id}/preview', f'/calendar/events/{event_id}/edit']:
        assert other.get(path).status_code == 404
    response = other.post('/calendar/events/new', data={'client_id': contact_id, 'starts_at': '270101', 'title': 'Bad link'})
    assert response.status_code == 404
