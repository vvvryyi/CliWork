import pytest

from app import create_app
from app.extensions import db


@pytest.fixture()
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "CRM_USERNAME": "tester",
            "CRM_PASSWORD": "secret",
            "SECRET_KEY": "test-secret",
        }
    )
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(client):
    response = client.post(
        "/auth/login",
        data={"username": "tester", "password": "secret"},
    )
    assert response.status_code == 302
    return client


@pytest.fixture()
def sample_client(auth_client):
    response = auth_client.post(
        "/clients/new",
        data={
            "full_name": "Иван Петров",
            "phone": "+7 999 111-22-33",
            "email": "ivan@example.com",
            "preferred_channel": "telegram",
            "telegram": "@ivan",
        },
    )
    assert response.status_code == 302
    return 1

