import re

import pytest

from app.extensions import db
from app.models import Client


@pytest.mark.parametrize("important", [False, True])
@pytest.mark.parametrize("due_date", ["2020-10-20", "2030-10-20"])
def test_calendar_counter_dims_by_completion_and_restores_on_undo(auth_client, due_date, important):
    task = auth_client.post("/tasks/save", data={
        "text": "Дело", "due_date": due_date, "important": "1" if important else "0",
    }).get_json()

    def counter():
        page = auth_client.get(f"/calendar/?view=month&date={due_date}").data.decode()
        return re.search(r'<a class="(calendar-count[^\"]*)"[^>]*aria-label="Дела: (\d+)"', page).groups()

    assert 'is-completed' not in counter()[0]
    payload = {"task_id": task["task_id"], "text": "Дело", "due_date": due_date, "important": "1" if important else "0"}
    auth_client.post("/tasks/save", data={**payload, "completed": "1"})
    classes, count = counter()
    assert count == "1"
    assert 'is-completed' in classes
    assert ('calendar-count-important' in classes) is important
    year = auth_client.get(f"/calendar/?view=year&date={due_date}").data.decode()
    assert re.search(r'class="mini-day [^"]*is-completed[^\"]*"\s+href="/calendar/\?view=day&amp;date=' + due_date, year)
    # A mixed counter remains vivid while any unchecked work remains.
    auth_client.post("/tasks/save", data={"text": "Ещё дело", "due_date": due_date})
    assert counter()[1] == "2"
    assert 'is-completed' not in counter()[0]
    auth_client.post("/tasks/save", data={**payload, "completed": "0"})
    assert 'is-completed' not in counter()[0]


@pytest.mark.parametrize("group", ["none", "d", "v", "b", "r", "m", "p", "a", "k"])
def test_contact_palette_saves_in_every_group(app, auth_client, sample_client, group):
    with app.app_context():
        db.session.get(Client, sample_client).client_group = group
        db.session.commit()
    page = auth_client.get(f"/clients/{sample_client}").data.decode()
    assert 'name="client_color_label"' in page
    assert 'data-color-option="red"' in page
    assert 'Метка контакта' not in page
    assert 'class="button" href="#client-message"' in page
    response = auth_client.post(f"/clients/{sample_client}/history", data={
        "history_text": "", "client_color_label": "red",
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Client, sample_client).color_label == "red"
    if group == 'd':
        assert '<h2>Торговля</h2>' in page
        assert 'Комментарии Д' not in page
        assert 'data-history-record' not in page
        assert not re.search(r'\bdata-history-color(?:\s|>)', page)
        assert 'client-detail-compact' in page


def test_filter_palette_has_only_visible_swatches_and_short_names(auth_client):
    page = auth_client.get('/clients/').data.decode()
    assert '>Каналы</option>' in page
    assert '>Все каналы</option>' not in page
    assert '>Метки</span>' in page
    assert 'placeholder="ФИО"' in page
    menu = re.search(r'<div class="color-picker-menu"[^>]*>(.*?)</div>', page, re.S).group(1)
    for button in re.findall(r'<button\b.*?</button>', menu, re.S):
        text = re.sub(r'<[^>]+>', '', button).strip()
        assert text in {'', '×'}
    assert auth_client.get('/clients/?color_label=red').status_code == 200
