from datetime import datetime

from app.extensions import db
from app.models import Abrechnungszeitraum, TimeEntry


def _make_entry(app, worker):
    with app.app_context():
        db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="offen"))
        en = TimeEntry(user_id=worker, start=datetime(2026, 9, 1, 8, 0),
                       ende=datetime(2026, 9, 1, 16, 0), dauer_minuten=480,
                       kategorie="Allgemein", quelle="manuell")
        db.session.add(en)
        db.session.commit()
        return en.id


def test_admin_mitarbeiter_detail_200(client, admin_user, worker, app):
    _make_entry(app, worker)
    client.post("/login", data={"email": "admin@test.de", "password": "pw"})
    resp = client.get(f"/admin/mitarbeiter/{worker}?jahr=2026&monat=9")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Max Mustermann" in body
    assert "Zeitkonto" in body and "08:00" in body and "16:00" in body
    assert "Urlaub" in body


def test_mitarbeiter_detail_forbidden_for_worker(client, worker, admin_user):
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    resp = client.get(f"/admin/mitarbeiter/{admin_user}")
    assert resp.status_code == 403
    resp = client.get(f"/admin/entries/1/edit")
    assert resp.status_code == 403


def test_admin_can_edit_other_users_entry(client, admin_user, worker, app):
    eid = _make_entry(app, worker)
    client.post("/login", data={"email": "admin@test.de", "password": "pw"})
    resp = client.post(f"/admin/entries/{eid}/edit", data={
        "datum": "2026-09-01", "von": "08:00", "bis": "18:00",
        "kategorie": "Allgemein", "bemerkung": "korrigiert vom Admin",
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        en = db.session.get(TimeEntry, eid)
        assert en.dauer_minuten == 600  # 08:00-18:00
        assert en.bemerkung == "korrigiert vom Admin"


def test_admin_edit_blocked_in_locked_period(client, admin_user, worker, app):
    eid = _make_entry(app, worker)
    with app.app_context():
        p = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first()
        p.status = "gesperrt"
        db.session.commit()
    client.post("/login", data={"email": "admin@test.de", "password": "pw"})
    client.post(f"/admin/entries/{eid}/edit", data={
        "datum": "2026-09-01", "von": "08:00", "bis": "18:00", "kategorie": "Allgemein",
    }, follow_redirects=True)
    with app.app_context():
        en = db.session.get(TimeEntry, eid)
        assert en.dauer_minuten == 480  # unverändert
