import tempfile

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    UPLOAD_FOLDER = tempfile.mkdtemp(prefix="uploads-test-")


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(app):
    with app.app_context():
        u = User(
            email="admin@test.de",
            name="Admin Test",
            role="admin",
            personalnummer="1",
            aktiv=True,
        )
        u.set_password("pw")
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture
def worker(app):
    with app.app_context():
        u = User(
            email="max@test.de",
            name="Max Mustermann",
            role="mitarbeiter",
            personalnummer="82",
            aktiv=True,
        )
        u.set_password("pw")
        db.session.add(u)
        db.session.commit()
        return u.id
