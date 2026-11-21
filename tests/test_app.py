from app.extensions import db
from app.models import User


def test_login_and_dashboard(client, admin_user):
    # Login
    resp = client.post("/login", data={"email": "admin@test.de", "password": "pw"},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert "Hallo Admin Test".encode() in resp.data
    # Dashboard erreichbar, Logout
    resp = client.get("/logout", follow_redirects=True)
    assert resp.status_code == 200


def test_mitarbeiter_cannot_access_admin(client, worker):
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    resp = client.get("/admin/users")
    assert resp.status_code == 403
    resp = client.get("/admin/")
    assert resp.status_code == 403


def test_manual_entry_and_saldo(client, worker):
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    # Manuelle Buchung über /entries
    resp = client.post("/entries?jahr=2026&monat=9", data={
        "datum": "2026-09-01", "von": "08:00", "bis": "16:00",
        "kategorie": "Allgemein", "bemerkung": "Test",
    }, follow_redirects=True)
    assert resp.status_code == 200
    with client.application.app_context():
        from app.models import TimeEntry
        assert TimeEntry.query.count() == 1
        en = TimeEntry.query.first()
        assert en.dauer_minuten == 480


def test_urlaubsantrag(client, worker):
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    resp = client.post("/urlaub", data={
        "von": "2026-09-07", "bis": "2026-09-11",  # Mo-Fr = 5 Arbeitstage
        "bemerkung": "Kurzurlaub",
    }, follow_redirects=True)
    assert resp.status_code == 200
    with client.application.app_context():
        from app.models import Urlaubsantrag
        a = Urlaubsantrag.query.first()
        assert a is not None
        assert a.tage == 5
        assert a.status == "beantragt"
