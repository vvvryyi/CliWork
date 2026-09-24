import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    CRM_USERNAME = os.getenv("CRM_USERNAME", "")
    CRM_PASSWORD = os.getenv("CRM_PASSWORD", "")
    CRM_TIMEZONE = os.getenv("CRM_TIMEZONE", "Europe/Moscow")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'instance' / 'crm.sqlite3').as_posix()}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TRUST_PROXY_HEADERS = env_flag("TRUST_PROXY_HEADERS")
    SESSION_COOKIE_SECURE = env_flag("SESSION_COOKIE_SECURE")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER",
        str(BASE_DIR / "instance" / "uploads"),
    )
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 20 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "txt",
        "csv",
        "jpg",
        "jpeg",
        "png",
        "webp",
        "heic",
        "heif",
        "zip",
    }
    ICLOUD_CALDAV_URL = os.getenv("ICLOUD_CALDAV_URL", "https://caldav.icloud.com/")
    ICLOUD_USERNAME = os.getenv("ICLOUD_USERNAME", "")
    ICLOUD_APP_PASSWORD = os.getenv("ICLOUD_APP_PASSWORD", "")
    ICLOUD_CALENDAR_NAME = os.getenv("ICLOUD_CALENDAR_NAME", "")
    WTF_CSRF_TIME_LIMIT = None
