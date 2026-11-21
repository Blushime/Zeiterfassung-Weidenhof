import os

from flask import Flask

from .config import Config, INSTANCE_DIR
from .extensions import db, login_manager, csrf
from . import models  # noqa: F401  (registriert Models + user_loader)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from .cli import register_cli

    register_cli(app)

    with app.app_context():
        db.create_all()

    return app
