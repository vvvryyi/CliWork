from app.extensions import db
from app.models import AppSetting
from app.totp import current_code


def test_protected_page_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_rejects_invalid_credentials(client):
    response = client.post(
        "/auth/login",
        data={"username": "tester", "password": "wrong"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Неверный логин или пароль".encode() in response.data


def test_login_supports_non_ascii_credentials(tmp_path):
    from app import create_app

    application = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "CRM_USERNAME": "Артём",
            "CRM_PASSWORD": "пароль-для-CRM",
            "SECRET_KEY": "test-secret",
        }
    )
    with application.app_context():
        db.create_all()
    response = application.test_client().post(
        "/auth/login",
        data={"username": "Артём", "password": "пароль-для-CRM"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_login_opens_dashboard(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "Связаться сегодня".encode() in response.data
    assert "Добро пожаловать".encode() not in response.data


def test_login_requires_totp_when_enabled(app, client):
    secret = "JBSWY3DPEHPK3PXP"
    with app.app_context():
        db.session.add(AppSetting(key="totp_secret", value=secret))
        db.session.commit()

    response = client.post(
        "/auth/login",
        data={"username": "tester", "password": "secret"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/2fa")
    assert client.get("/").status_code == 302

    response = client.post("/auth/2fa", data={"code": current_code(secret)})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200


def test_enable_totp_from_settings(app, auth_client):
    response = auth_client.get("/settings/2fa/setup")
    assert response.status_code == 200
    assert "Ключ настройки".encode() in response.data

    with app.app_context():
        secret = db.session.get(AppSetting, "totp_pending_secret").value

    response = auth_client.post(
        "/settings/2fa/setup",
        data={"code": current_code(secret)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Двухфакторная аутентификация включена".encode() in response.data
    with app.app_context():
        assert db.session.get(AppSetting, "totp_secret").value == secret
