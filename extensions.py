"""
extensions.py — Flask extension instances (avoids circular imports).
Import these into app.py and models.py instead of creating new instances.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

# Redirect unauthenticated users to the login page
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to access the dashboard."
login_manager.login_message_category = "warning"
