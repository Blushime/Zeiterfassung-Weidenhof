"""Stellt sicher, dass 'flask db upgrade' das komplette Schema aus den Migrationen aufbaut."""

from sqlalchemy import inspect

from app import create_app
from app.extensions import db
from tests.conftest import TestConfig


def test_db_upgrade_creates_full_schema(tmp_path):
    db_file = tmp_path / "mig.db"

    class MigConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"

    app = create_app(MigConfig)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output

    with app.app_context():
        tables = inspect(db.engine).get_table_names()
    for expected in [
        "users",
        "time_entries",
        "abrechnungszeitraeume",
        "import_batches",
        "urlaubsantraege",
        "absenzen",
        "settings",
        "alembic_version",
    ]:
        assert expected in tables, f"Tabelle fehlt nach db upgrade: {expected}"

    # User-Tabelle enthält die Felder aus den Migrationen
    with app.app_context():
        cols = [c["name"] for c in inspect(db.engine).get_columns("users")]
    assert "perm_overrides" in cols
    assert "urlaub_modus" in cols
    assert "urlaub_stunden_pro_tag" in cols
    assert "hat_soll" in cols
    assert "soll_stunden_monat" in cols
    assert "arbeitsplan" in cols

    with app.app_context():
        period_cols = [c["name"] for c in inspect(db.engine).get_columns("abrechnungszeitraeume")]
    assert "soll_stunden" in period_cols
