from app.extensions import db
from app.models import GeneralTask


def test_general_task_arrow_opens_card_and_comment_is_saved(app, auth_client):
    created = auth_client.post(
        "/tasks/save",
        data={"task_scope": "general", "text": "Общее дело"},
    ).get_json()
    task_id = created["task_id"]
    detail_url = f"/tasks/all/{task_id}"
    assert created["calendar_url"] == detail_url
    assert created["has_comment"] is False

    listing = auth_client.get("/tasks/all").data.decode()
    row = listing.split(f'data-task-id="{task_id}"', 1)[1].split("data-task-row", 1)[0]
    assert f'href="{detail_url}"' in row
    assert "task-calendar-link is-hidden" not in row
    assert 'style="color: #c65a00"' not in row

    detail = auth_client.get(detail_url)
    assert detail.status_code == 200
    assert "Общее дело" in detail.data.decode()

    saved = auth_client.post(
        detail_url,
        data={"text": "Обновлённое дело", "comment": "Подробности", "important": "1"},
    )
    assert saved.status_code == 302
    assert saved.headers["Location"].endswith("/tasks/all")
    with app.app_context():
        task = db.session.get(GeneralTask, task_id)
        assert task.text == "Обновлённое дело"
        assert task.comment == "Подробности"
        assert task.is_important is True

    listing = auth_client.get("/tasks/all").data.decode()
    row = listing.split(f'data-task-id="{task_id}"', 1)[1].split("data-task-row", 1)[0]
    assert "task-calendar-link has-comment" in row
    assert 'style="color: #c65a00"' in row
    assert f'href="{detail_url}"' in row


def test_general_task_card_requires_valid_title(app, auth_client):
    task_id = auth_client.post(
        "/tasks/save", data={"task_scope": "general", "text": "Исходное"}
    ).get_json()["task_id"]
    response = auth_client.post(
        f"/tasks/all/{task_id}", data={"text": "  ", "comment": "Не сохранять"}
    )
    assert response.status_code == 200
    with app.app_context():
        task = db.session.get(GeneralTask, task_id)
        assert task.text == "Исходное"
        assert task.comment == ""
