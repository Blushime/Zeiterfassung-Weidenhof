import app.mailer as mailer_mod
from app.extensions import db
from app.models import Setting


def test_urlaub_triggers_email_when_smtp_configured(client, worker, admin_user, app, monkeypatch):
    with app.app_context():
        db.session.add(Setting(key="smtp_host", value="smtp.test.local"))
        db.session.commit()
    sent = []
    monkeypatch.setattr(mailer_mod, "send_mail", lambda s, b, r: sent.append((s, r)) or True)
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    client.post("/urlaub", data={"von": "2026-09-07", "bis": "2026-09-08"}, follow_redirects=True)
    assert len(sent) == 1
    assert "admin@test.de" in sent[0][1]  # Admin/Chef wird benachrichtigt
    assert "Urlaubsantrag" in sent[0][0]


def test_urlaub_no_email_without_smtp(client, worker, app, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer_mod, "send_mail", lambda s, b, r: sent.append(r) or True)
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    resp = client.post("/urlaub", data={"von": "2026-09-07", "bis": "2026-09-08"}, follow_redirects=True)
    assert resp.status_code == 200
    assert sent == []  # ohne SMTP-Host kein Versand, Antrag trotzdem gestellt
    from app.models import Urlaubsantrag
    with app.app_context():
        assert Urlaubsantrag.query.count() == 1
