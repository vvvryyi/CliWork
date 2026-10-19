from io import BytesIO
from pathlib import Path
import re

import pytest

from app.extensions import db
from app.models import Attachment, DailyTask


@pytest.mark.parametrize("filename", ["Презентация.pptx", "Документ.pdf", "Презентация.PPTX"])
def test_upload_requested_formats(app, auth_client, sample_client, filename):
    content = b"test attachment"
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={"history_text": "Файл", "files": (BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        attachment = db.session.scalar(db.select(Attachment))
        assert attachment.original_name == filename
        assert Path(attachment.file_path).read_bytes() == content
        attachment_id = attachment.id
    download = auth_client.get(f"/clients/attachments/{attachment_id}")
    assert download.status_code == 200
    assert download.data == content
    page = auth_client.get(f"/clients/{sample_client}").data.decode()
    accept = re.search(r'name="files" type="file" accept="([^"]+)"', page).group(1)
    assert {".pptx", ".pdf", ".xlsx"} <= set(accept.split(","))


def test_save_multiple_client_documents_without_text_returns_home(app, auth_client, sample_client):
    documents = {"Договор.pdf": b"pdf content", "Презентация.pptx": b"pptx content"}
    response = auth_client.post(
        f"/clients/{sample_client}/history",
        data={
            "history_text": "",
            "files": [(BytesIO(content), name) for name, content in documents.items()],
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    with app.app_context():
        attachments = db.session.scalars(db.select(Attachment)).all()
        assert len(attachments) == 2
        for attachment in attachments:
            assert attachment.client_id == sample_client
            assert Path(attachment.file_path).read_bytes() == documents[attachment.original_name]
    page = auth_client.get(f"/clients/{sample_client}").data.decode()
    for name in documents:
        assert name in page


def test_work_space_brand_and_contacts(auth_client):
    home = auth_client.get("/").data.decode()
    assert "<title>WorkSpace</title>" in home
    assert "<span>Контакты</span>" in home
    assert "<span>Клиенты</span>" not in home
    manifest = auth_client.get("/static/manifest.webmanifest").get_json()
    assert manifest["name"] == manifest["short_name"] == "WorkSpace"


def test_calendar_reuses_daily_and_general_editors(app, auth_client):
    daily = auth_client.post(
        "/tasks/save", data={"text": "Дело дня", "due_date": "2030-12-05"}
    ).get_json()
    general = auth_client.post(
        "/tasks/save",
        data={"task_scope": "general", "text": "Общее дело", "due_date": "2030-12-05", "comment": "Детали"},
    ).get_json()
    page = auth_client.get("/calendar/?view=day&date=2030-12-05").data.decode()
    assert page.count("data-task-editor") == 2
    assert 'data-task-scope="daily"' in page
    assert 'data-task-scope="general"' in page
    assert page.count("data-task-check") == page.count("data-task-remove") == 2
    assert 'data-allow-create="0"' in page
    assert 'class="task-line is-new"' not in page
    for task in (daily, general):
        assert f'href="{task["calendar_url"]}"' in page
        assert auth_client.get(task["calendar_url"]).status_code == 200
    assert "has-comment" in page

    # Calendar changes use each task's own scope, even when IDs overlap.
    completed = auth_client.post(
        "/tasks/save", data={"task_id": daily["task_id"], "text": "Дело дня", "due_date": "2030-12-05", "completed": "1"}
    )
    assert completed.get_json()["completed"] is True
    page = auth_client.get("/calendar/?view=day&date=2030-12-05").data.decode()
    assert "Дело дня" not in page
    assert "Общее дело" in page
    with app.app_context():
        assert db.session.get(DailyTask, daily["task_id"]).is_completed


def test_overdue_tasks_keep_original_date_and_arrow(auth_client):
    task = auth_client.post(
        "/tasks/save", data={"text": "Просроченное", "due_date": "2020-01-02"}
    ).get_json()
    page = auth_client.get("/calendar/?view=overdue").data.decode()
    assert 'data-task-scope="daily"' in page
    assert 'data-due-date="2020-01-02"' in page
    assert "02.01.2020 · Просрочено" in page
    assert f'href="{task["calendar_url"]}"' in page
