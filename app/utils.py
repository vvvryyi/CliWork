import calendar
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from werkzeug.utils import secure_filename

from .extensions import db
from .models import AppSetting, Attachment


CHANNEL_LABELS = {
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "max": "MAX",
    "instagram": "Instagram",
    "facebook": "Facebook",
}

STATUS_LABELS = {
    "planned": "Запланирован",
    "completed": "Выполнен",
    "rescheduled": "Перенесён",
    "cancelled": "Отменён",
}

EVENT_TYPE_LABELS = {
    "call": "Звонок",
    "meeting": "Встреча",
    "task": "Задача",
    "documents": "Документы",
    "other": "Другое",
}

PLANNING_START_YEAR = 2020
PLANNING_END_YEAR = 2031
PLANNING_SUFFIX = re.compile(
    r"(?:^|\s)(?P<date>\d{6})(?:\s+(?:в\s*)?(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d))?\s*$"
)


def parse_planning_suffix(text):
    """Return (local datetime, suffix_found) for a trailing YYMMDD date."""
    match = PLANNING_SUFFIX.search(text or "")
    if not match:
        return None, False
    try:
        planned = datetime.strptime(match.group("date"), "%y%m%d")
    except ValueError:
        return None, True
    if not PLANNING_START_YEAR <= planned.year <= PLANNING_END_YEAR:
        return None, True
    hour = int(match.group("hour") or 9)
    minute = int(match.group("minute") or 0)
    return planned.replace(hour=hour, minute=minute), True


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
