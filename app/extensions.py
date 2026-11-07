from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session
from flask_wtf.csrf import CSRFProtect


class WorkspaceSession(Session):
    def get(self, entity, ident, **kwargs):
        result = super().get(entity, ident, **kwargs)
        from .models import OwnedMixin
        from .ownership import owner_id
        if isinstance(result, OwnedMixin) and result.owner_id != owner_id():
            return None
        return result


db = SQLAlchemy(session_options={"class_": WorkspaceSession})
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()

