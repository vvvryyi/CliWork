from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import BASE_DIR, Config
from .extensions import csrf, db, login_manager, migrate


def create_app(test_config=None):
    load_dotenv(BASE_DIR / ".env")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    if app.config["TRUST_PROXY_HEADERS"]:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1,
        )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY не задан в .env")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Войдите, чтобы открыть CRM."
    login_manager.login_message_category = "error"

    from . import models
    from .auth import bp as auth_bp
    from .calendar_routes import bp as calendar_bp
    from .clients import bp as clients_bp
    from .main import bp as main_bp
    from .messaging import bp as messaging_bp
    from .settings import bp as settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(messaging_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(settings_bp)

    from .utils import (
        CHANNEL_LABELS,
        EVENT_TYPE_LABELS,
        STATUS_LABELS,
        get_timezone_name,
        utc_naive_to_local,
    )

    @app.template_filter("local_datetime")
    def local_datetime(value, pattern="%d.%m.%Y %H:%M"):
        local = utc_naive_to_local(value)
        return local.strftime(pattern) if local else ""

    @app.template_filter("history_date")
    def history_date(value):
        local = utc_naive_to_local(value)
        return local.strftime("%y%m%d") if local else ""

    @app.context_processor
    def template_globals():
        return {
            "channel_labels": CHANNEL_LABELS,
            "status_labels": STATUS_LABELS,
            "event_type_labels": EVENT_TYPE_LABELS,
            "current_timezone": get_timezone_name,
        }

    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        print("База данных создана.")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/service-worker.js")
    def service_worker():
        response = app.send_static_file("service-worker.js")
        response.headers["Cache-Control"] = "no-cache"
        return response

    return app
