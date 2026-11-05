import json
from datetime import datetime

from app.clients import HISTORY_DIVIDER, build_history_text
from app.extensions import db
from app.models import CalendarEvent, Interaction


def test_selection_deletes_past_and_future_records_and_adds_event(app, auth_client, sample_client, monkeypatch):
    monkeypatch.setattr("app.clients.utcnow", lambda: datetime(2026, 11, 5, 12))
    with app.app_context():
        records = [Interaction(client_id=sample_client, text=text) for text in
                   ["261030 Прошедший звонок 261031", "261030 Будущий звонок 270831", "261030 Оставить"]]
        db.session.add_all(records)
        db.session.flush()
        past = CalendarEvent(client_id=sample_client, source_interaction_id=records[0].id,
                             title="Комментарий", origin="interaction", starts_at=datetime(2026, 10, 31, 6), status="overdue")
        future = CalendarEvent(client_id=sample_client, source_interaction_id=records[1].id,
                               title="Комментарий", origin="interaction", starts_at=datetime(2027, 8, 31, 6), status="planned")
        db.session.add_all([past, future])
        db.session.commit()
        ids = [record.id for record in records]
        past_id = past.id
        # A selection deleted two complete records, including both boundaries.
        sections = ["", "", records[2].text + HISTORY_DIVIDER, "261105 Новый звонок 271201"]
    response = auth_client.post(f"/clients/{sample_client}/history", data={
        "history_ids": ",".join(map(str, ids)), "history_text": "".join(sections),
        "history_sections": json.dumps(sections),
    })
    assert response.status_code == 302
    with app.app_context():
        past = db.session.get(CalendarEvent, past_id)
        assert past.source_interaction_id is None
        assert past.comment == "Прошедший звонок 261031"
        assert past.status in {"overdue", "completed"}
        assert db.session.scalar(db.select(CalendarEvent).where(
            CalendarEvent.starts_at == datetime(2027, 8, 31, 6))) is None
        assert db.session.get(Interaction, ids[0]) is None
        assert db.session.get(Interaction, ids[1]) is None
        assert db.session.get(Interaction, ids[2]).text == "261030 Оставить"
        new = db.session.scalar(db.select(Interaction).where(Interaction.id > ids[-1]))
        assert new.calendar_event.starts_at == datetime(2027, 12, 1, 6)


def test_deleting_planning_line_keeps_past_event_snapshot(app, auth_client, sample_client, monkeypatch):
    monkeypatch.setattr("app.clients.utcnow", lambda: datetime(2026, 11, 5, 12))
    with app.app_context():
        record = Interaction(client_id=sample_client, text="261030 Заметка\nПозвонить 261031")
        db.session.add(record)
        db.session.flush()
        event = CalendarEvent(client_id=sample_client, source_interaction_id=record.id,
                              starts_at=datetime(2026, 10, 31, 6), status="completed")
        db.session.add(event)
        db.session.commit()
        record_id, event_id = record.id, event.id
        text = build_history_text([record], datetime(2026, 11, 5)).replace("\nПозвонить 261031", "")
    response = auth_client.post(f"/clients/{sample_client}/history", data={
        "history_ids": str(record_id), "history_text": text,
    })
    assert response.status_code == 302
    with app.app_context():
        event = db.session.get(CalendarEvent, event_id)
        assert event.status == "completed"
        assert event.source_interaction_id is None
        assert event.comment == "Заметка\nПозвонить 261031"


def test_sections_cannot_silently_replace_submitted_text(auth_client, sample_client):
    response = auth_client.post(f"/clients/{sample_client}/history", data={
        "history_ids": "", "history_text": "Текст", "history_sections": '["Другой текст"]',
    })
    assert response.status_code == 400
