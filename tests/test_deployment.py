from flask import request

from app import create_app


def test_trusted_proxy_uses_forwarded_https(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "TRUST_PROXY_HEADERS": True,
            "SESSION_COOKIE_SECURE": True,
        }
    )

    @application.get("/_test/request-scheme")
    def request_scheme():
        return {"scheme": request.scheme}

    response = application.test_client().get(
        "/_test/request-scheme",
        headers={"X-Forwarded-Proto": "https"},
    )

    assert response.get_json() == {"scheme": "https"}
    assert application.config["SESSION_COOKIE_SECURE"] is True
