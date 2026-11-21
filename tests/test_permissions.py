from app.extensions import db
from app.models import Setting, TimeEntry


def _set_perm(app, name, on):
    with app.app_context():
        s = Setting.query.filter_by(key=f"perm_{name}").first()
        if s is None:
            s = Setting(key=f"perm_{name}")
            db.session.add(s)
        s.value = "1" if on else "0"
        db.session.commit()


def test_manual_blocked_when_disabled(client, worker, app):
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    _set_perm(app, "manual", False)
    client.post("/entries?jahr=2026&monat=9", data={
        "datum": "2026-09-01", "von": "08:00", "bis": "09:00", "kategorie": "Allgemein",
    }, follow_redirects=True)
    with app.app_context():
        assert TimeEntry.query.count() == 0
    _set_perm(app, "manual", True)
    client.post("/entries?jahr=2026&monat=9", data={
        "datum": "2026-09-01", "von": "08:00", "bis": "09:00", "kategorie": "Allgemein",
    })
    with app.app_context():
        assert TimeEntry.query.count() == 1


def test_timer_blocked_when_disabled(client, worker, app):
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    _set_perm(app, "timer", False)
    client.post("/start", follow_redirects=True)
    with app.app_context():
        assert TimeEntry.query.filter_by(ende=None).count() == 0
    _set_perm(app, "timer", True)
    client.post("/start")
    with app.app_context():
        assert TimeEntry.query.filter_by(ende=None).count() == 1


def test_edit_and_delete_blocked_when_disabled(client, worker, app):
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    client.post("/entries?jahr=2026&monat=9", data={
        "datum": "2026-09-01", "von": "08:00", "bis": "09:00", "kategorie": "Allgemein",
    })
    with app.app_context():
        eid = TimeEntry.query.first().id

    _set_perm(app, "edit", False)
    client.post(f"/entries/{eid}/delete", follow_redirects=True)
    resp = client.get(f"/entries/{eid}/edit", follow_redirects=True)
    with app.app_context():
        assert TimeEntry.query.count() == 1  # nichts gelöscht

    _set_perm(app, "edit", True)
    client.post(f"/entries/{eid}/edit", data={
        "datum": "2026-09-01", "von": "08:00", "bis": "10:00",
        "kategorie": "Allgemein", "bemerkung": "korrigiert",
    }, follow_redirects=True)
    with app.app_context():
        en = TimeEntry.query.first()
        assert en.dauer_minuten == 120
        assert en.bemerkung == "korrigiert"
