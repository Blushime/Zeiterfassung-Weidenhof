from datetime import datetime

from app.datev import export_datev_unternehmen_online, export_entries_csv
from app.extensions import db
from app.models import Abrechnungszeitraum, Setting, TimeEntry


def test_datev_export(app, admin_user, worker):
    with app.app_context():
        db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="offen"))
        db.session.add(Setting(key="datev_lohnart_default", value="1000"))
        db.session.add(Setting(key="lohnarten_mapping", value='{"Projekt A": "2010"}'))
        db.session.add(TimeEntry(user_id=worker, start=datetime(2026, 9, 1, 8, 0),
                                 ende=datetime(2026, 9, 1, 16, 0), dauer_minuten=480,
                                 kategorie="Allgemein", quelle="manuell"))
        db.session.add(TimeEntry(user_id=worker, start=datetime(2026, 9, 2, 8, 0),
                                 ende=datetime(2026, 9, 2, 12, 0), dauer_minuten=240,
                                 kategorie="Projekt A", quelle="stempeluhr"))
        db.session.commit()

        period = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first()
        csv_data = export_datev_unternehmen_online(period)
        lines = [l for l in csv_data.strip().split("\r\n")]
        assert lines[0] == "Personalnummer;Abrechnungsmonat;Lohnart;Stunden"
        assert "82;202609;1000;8,00" in lines
        assert "82;202609;2010;4,00" in lines

        raw = export_entries_csv(period)
        assert "Max Mustermann" in raw
        assert raw.count("\r\n") == 3  # Kopf + 2 Zeilen
