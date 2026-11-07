from flask import has_request_context, session, abort
from flask_login import current_user
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from .extensions import db
from .models import OwnedMixin, AppSetting, Client, Interaction, CalendarEvent, DailyTask, GeneralTask


def owner_id():
    if has_request_context():
        return session.get("_user_id") or session.get("pending_2fa_user", "local-user")
    return 'local-user'


def setting_key(key):
    owner = owner_id()
    return key if owner == 'local-user' else f'{owner}:{key}'


def get_setting(key):
    return db.session.get(AppSetting, setting_key(key))


def make_setting(key, value):
    return AppSetting(key=setting_key(key), value=value)


@event.listens_for(Session, 'do_orm_execute')
def scope_queries(state):
    if state.is_select or state.is_update or state.is_delete:
        owner = owner_id()
        state.statement = state.statement.options(with_loader_criteria(
            OwnedMixin, lambda model: model.owner_id == owner, include_aliases=True
        ))


@event.listens_for(Session, 'before_flush')
def scope_writes(session_, context, instances):
    if not has_request_context():
        return
    owner = owner_id()
    for obj in set(session_.new) | set(session_.dirty) | set(session_.deleted):
        if not isinstance(obj, OwnedMixin):
            continue
        if obj in session_.new:
            obj.owner_id = owner
        elif obj.owner_id != owner:
            abort(404)
        for field, model in [('client_id', Client), ('interaction_id', Interaction),
                             ('source_interaction_id', Interaction), ('completed_by_interaction_id', Interaction),
                             ('calendar_event_id', CalendarEvent)]:
            value = getattr(obj, field, None)
            if value is not None and session_.get(model, value) is None:
                abort(404)
