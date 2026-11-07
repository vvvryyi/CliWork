from .ownership import get_setting, make_setting
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user

from .calendar_sync import is_configured, sync_icloud_calendar
from .extensions import db
from .models import AppSetting
from .totp import generate_secret, provisioning_uri, verify_code
from .utils import get_timezone_name


bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        timezone_name = request.form.get("timezone", "").strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            flash("Укажите корректный часовой пояс, например Europe/Moscow.", "error")
        else:
            setting = get_setting("timezone")
            if setting:
                setting.value = timezone_name
            else:
                db.session.add(make_setting(key="timezone", value=timezone_name))
            db.session.commit()
            request.environ.pop("crm.timezone", None)
            flash("Настройки сохранены.", "success")
            return redirect(url_for("settings.index"))
    totp_secret = get_setting("totp_secret")
    last_sync = get_setting("icloud_last_sync")
    icloud_fields = {
        "ICLOUD_USERNAME": "Apple ID",
        "ICLOUD_APP_PASSWORD": "пароль приложения",
        "ICLOUD_CALENDAR_NAME": "название календаря",
    }
    return render_template(
        "settings/index.html",
        timezone_name=get_timezone_name(),
        two_factor_enabled=bool(totp_secret),
        icloud_configured=is_configured(),
        icloud_calendar_name=current_app.config.get("ICLOUD_CALENDAR_NAME", ""),
        icloud_last_sync=last_sync.value if last_sync else "",
        icloud_missing=[
            label
            for key, label in icloud_fields.items()
            if not current_app.config.get(key)
        ],
    )


@bp.post("/icloud/sync")
@login_required
def sync_icloud():
    try:
        result = sync_icloud_calendar()
    except Exception as error:
        current_app.logger.exception("iCloud calendar sync failed")
        message = str(error) if isinstance(error, RuntimeError) else "не удалось подключиться к iCloud."
        flash(f"Синхронизация не выполнена: {message}", "error")
    else:
        flash(
            f"Календарь синхронизирован: "
            f"из iPhone — {result['pulled']}, в iPhone — {result['pushed']}, "
            f"удалено — {result['deleted']}.",
            "success",
        )
    return redirect(url_for("settings.index"))


@bp.route("/2fa/setup", methods=["GET", "POST"])
@login_required
def setup_2fa():
    if get_setting("totp_secret"):
        flash("Двухфакторная аутентификация уже включена.", "error")
        return redirect(url_for("settings.index"))

    pending = get_setting("totp_pending_secret")
    created = get_setting("totp_pending_created")
    if not pending or not created or time.time() - float(created.value) > 600:
        secret = generate_secret()
        if pending:
            pending.value = secret
        else:
            pending = make_setting(key="totp_pending_secret", value=secret)
            db.session.add(pending)
        if created:
            created.value = str(time.time())
        else:
            db.session.add(make_setting(key="totp_pending_created", value=str(time.time())))
        db.session.commit()

    if request.method == "POST":
        counter = verify_code(pending.value, request.form.get("code", ""))
        if counter is None:
            flash("Код не подошёл. Проверьте время на устройстве и попробуйте снова.", "error")
        else:
            db.session.add(make_setting(key="totp_secret", value=pending.value))
            db.session.add(make_setting(key="totp_last_counter", value=str(counter)))
            db.session.delete(pending)
            db.session.delete(created)
            db.session.commit()
            flash("Двухфакторная аутентификация включена.", "success")
            return redirect(url_for("settings.index"))

    uri = provisioning_uri(
        pending.value,
        getattr(current_user, "email", current_app.config["CRM_USERNAME"]),
        "WorkSpace",
    )
    return render_template("settings/setup_2fa.html", secret=pending.value, uri=uri)


@bp.post("/2fa/disable")
@login_required
def disable_2fa():
    secret = get_setting("totp_secret")
    if not secret:
        return redirect(url_for("settings.index"))
    if verify_code(secret.value, request.form.get("code", "")) is None:
        flash("Введите действующий код, чтобы отключить 2FA.", "error")
        return redirect(url_for("settings.index"))
    for key in ("totp_secret", "totp_last_counter", "totp_pending_secret", "totp_pending_created"):
        setting = get_setting(key)
        if setting:
            db.session.delete(setting)
    db.session.commit()
    flash("Двухфакторная аутентификация отключена.", "success")
    return redirect(url_for("settings.index"))
