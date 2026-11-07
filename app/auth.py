from .ownership import get_setting, make_setting
import hmac
import time

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user, login_required

from .extensions import db, login_manager
from .models import AppSetting, User
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from uuid import uuid4
from flask import abort
from .totp import verify_code


bp = Blueprint("auth", __name__, url_prefix="/auth")


class LocalUser(UserMixin):
    id = "local-user"

    @property
    def is_admin(self):
        return current_app.config["CRM_USERNAME"].strip().lower() == "da332381@gmail.com"


def secure_text_compare(value, expected):
    """Compare Unicode credentials in constant time using UTF-8 bytes."""
    return hmac.compare_digest(
        (value or "").encode("utf-8"),
        (expected or "").encode("utf-8"),
    )


@login_manager.user_loader
def load_user(user_id):
    return LocalUser() if user_id == LocalUser.id else db.session.get(User, user_id)


def get_totp_secret():
    setting = get_setting("totp_secret")
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
            and secure_text_compare(username, expected_username)
            and secure_text_compare(password, expected_password)
        )
        user = LocalUser() if valid else db.session.scalar(db.select(User).where(User.email == username.strip().lower()))
        if user and (valid or user.check_password(password)):
            session.clear()
            session["pending_2fa_user"] = user.get_id()
            next_url = _safe_next_url(request.args.get("next", ""))
            if get_totp_secret():
                session["pending_2fa"] = True
                session["pending_2fa_started"] = int(time.time())
                session["pending_2fa_next"] = next_url
                return redirect(url_for("auth.verify_2fa"))
            session.clear()
            login_user(user)
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
        last_setting = get_setting("totp_last_counter")
        last_counter = int(last_setting.value) if last_setting else -1
        if counter is not None and counter > last_counter:
            if last_setting:
                last_setting.value = str(counter)
            else:
                db.session.add(make_setting(key="totp_last_counter", value=str(counter)))
            db.session.commit()
            next_url = _safe_next_url(session.get("pending_2fa_next", ""))
            user = load_user(session.get("pending_2fa_user", "local-user"))
            session.clear()
            if user is None:
                return redirect(url_for("auth.login"))
            login_user(user)
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
    flash("Вы вышли из WorkSpace.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(email) > 200 or not email or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Введите корректный email.", "error")
        elif len(password) < 8 or len(password) > 256:
            flash("Пароль должен содержать от 8 до 256 символов.", "error")
        elif password != request.form.get("password_confirm", ""):
            flash("Пароли не совпадают.", "error")
        elif email == current_app.config["CRM_USERNAME"].strip().lower():
            flash("Этот email уже зарегистрирован.", "error")
        else:
            user = User(id=uuid4().hex, email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Этот email уже зарегистрирован.", "error")
            else:
                session.clear()
                login_user(user)
                return redirect(url_for("main.dashboard"))
    return render_template("auth/register.html")


@bp.get("/users")
@login_required
def users():
    if not current_user.is_admin:
        abort(403)
    accounts = db.session.scalars(db.select(User).order_by(User.created_at)).all()
    return render_template("auth/users.html", users=accounts, legacy_username=current_app.config["CRM_USERNAME"])
