from datetime import datetime

from app.extensions import db
from app.models import Abrechnungszeitraum, TimeEntry, User
from app.utils import ist_minuten, saldo_minuten, soll_minuten, workdays_in_month


def _add_period(app, soll=None):
    with app.app_context():
        p = Abrechnungszeitraum(jahr=2026, monat=9, status="offen", soll_stunden=soll)
        db.session.add(p)
        db.session.commit()


def _add_entry(app, worker, dauer=480):
    with app.app_context():
        db.session.add(TimeEntry(user_id=worker, start=datetime(2026, 9, 1, 8, 0),
                                 ende=datetime(2026, 9, 1, 16, 0), dauer_minuten=dauer,
                                 kategorie="Allgemein", quelle="manuell"))
        db.session.commit()


def test_soll_pro_monat(app, worker):
    _add_period(app, soll=160.0)
    _add_entry(app, worker, dauer=480)
    with app.app_context():
        u = db.session.get(User, worker)
        p = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first()
        assert soll_minuten(u, p) == 160 * 60          # 160 h/Monat
        assert saldo_minuten(u, p) == 480 - 160 * 60    # Ist - Soll


def test_minijobber_kein_soll_saldo_ist_ist(app, worker):
    _add_period(app, soll=160.0)
    _add_entry(app, worker, dauer=480)
    with app.app_context():
        u = db.session.get(User, worker)
        u.hat_soll = False   # z. B. Minijobber
        db.session.commit()
        db.session.refresh(u)
        p = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first()
        assert soll_minuten(u, p) == 0
        assert saldo_minuten(u, p) == ist_minuten(worker, p) == 480


def test_fallback_legacy_woechentlich(app, worker):
    _add_period(app, soll=None)  # kein Monats-Soll gesetzt -> Legacy 40 h/Woche
    with app.app_context():
        u = db.session.get(User, worker)
        p = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first()
        expected = int(round(40 / 5 * workdays_in_month(2026, 9) * 60))
        assert soll_minuten(u, p) == expected


def test_soll_pro_mitarbeiter_schlaegt_zeitraum(app, worker):
    """Individueller Monats-Soll des Mitarbeiters hat Vorrang vor dem Zeitraum-Soll."""
    _add_period(app, soll=160.0)  # global 160 h
    with app.app_context():
        u = db.session.get(User, worker)
        u.soll_stunden_monat = 80.0  # Teilzeit: 80 h
        db.session.commit()
        db.session.refresh(u)
        p = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first()
        assert soll_minuten(u, p) == 80 * 60
        # anderer Mitarbeiter ohne individuellen Wert -> Zeitraum-Soll
        from app.models import User as U
        other = U(email="other@test.de", name="Other", role="mitarbeiter", aktiv=True)
        other.set_password("x")
        db.session.add(other)
        db.session.commit()
        assert soll_minuten(other, p) == 160 * 60


def test_admin_period_edit_soll(client, admin_user, app):
    _add_period(app, soll=None)
    with app.app_context():
        pid = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first().id
    client.post("/login", data={"email": "admin@test.de", "password": "pw"})
    resp = client.post(f"/admin/periods/{pid}/edit", data={"soll_stunden": "152,5"}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        p = db.session.get(Abrechnungszeitraum, pid)
        assert p.soll_stunden == 152.5  # Komma-Eingabe ok


def test_worker_cannot_edit_period(client, worker, app):
    _add_period(app, soll=None)
    with app.app_context():
        pid = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first().id
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    resp = client.post(f"/admin/periods/{pid}/edit", data={"soll_stunden": "100"})
    assert resp.status_code == 403
