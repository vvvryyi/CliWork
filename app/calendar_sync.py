import hashlib
from datetime import date, datetime, time, timezone
from uuid import uuid4

from flask import current_app

from .extensions import db
from .models import AppSetting, CalendarEvent, utcnow
from .task_service import delete_event_and_task, sync_task_from_event
from .utils import get_timezone, local_to_utc_naive


def is_configured():
    return all(
        current_app.config.get(key)
        for key in ("ICLOUD_USERNAME", "ICLOUD_APP_PASSWORD", "ICLOUD_CALENDAR_NAME")
    )


def event_fingerprint(event):
    payload = "|".join(
        (
            event.title or "",
            event.starts_at.isoformat() if event.starts_at else "",
            event.ends_at.isoformat() if event.ends_at else "",
            event.comment or "",
            event.status or "",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _remote_datetime(value, all_day_end=False):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return local_to_utc_naive(value.isoformat(timespec="minutes"))
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    if isinstance(value, date):
        local_value = datetime.combine(value, time.min if all_day_end else time(hour=9))
        return local_value.replace(tzinfo=get_timezone()).astimezone(timezone.utc).replace(tzinfo=None)
    return None


def _component_value(component, name, default=""):
    value = component.get(name)
    return str(value) if value is not None else default


def _apply_remote_event(local_event, remote_event, synced_at):
    component = remote_event.component
    starts_at = _remote_datetime(component.decoded("dtstart"))
    if not starts_at:
        return False
    ends_at = None
    if component.get("dtend") is not None:
        ends_at = _remote_datetime(component.decoded("dtend"), all_day_end=True)
    local_event.title = _component_value(component, "summary", "Встреча")[:250]
    local_event.comment = _component_value(component, "description")
    local_event.starts_at = starts_at
    local_event.ends_at = ends_at
    local_event.status = "cancelled" if _component_value(component, "status").upper() == "CANCELLED" else "planned"
    local_event.external_uid = _component_value(component, "uid")[:255]
    local_event.external_href = str(remote_event.url or "")[:1000]
    local_event.external_etag = str(remote_event.etag or "")[:255]
    local_event.last_synced_at = synced_at
    local_event.external_hash = event_fingerprint(local_event)
    return True


def _event_ical(event):
    from icalendar import Calendar, Event

    calendar = Calendar()
    calendar.add("prodid", "-//Personal CRM//Calendar Sync//RU")
    calendar.add("version", "2.0")
    component = Event()
    component.add("uid", event.external_uid)
    component.add("dtstamp", datetime.now(timezone.utc))
    component.add("summary", event.title or (event.client.full_name if event.client else "Дело CRM"))
    component.add("dtstart", event.starts_at.replace(tzinfo=timezone.utc))
    if event.ends_at:
        component.add("dtend", event.ends_at.replace(tzinfo=timezone.utc))
    if event.comment:
        component.add("description", event.comment)
    if event.status == "cancelled":
        component.add("status", "CANCELLED")
    calendar.add_component(component)
    return calendar.to_ical()


def sync_icloud_calendar():
    """Synchronize CRM events with one configured iCloud calendar."""
    if not is_configured():
        raise RuntimeError("Заполните ICLOUD_USERNAME, ICLOUD_APP_PASSWORD и ICLOUD_CALENDAR_NAME в .env.")

    from caldav import get_calendar

    synced_at = utcnow()
    pulled = 0
    pushed = 0
    deleted = 0
    with get_calendar(
        url=current_app.config["ICLOUD_CALDAV_URL"],
        username=current_app.config["ICLOUD_USERNAME"],
        password=current_app.config["ICLOUD_APP_PASSWORD"],
        calendar_name=current_app.config["ICLOUD_CALENDAR_NAME"],
        check_config_file=False,
        environment=False,
        raise_errors=True,
    ) as calendar:
        if calendar is None:
            raise RuntimeError("Календарь iCloud с указанным именем не найден.")

        remote_objects = calendar.get_events()
        remote_by_uid = {}
        for remote in remote_objects:
            try:
                uid = _component_value(remote.component, "uid")
            except Exception:
                continue
            if uid:
                remote_by_uid[uid] = remote

        local_by_uid = {
            event.external_uid: event
            for event in db.session.scalars(
                db.select(CalendarEvent).where(CalendarEvent.external_uid.is_not(None))
            ).all()
        }

        for uid, remote in remote_by_uid.items():
            local_event = local_by_uid.get(uid)
            if local_event is None:
                local_event = CalendarEvent(
                    origin="icloud",
                    event_type="meeting",
                    status="planned",
                    external_uid=uid[:255],
                )
                if _apply_remote_event(local_event, remote, synced_at):
                    db.session.add(local_event)
                    sync_task_from_event(local_event)
                    pulled += 1
                continue

            locally_changed = bool(
                local_event.external_hash
                and local_event.external_hash != event_fingerprint(local_event)
            )
            remote_changed = str(remote.etag or "") != local_event.external_etag
            if remote_changed and not locally_changed:
                if _apply_remote_event(local_event, remote, synced_at):
                    pulled += 1
            sync_task_from_event(local_event)

        db.session.flush()
        syncable = db.session.scalars(
            db.select(CalendarEvent).where(CalendarEvent.origin != "quarterly")
        ).all()
        for local_event in syncable:
            fingerprint = event_fingerprint(local_event)
            if (
                local_event.external_uid
                and local_event.external_uid not in remote_by_uid
                and local_event.external_hash == fingerprint
            ):
                if local_event.origin == "icloud":
                    delete_event_and_task(local_event)
                else:
                    local_event.status = "cancelled"
                    local_event.external_uid = None
                    local_event.external_href = ""
                    local_event.external_etag = ""
                    local_event.external_hash = ""
                deleted += 1
                continue

            if local_event.status in ("completed", "cancelled"):
                remote = remote_by_uid.get(local_event.external_uid)
                if remote is not None:
                    remote.delete()
                    deleted += 1
                local_event.external_uid = None
                local_event.external_href = ""
                local_event.external_etag = ""
                local_event.external_hash = ""
                local_event.last_synced_at = synced_at
                continue

            if not local_event.external_uid:
                local_event.external_uid = f"crm-{local_event.id}-{uuid4().hex}@personal-crm"

            remote = remote_by_uid.get(local_event.external_uid)
            if remote is not None and local_event.external_hash == fingerprint:
                continue

            ical = _event_ical(local_event)
            if remote is None:
                remote = calendar.add_event(ical=ical)
            else:
                remote.data = ical
                remote.save()
            local_event.external_href = str(remote.url or "")[:1000]
            local_event.external_etag = str(remote.etag or "")[:255]
            local_event.external_hash = fingerprint
            local_event.last_synced_at = synced_at
            remote_by_uid[local_event.external_uid] = remote
            pushed += 1

    setting = db.session.get(AppSetting, "icloud_last_sync")
    value = synced_at.isoformat(timespec="seconds")
    if setting:
        setting.value = value
    else:
        db.session.add(AppSetting(key="icloud_last_sync", value=value))
    db.session.commit()
    return {"pulled": pulled, "pushed": pushed, "deleted": deleted}
