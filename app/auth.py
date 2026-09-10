import hmac
import time

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user

from .extensions import db, login_manager
from .models import AppSetting
from .totp import verify_code


bp = Blueprint("auth", __name__, url_prefix="/auth")


class LocalUser(UserMixin):
    id = "local-user"


@login_manager.user_loader
def load_user(user_id):
    return LocalUser() if user_id == LocalUser.id else None


def get_totp_secret():
    setting = db.session.get(AppSetting, "totp_secret")
    return setting.value if setting else ""


def _safe_next_url(value):
    if not value.startswith("/") or value.startswith("//"):
        return url_for("main.dashboard")
    return value


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        expected_username = current_app.config["CRM_USERNAME"]
        expected_password = current_app.config["CRM_PASSWORD"]
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid = (
            bool(expected_username)
            and bool(expected_password)
            and hmac.compare_digest(username, expected_username)
            and hmac.compare_digest(password, expected_password)
        )
        if valid:
            next_url = _safe_next_url(request.args.get("next", ""))
            if get_totp_secret():
                session.clear()
                session["pending_2fa"] = True
                session["pending_2fa_started"] = int(time.time())
                session["pending_2fa_next"] = next_url
                return redirect(url_for("auth.verify_2fa"))
            login_user(LocalUser())
            return redirect(next_url)
        flash("Неверный логин или пароль.", "error")

    return render_template("auth/login.html")


@bp.route("/2fa", methods=["GET", "POST"])
def verify_2fa():
    started_at = session.get("pending_2fa_started", 0)
    if not session.get("pending_2fa") or time.time() - started_at > 300:
        session.clear()
        flash("Сеанс подтверждения истёк. Войдите ещё раз.", "error")
        return redirect(url_for("auth.login"))

    secret = get_totp_secret()
    if not secret:
        session.clear()
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        counter = verify_code(secret, request.form.get("code", ""))
        last_setting = db.session.get(AppSetting, "totp_last_counter")
        last_counter = int(last_setting.value) if last_setting else -1
        if counter is not None and counter > last_counter:
            if last_setting:
                last_setting.value = str(counter)
            else:
                db.session.add(AppSetting(key="totp_last_counter", value=str(counter)))
            db.session.commit()
            next_url = _safe_next_url(session.get("pending_2fa_next", ""))
            session.clear()
            login_user(LocalUser())
            return redirect(next_url)

        attempts = session.get("pending_2fa_attempts", 0) + 1
        session["pending_2fa_attempts"] = attempts
        if attempts >= 5:
            session.clear()
            flash("Слишком много неверных кодов. Войдите заново.", "error")
            return redirect(url_for("auth.login"))
        flash("Неверный или уже использованный код.", "error")

    return render_template("auth/verify_2fa.html")


@bp.post("/logout")
def logout():
    logout_user()
    flash("Вы вышли из CRM.", "success")
    return redirect(url_for("auth.login"))
