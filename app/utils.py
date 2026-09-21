import calendar
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from werkzeug.utils import secure_filename

from .extensions import db
from .models import AppSetting, Attachment, CalendarEvent, utcnow


CHANNEL_LABELS = {
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "max": "MAX",
    "instagram": "Instagram",
    "facebook": "Facebook",
}

STATUS_LABELS = {
    "planned": "Запланирован",
    "overdue": "Просрочен",
    "completed": "Выполнен",
    "rescheduled": "Перенесён",
    "cancelled": "Отменён",
}

EVENT_TYPE_LABELS = {
    "call": "Звонок",
    "meeting": "Встреча",
    "task": "Дело",
    "documents": "Документы",
    "other": "Другое",
}

PLANNING_START_YEAR = 2020
PLANNING_END_YEAR = 2031
OPEN_EVENT_STATUSES = ("planned", "overdue")
PLANNING_SUFFIX = re.compile(
    r"(?:^|\s)(?P<date>\d{6})(?:\s+(?:в\s*)?(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d))?(?P<important>!)?\s*$"
)
INTERACTION_LEADING_DATE = re.compile(r"^(?P<date>\d{6})(?:\s+|$)")


def parse_planning_details(text):
    """Return (local datetime, suffix_found, important) for a trailing date."""
    match = PLANNING_SUFFIX.search(text or "")
    if not match:
        return None, False, False
    try:
        planned = datetime.strptime(match.group("date"), "%y%m%d")
    except ValueError:
        return None, True, bool(match.group("important"))
    if not PLANNING_START_YEAR <= planned.year <= PLANNING_END_YEAR:
        return None, True, bool(match.group("important"))
    hour = int(match.group("hour") or 9)
    minute = int(match.group("minute") or 0)
    return (
        planned.replace(hour=hour, minute=minute),
        True,
        bool(match.group("important")),
    )


def parse_planning_suffix(text):
    """Backward-compatible parser returning only datetime and suffix presence."""
    planned, suffix_found, _ = parse_planning_details(text)
    return planned, suffix_found


def interaction_text_body(text):
    """Return record text without its automatic leading date."""
    cleaned = (text or "").strip()
    match = INTERACTION_LEADING_DATE.match(cleaned)
    return cleaned[match.end():].lstrip() if match else cleaned


def normalize_interaction_text(text, now=None):
    """Show today's date at the start without persisting it until submit."""
    cleaned = (text or "").strip()
    local_now = utc_naive_to_local(now or utcnow())
    current_date = local_now.strftime("%y%m%d")
    if not cleaned:
        return f"{current_date} "

    leading_match = INTERACTION_LEADING_DATE.match(cleaned)
    body = cleaned[leading_match.end():].lstrip() if leading_match else cleaned
    return f"{current_date} {body}" if body else f"{current_date} "


def validate_mmdd(value):
    """Normalize an MMDD reminder value or raise a user-facing error."""
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if not re.fullmatch(r"\d{4}", cleaned):
        raise ValueError("Дату квартального напоминания укажите в формате ММДД.")
    try:
        date(2000, int(cleaned[:2]), int(cleaned[2:]))
    except ValueError as error:
        raise ValueError("Укажите существующую дату в формате ММДД.") from error
    return cleaned


def add_months(day, months, preferred_day=None):
    month_index = day.year * 12 + day.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    target_day = preferred_day or day.day
    return date(year, month, min(target_day, calendar.monthrange(year, month)[1]))


def regenerate_quarterly_events(client, after_date=None):
    """Rebuild open quarterly reminders from the anchor through 2031."""
    existing = db.session.scalars(
        db.select(CalendarEvent).where(
            CalendarEvent.client_id == client.id,
            CalendarEvent.origin == "quarterly",
            CalendarEvent.status.in_(OPEN_EVENT_STATUSES),
        )
    ).all()
    for event in existing:
        db.session.delete(event)

    if (
        client.is_archived
        or client.client_group != "a"
        or not client.quarterly_reminder_mmdd
    ):
        return 0

    local_today = utc_naive_to_local(utcnow()).date()
    cutoff = after_date if after_date is not None else local_today - timedelta(days=1)
    month = int(client.quarterly_reminder_mmdd[:2])
    day = int(client.quarterly_reminder_mmdd[2:])
    first = date(local_today.year, month, min(day, calendar.monthrange(local_today.year, month)[1]))
    while first <= cutoff:
        first = add_months(first, 3, day)

    created = 0
    reminder_day = first
    while reminder_day <= date(PLANNING_END_YEAR, 12, 31):
        db.session.add(
            CalendarEvent(
                client_id=client.id,
                title="Квартальный контакт",
                origin="quarterly",
                event_type="task",
                starts_at=local_to_utc_naive(f"{reminder_day.isoformat()}T09:00"),
                status="planned",
            )
        )
        created += 1
        reminder_day = add_months(reminder_day, 3, day)
    return created


