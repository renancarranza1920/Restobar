from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "web.login"
login_manager.refresh_view = "web.login"
login_manager.login_message = "Inicia sesion para continuar."
login_manager.login_message_category = "error"
login_manager.needs_refresh_message = (
    "Confirma tu contrasena para entrar a esta seccion protegida."
)
login_manager.needs_refresh_message_category = "info"
login_manager.session_protection = "strong"
