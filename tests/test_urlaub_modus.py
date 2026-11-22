from datetime import date, datetime

from app.datev import export_datev_unternehmen_online
from app.extensions import db
from app.models import Abrechnungszeitraum, Setting, TimeEntry, Urlaubsantrag, User
from app.utils import urlaub_stunden, urlaubauszahlung_stunden, urlaubskonto


def _set_modus(app, user_id, modus, stunden=8.0):
    with app.app_context():
        u = db.session.get(User, user_id)
        u.urlaub_modus = modus
        u.urlaub_stunden_pro_tag = stunden
        db.session.commit()


def test_urlaubskonto_auszahlung_belastet_nicht(app, worker):
    with app.app_context():
        db.session.add(Urlaubsantrag(user_id=worker, von=date(2026, 9, 7), bis=date(2026, 9, 11),
                                     tage=5, status="genehmigt"))
        _set_modus(app, worker, "konto")
        konto = urlaubskonto(db.session.get(User, worker), 2026)
        assert konto["genommen"] == 5
        _set_modus(app, worker, "auszahlung")
        konto = urlaubskonto(db.session.get(User, worker), 2026)
        assert konto["genommen"] == 0  # Auszahlung belastet das Konto nicht
        assert konto["rest"] == konto["anspruch"]


def test_urlaub_stunden_pro_tag(app, worker):
    with app.app_context():
        u = db.session.get(User, worker)
        assert urlaub_stunden(u, 5) == 40.0  # default 8 h
        u.urlaub_stunden_pro_tag = 7.5
        db.session.commit()
        db.session.refresh(u)
        assert urlaub_stunden(u, 4) == 30.0  # 4 Tage à 7,5 h
        assert urlaubauszahlung_stunden(120 * 60) == 10.0  # 120 h / 12


def test_datev_export_mit_urlaubsauszahlung(app, admin_user, worker):
    with app.app_context():
        db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="offen"))
        db.session.add(Setting(key="datev_lohnart_default", value="1000"))
        db.session.add(Setting(key="datev_lohnart_urlaub_auszahlung", value="9000"))
        # 120 h gearbeitet im September
        db.session.add(TimeEntry(user_id=worker, start=datetime(2026, 9, 1, 8, 0),
                                 ende=datetime(2026, 9, 1, 16, 0), dauer_minuten=480,
                                 kategorie="Allgemein", quelle="stempeluhr"))
        for day in range(2, 31):
            db.session.add(TimeEntry(user_id=worker, start=datetime(2026, 9, day, 8, 0),
                                     ende=datetime(2026, 9, day, 12, 0), dauer_minuten=240,
                                     kategorie="Allgemein", quelle="stempeluhr"))
        _set_modus(app, worker, "auszahlung")
        db.session.commit()

        period = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first()
        csv_data = export_datev_unternehmen_online(period)
        lines = csv_data.strip().split("\r\n")
        # 8 h + 29 Tage à 4 h = 124 h Ist; Auszahlung = 124/12 = 10,33 h
        assert "82;202609;1000;124,00" in lines  # normale Stunden
        assert "82;202609;9000;10,33" in lines   # Urlaubsauszahlung = Ist/12

        # im Konto-Modus darf keine Auszahlungszeile erscheinen
        _set_modus(app, worker, "konto")
        csv_data = export_datev_unternehmen_online(period)
        assert "9000" not in csv_data
