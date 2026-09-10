import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

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
            setting = db.session.get(AppSetting, "timezone")
            if setting:
                setting.value = timezone_name
            else:
                db.session.add(AppSetting(key="timezone", value=timezone_name))
            db.session.commit()
            flash("Настройки сохранены.", "success")
            return redirect(url_for("settings.index"))
    totp_secret = db.session.get(AppSetting, "totp_secret")
    return render_template(
        "settings/index.html",
        timezone_name=get_timezone_name(),
        two_factor_enabled=bool(totp_secret),
    )


@bp.route("/2fa/setup", methods=["GET", "POST"])
@login_required
def setup_2fa():
    if db.session.get(AppSetting, "totp_secret"):
        flash("Двухфакторная аутентификация уже включена.", "error")
        return redirect(url_for("settings.index"))

    pending = db.session.get(AppSetting, "totp_pending_secret")
    created = db.session.get(AppSetting, "totp_pending_created")
    if not pending or not created or time.time() - float(created.value) > 600:
        secret = generate_secret()
        if pending:
            pending.value = secret
        else:
            pending = AppSetting(key="totp_pending_secret", value=secret)
            db.session.add(pending)
        if created:
            created.value = str(time.time())
        else:
            db.session.add(AppSetting(key="totp_pending_created", value=str(time.time())))
        db.session.commit()

    if request.method == "POST":
        counter = verify_code(pending.value, request.form.get("code", ""))
        if counter is None:
            flash("Код не подошёл. Проверьте время на устройстве и попробуйте снова.", "error")
        else:
            db.session.add(AppSetting(key="totp_secret", value=pending.value))
            db.session.add(AppSetting(key="totp_last_counter", value=str(counter)))
            db.session.delete(pending)
            db.session.delete(created)
            db.session.commit()
            flash("Двухфакторная аутентификация включена.", "success")
            return redirect(url_for("settings.index"))

    uri = provisioning_uri(
        pending.value,
        current_app.config["CRM_USERNAME"],
        "Персональная CRM",
    )
    return render_template("settings/setup_2fa.html", secret=pending.value, uri=uri)


@bp.post("/2fa/disable")
@login_required
def disable_2fa():
    secret = db.session.get(AppSetting, "totp_secret")
    if not secret:
        return redirect(url_for("settings.index"))
    if verify_code(secret.value, request.form.get("code", "")) is None:
        flash("Введите действующий код, чтобы отключить 2FA.", "error")
        return redirect(url_for("settings.index"))
    for key in ("totp_secret", "totp_last_counter", "totp_pending_secret", "totp_pending_created"):
        setting = db.session.get(AppSetting, key)
        if setting:
            db.session.delete(setting)
    db.session.commit()
    flash("Двухфакторная аутентификация отключена.", "success")
    return redirect(url_for("settings.index"))
