import re
from app.extensions import db
from app.models import Client


def test_multiple_labels_save_filter_clear_and_preserve_legacy(app, auth_client, sample_client):
    with app.app_context():
        client = db.session.get(Client, sample_client)
        client.color_label = 'yellow'
        db.session.commit()
        assert client.label_values == ['yellow']
    response = auth_client.post(f'/clients/{sample_client}/history', data={
        'history_text': '', 'contact_labels_present': '1', 'contact_labels': ['red', 'blue', 'red'],
    })
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Client, sample_client).label_values == ['red', 'blue']
    for color in ['red', 'blue']:
        assert f'href="/clients/{sample_client}"' in auth_client.get('/clients/?color_label=' + color).data.decode()
    assert f'href="/clients/{sample_client}"' not in auth_client.get('/clients/?color_label=yellow').data.decode()
    bad = auth_client.post(f'/clients/{sample_client}/history', data={'history_text': '', 'contact_labels_present': '1', 'contact_labels': ['bad']})
    assert bad.status_code == 400
    with app.app_context():
        assert db.session.get(Client, sample_client).label_values == ['red', 'blue']
    auth_client.post(f'/clients/{sample_client}/history', data={'history_text': '', 'contact_labels_present': '1'})
    with app.app_context():
        assert db.session.get(Client, sample_client).label_values == []


def test_no_name_field_no_trade_prefill_and_only_d_filter(app, auth_client, sample_client):
    with app.app_context():
        db.session.get(Client, sample_client).client_group = 'd'
        db.session.commit()
    page = auth_client.get('/clients/').data.decode()
    assert 'placeholder="ФИО"' not in page
    assert 'name="group" value="d"' in page
    assert 'client-segment-dialog' not in page
    card = auth_client.get(f'/clients/{sample_client}').data.decode()
    assert re.search(r'<textarea id="d-history-editor"[^>]*></textarea>', card)
    assert len(auth_client.get('/clients/?group=d').data) > 0
