import re

import pytest

from app.extensions import db
from app.models import Client


def test_card_header_has_four_controls(auth_client, sample_client):
    page = auth_client.get(f'/clients/{sample_client}').data.decode()
    actions = page.split('class="heading-actions client-card-actions"', 1)[1].split('</div>', 1)[0]
    for text in ('Без группы', 'Написать', 'Редактировать', 'В архив'):
        assert text in actions
    for text in ('Звонок', 'Встреча', 'Рассылка'):
        assert text not in actions
    assert re.search(r'<select[^>]*name="group"', actions)
    assert 'data-client-group' in actions
    assert 'data-client-group-status' in page
    assert '/static/css/style.css?v=22' in page
    assert '/static/js/app.js?v=22' in page


@pytest.mark.parametrize('group', ['none', 'd', 'v', 'b', 'r', 'm', 'p', 'a', 'k'])
def test_group_switch_saves_and_returns_card(app, auth_client, sample_client, group):
    response = auth_client.post(f'/clients/{sample_client}/group', data={'group': group}, headers={'Accept': 'application/json'})
    assert response.status_code == 200
    assert response.get_json() == {'group': group, 'url': f'/clients/{sample_client}'}
    with app.app_context():
        assert db.session.get(Client, sample_client).client_group == group
    card = auth_client.get(response.get_json()['url']).data.decode()
    assert f'value="{group}" selected' in card


def test_group_rejects_unknown_value_without_changing_client(app, auth_client, sample_client):
    response = auth_client.post(f'/clients/{sample_client}/group', data={'group': 'unknown'}, headers={'Accept': 'application/json'})
    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(Client, sample_client).client_group == 'none'


def test_contacts_list_actions_have_same_button_style(auth_client):
    page = auth_client.get('/clients/').data.decode()
    actions = page.split('class="heading-actions contacts-list-actions"', 1)[1].split('</div>', 1)[0]
    assert re.findall(r'class="([^"]+)"', actions) == ['button', 'button', 'button']
    assert 'Поиск по запискам' not in actions
    assert 'Поиск' in actions and 'Архив' in actions and '+ Новый клиент' in actions
