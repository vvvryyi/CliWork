import hmac

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user

from .extensions import login_manager


bp = Blueprint("auth", __name__, url_prefix="/auth")


class LocalUser(UserMixin):
    id = "local-user"


@login_manager.user_loader
def load_user(user_id):
    return LocalUser() if user_id == LocalUser.id else None


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
            login_user(LocalUser())
            next_url = request.args.get("next", "")
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("main.dashboard")
            return redirect(next_url)
        flash("Неверный логин или пароль.", "error")

    return render_template("auth/login.html")


@bp.post("/logout")
def logout():
    logout_user()
    flash("Вы вышли из CRM.", "success")
    return redirect(url_for("auth.login"))
