import os

from flask import Flask

from .config import BASE_DIR, Config, INSTANCE_DIR
from .extensions import db, login_manager, csrf, migrate
from . import models  # noqa: F401  (registriert Models + user_loader)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from .cli import register_cli
    from .utils import user_plan_days

    register_cli(app)
    app.add_template_global(user_plan_days, "user_plan_days")

    with app.app_context():
        # Schema per Migrationen (migrations/ existiert) — sonst Dev-Fallback create_all
        if not os.path.isdir(os.path.join(BASE_DIR, "migrations")):
            db.create_all()

    return app
