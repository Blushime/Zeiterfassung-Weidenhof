from datetime import date

from app.extensions import db
from app.models import Abrechnungszeitraum, Abwesenheit, User, Urlaubsantrag
from app.utils import plan_days_between, user_plan_days


def test_plan_default_mo_fr(app, worker):
    with app.app_context():
        u = db.session.get(User, worker)
        assert user_plan_days(u) == {0, 1, 2, 3, 4}
        # 07.09.2026 (Mo) bis 11.09.2026 (Fr) = 5 Tage
        assert plan_days_between(u, date(2026, 9, 7), date(2026, 9, 11)) == 5


def test_plan_individuell(app, worker):
    with app.app_context():
        u = db.session.get(User, worker)
        u.arbeitsplan = "0,2,4"  # Mo, Mi, Fr
        db.session.commit()
        db.session.refresh(u)
        assert user_plan_days(u) == {0, 2, 4}
        assert plan_days_between(u, date(2026, 9, 7), date(2026, 9, 11)) == 3  # Mo, Mi, Fr


def test_urlaub_zählt_nur_plan_tage(client, worker, app):
    with app.app_context():
        u = db.session.get(User, worker)
        u.arbeitsplan = "6"  # nur Sonntag
        db.session.commit()
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    # So 06.09.2026 bis So 13.09.2026 -> 2 Sonntage
    client.post("/urlaub", data={"von": "2026-09-06", "bis": "2026-09-13", "bemerkung": "test"})
    with app.app_context():
        antrag = Urlaubsantrag.query.filter_by(user_id=worker).first()
        assert antrag is not None and antrag.tage == 2


def test_admin_absenz_anlegen_bearbeiten_loeschen(client, admin_user, worker, app):
    with app.app_context():
        db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="offen"))
        db.session.commit()
    client.post("/login", data={"email": "admin@test.de", "password": "pw"})
    # anlegen: Mo-Fr 07.-11.09. -> 5 Einträge, Typ Krank
    client.post("/admin/absenzen/new", data={
        "user_id": str(worker), "von": "2026-09-07", "bis": "2026-09-11",
        "typ": "Krank", "bemerkung": "Grippe",
    }, follow_redirects=True)
    with app.app_context():
        rows = Abwesenheit.query.filter_by(user_id=worker, typ="Krank").all()
        assert len(rows) == 5
        assert all(r.quelle == "manuell" for r in rows)
        aid = rows[0].id
    # Duplikat -> wird übersprungen
    client.post("/admin/absenzen/new", data={
        "user_id": str(worker), "von": "2026-09-07", "bis": "2026-09-07", "typ": "Krank",
    }, follow_redirects=True)
    with app.app_context():
        assert Abwesenheit.query.filter_by(user_id=worker).count() == 5
    # bearbeiten
    client.post(f"/admin/absenzen/{aid}/edit", data={
        "datum": "2026-09-08", "typ": "Urlaub", "bemerkung": "geändert",
    }, follow_redirects=True)
    with app.app_context():
        a = db.session.get(Abwesenheit, aid)
        assert str(a.datum) == "2026-09-08" and a.typ == "Urlaub" and a.bemerkung == "geändert"
    # löschen
    client.post(f"/admin/absenzen/{aid}/delete", follow_redirects=True)
    with app.app_context():
        assert db.session.get(Abwesenheit, aid) is None
        assert Abwesenheit.query.filter_by(user_id=worker).count() == 4


def test_admin_absenz_gesperrt(client, admin_user, worker, app):
    with app.app_context():
        db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="gesperrt"))
        db.session.commit()
    client.post("/login", data={"email": "admin@test.de", "password": "pw"})
    client.post("/admin/absenzen/new", data={
        "user_id": str(worker), "von": "2026-09-07", "bis": "2026-09-08", "typ": "Krank",
    }, follow_redirects=True)
    with app.app_context():
        assert Abwesenheit.query.filter_by(user_id=worker).count() == 0  # nichts angelegt


def test_worker_403_absenz_admin(client, worker, app):
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    assert client.get("/admin/absenzen/new").status_code == 403
    assert client.post("/admin/absenzen/new", data={}).status_code == 403


def test_user_form_rendert_mit_arbeitsplan(client, admin_user, worker):
    """Regression: Mitarbeiter-Formular (neu/bearbeiten) darf nicht 500 werfen (Jinja-Set-Literal)."""
    client.post("/login", data={"email": "admin@test.de", "password": "pw"})
    r = client.get("/admin/users/new")
    assert r.status_code == 200 and r.get_data(as_text=True).count('name="plan"') == 7
    r = client.get(f"/admin/users/{worker}/edit")
    assert r.status_code == 200 and 'name="plan"' in r.get_data(as_text=True)
