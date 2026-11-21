import openpyxl

from app.extensions import db
from app.importers import import_stempeluhr_xlsx
from app.models import Abwesenheit, TimeEntry

HEADER = [
    "Vorname", "Nachname", "Datum", "Hinein", "In Origin", "Hinaus", "Out Origin",
    "Dauer", "Projekt", "Mitarbeiternummer", "Zweite Mitarbeiternr.", "Geplant",
    "Gearbeitete Stunden", "Geplante Pause", "Pause", "Saldo", "Abwesenheit",
    "Remarks", "Buchungsstandort", "Department", "Comments",
]


def _write_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Zeitbericht"
    ws.append(HEADER)
    # Tag 1: eine Buchung
    ws.append(["Max", "Mustermann", "01-09-2026", "08:00", "RFID", "12:00", "RFID",
               "04:00", "", None, "82", "flex", "04:00", "00:00", "00:00", "flex", "00:00",
               "", "Weidenhof GmbH", "Feste", ""])
    # Tag 2: zwei Buchungen -> Folgezeile ohne Name/Datum
    ws.append(["Max", "Mustermann", "02-09-2026", "08:00", "RFID", "12:00", "RFID",
               "04:00", "", None, "82", "flex", "04:00", "00:00", "00:00", "flex", "00:00",
               "", "Weidenhof GmbH", "Feste", ""])
    ws.append([None, None, None, "13:00", "Manuell", "17:00", "Manuell",
               "04:00", "Projekt A", None, None, None, None, None, None, None, None,
               None, "Weidenhof GmbH", "Feste", None])
    # Tag 3: keine Buchung, Abwesenheit
    ws.append(["Max", "Mustermann", "03-09-2026", None, None, None, None,
               "", "", None, "82", "flex", "00:00", "00:00", "00:00", "flex", "Urlaub",
               "", "", "Feste", ""])
    # Unbekannter Mitarbeiter
    ws.append(["Ute", "Unbekannt", "01-09-2026", "08:00", "RFID", "09:00", "RFID",
               "01:00", "", None, "999", "flex", "01:00", "00:00", "00:00", "flex", "00:00",
               "", "", "", ""])
    wb.save(path)


def test_import_stempeluhr(app, admin_user, worker, tmp_path):
    path = tmp_path / "Zeitbericht 2026-09-01 - 2026-09-30.xlsx"
    _write_xlsx(path)

    with app.app_context():
        batch = import_stempeluhr_xlsx(str(path), admin_user, filename=path.name)
        assert batch.zeilen == 5
        assert batch.importiert == 3  # 08-12 + 08-12 + 13-17
        assert batch.abwesenheit == 1  # "Urlaub" am 03-09
        assert batch.fehler == 1  # unbekannter Mitarbeiter
        assert batch.doppelt == 0

        entries = TimeEntry.query.filter_by(quelle="stempeluhr").order_by(TimeEntry.start).all()
        assert len(entries) == 3
        assert entries[0].dauer_minuten == 240
        assert entries[2].kategorie == "Projekt A"
        assert entries[2].origin == "Manuell/Manuell"

        absenzen = Abwesenheit.query.all()
        assert len(absenzen) == 1
        assert absenzen[0].typ == "Urlaub"
        assert str(absenzen[0].datum) == "2026-09-03"

        # Erneuter Import derselben Datei -> alles doppelt (auch die Abwesenheit)
        batch2 = import_stempeluhr_xlsx(str(path), admin_user, filename=path.name)
        assert batch2.importiert == 0
        assert batch2.doppelt == 4  # 3 Buchungen + 1 Abwesenheit
        assert TimeEntry.query.filter_by(quelle="stempeluhr").count() == 3
        assert Abwesenheit.query.count() == 1


def test_import_gesperrter_zeitraum(app, admin_user, worker, tmp_path):
    from app.models import Abrechnungszeitraum

    with app.app_context():
        db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="gesperrt"))
        db.session.commit()

    path = tmp_path / "Zeitbericht.xlsx"
    _write_xlsx(path)
    with app.app_context():
        batch = import_stempeluhr_xlsx(str(path), admin_user, filename=path.name)
        assert batch.importiert == 0
        # 3 Buchungen gesperrt + 1 Abwesenheit gesperrt + 1 unbekannter Mitarbeiter
        assert batch.fehler == 5
        assert TimeEntry.query.count() == 0
        assert Abwesenheit.query.count() == 0
