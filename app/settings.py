from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .extensions import db
from .models import AppSetting
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
    return render_template("settings/index.html", timezone_name=get_timezone_name())
