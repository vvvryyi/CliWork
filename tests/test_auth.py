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


def test_login_opens_dashboard(auth_client):
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "Добро пожаловать".encode() in response.data