def complete_due_quarterly_events(client_id, now=None):
    current_time = now or utcnow()
    return db.session.execute(
        db.update(CalendarEvent)
        .where(
            CalendarEvent.client_id == client_id,
            CalendarEvent.origin == "quarterly",
            CalendarEvent.status.in_(OPEN_EVENT_STATUSES),
            CalendarEvent.starts_at <= current_time,
        )
        .values(status="completed", completed_at=current_time)
    ).rowcount or 0


def get_timezone_name():
    setting = db.session.get(AppSetting, "timezone")
    return setting.value if setting else current_app.config["CRM_TIMEZONE"]


def get_timezone():
    try:
        return ZoneInfo(get_timezone_name())
    except ZoneInfoNotFoundError:
        return timezone.utc


def local_to_utc_naive(value):
    if not value:
        return None
    local_datetime = datetime.fromisoformat(value)
    localized = local_datetime.replace(tzinfo=get_timezone())
    return localized.astimezone(timezone.utc).replace(tzinfo=None)


def utc_naive_to_local(value):
    if value is None:
        return None
    aware_utc = value.replace(tzinfo=timezone.utc)
    return aware_utc.astimezone(get_timezone())


def synchronize_event_statuses(now=None):
    """Persist the overdue state for events whose scheduled time has passed."""
    current_time = now or utcnow()
    result = db.session.execute(
        db.update(CalendarEvent)
        .where(
            CalendarEvent.status == "planned",
            CalendarEvent.starts_at < current_time,
        )
        .values(status="overdue")
    )
    if result.rowcount:
        db.session.commit()
    return result.rowcount or 0


def complete_client_events(client_id, interaction):
    """Complete open note-generated events when a newer client record appears."""
    return db.session.execute(
        db.update(CalendarEvent)
        .where(
            CalendarEvent.client_id == client_id,
            CalendarEvent.origin == "interaction",
            CalendarEvent.status.in_(OPEN_EVENT_STATUSES),
        )
        .values(
            status="completed",
            completed_at=interaction.created_at,
            completed_by_interaction_id=interaction.id,
        )
    ).rowcount or 0


def save_uploads(files, client_id, interaction_id=None):
    saved = []
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    upload_root.mkdir(parents=True, exist_ok=True)

    validated = []
    for uploaded in files:
        if not uploaded or not uploaded.filename:
            continue
        safe_name = secure_filename(uploaded.filename)
        if not safe_name or "." not in safe_name:
            raise ValueError("Файл должен иметь допустимое имя и расширение.")
        extension = safe_name.rsplit(".", 1)[1].lower()
        if extension not in current_app.config["ALLOWED_EXTENSIONS"]:
            raise ValueError(f"Формат .{extension} не разрешён.")
        validated.append((uploaded, extension))

    for uploaded, extension in validated:
        stored_name = f"{uuid4().hex}.{extension}"
        target = upload_root / stored_name
        uploaded.save(target)
        attachment = Attachment(
            client_id=client_id,
            interaction_id=interaction_id,
            original_name=uploaded.filename[:255],
            stored_name=stored_name,
            file_path=str(target),
            mime_type=uploaded.mimetype or "",
            file_size=target.stat().st_size,
        )
        db.session.add(attachment)
        saved.append(attachment)
    return saved


def build_channel_url(client, channel, message):
    contact = client.channel_contact(channel).strip()
    encoded = quote(message)

    if channel == "whatsapp":
        digits = "".join(character for character in contact if character.isdigit())
        return f"https://wa.me/{digits}?text={encoded}" if digits else ""
    if channel == "telegram":
        username = contact.lstrip("@").strip()
        return f"https://t.me/{username}" if username else ""
    if channel == "instagram":
        username = contact.lstrip("@").strip().rstrip("/")
        if username.startswith("http"):
            return username
        return f"https://www.instagram.com/{username}/" if username else ""
    if channel == "facebook":
        return contact if contact.startswith("http") else ""
    if channel == "max":
        return contact if contact.startswith(("http://", "https://")) else ""
    return ""


def month_grid(year, month):
    cal = calendar.Calendar(firstweekday=0)
    return list(cal.monthdatescalendar(year, month))
