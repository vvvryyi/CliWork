import pytest

from app.extensions import db
from app.models import CalendarEvent
from app.utils import utc_naive_to_local


@pytest.mark.parametrize("invalid_date", ["301332", "300231", "302010", ""])
def test_invalid_edit_does_not_flush_or_lose_session(app, auth_client, invalid_date):
    task = auth_client.post("/tasks/save", data={"text": "Исходное", "due_date": "2030-12-02"}).get_json()
    url = task["calendar_url"]
    response = auth_client.post(url, data={"title": "Новый текст", "comment": "Сохранить черновик", "starts_at": invalid_date})
    assert response.status_code == 200
    assert 'value="Новый текст"' in response.data.decode()
    assert "Сохранить черновик" in response.data.decode()
    assert auth_client.get("/tasks/all").status_code == 200
    with app.app_context():
        event = db.session.scalar(db.select(CalendarEvent))
        assert utc_naive_to_local(event.starts_at).strftime("%y%m%d") == "301202"
        assert event.title == "Исходное"
    saved = auth_client.post(url, data={"title": "Новый текст", "starts_at": "301203"})
    assert saved.headers["Location"] == "/"
