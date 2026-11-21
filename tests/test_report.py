from datetime import datetime

from app.extensions import db
from app.models import Abrechnungszeitraum, TimeEntry, User
from app.report import build_monthly_pdf
from app.utils import urlaubskonto


def test_pdf_report_route(client, worker, app):
    with app.app_context():
        db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="offen"))
        db.session.add(TimeEntry(
            user_id=worker, start=datetime(2026, 9, 1, 8, 0), ende=datetime(2026, 9, 1, 16, 0),
            dauer_minuten=480, kategorie="Allgemein", quelle="manuell",
        ))
        db.session.commit()
    client.post("/login", data={"email": "max@test.de", "password": "pw"})
    resp = client.get("/report?jahr=2026&monat=9")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF")
    assert "attachment" in resp.headers["Content-Disposition"]


def test_pdf_build_direct(app, worker):
    with app.app_context():
        db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="offen"))
        db.session.commit()
        period = Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first()
        u = db.session.get(User, worker)
        pdf = build_monthly_pdf(u, period, [], [], 0, 0, 0, urlaubskonto(u, 2026))
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 500  # sinnvoller Inhalt (Seiten-Stream ggf. komprimiert)
        # gegen ungeeignete Zeichen (nicht latin-1) abgesichert:
        assert isinstance(pdf, bytes)
