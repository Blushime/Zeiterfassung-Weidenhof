import click
from flask.cli import with_appcontext

from .extensions import db
from .models import Abrechnungszeitraum, User


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True, help="E-Mail des Admin-Kontos")
    @click.option("--name", prompt=True, help="Anzeigename")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @with_appcontext
    def create_admin(email, name, password):
        """Legt das erste Admin-Konto an."""
        if User.query.filter(db.func.lower(User.email) == email.lower()).first():
            click.echo("Es existiert bereits ein Konto mit dieser E-Mail.")
            return
        u = User(email=email.lower(), name=name, role="admin", aktiv=True)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Admin-Konto angelegt: {email}")

    @app.cli.command("seed-demo")
    @with_appcontext
    def seed_demo():
        """Demo-Daten: Admin + Beispiel-Mitarbeiter + Abrechnungszeitraum 2026-09."""
        if not User.query.filter_by(email="admin@beispiel.de").first():
            a = User(email="admin@beispiel.de", name="Demo Admin", role="admin", personalnummer="1", aktiv=True)
            a.set_password("admin123")
            db.session.add(a)
        for pn, name, dept in [
            ("82", "Sevgi Akyol", "Minijobber"),
            ("77", "Ulrike Willmer", "Feste"),
            ("8537243", "Julia Gentemann", "Feste"),
        ]:
            if not User.query.filter_by(personalnummer=pn).first():
                u = User(
                    email=f"mitarbeiter{pn}@beispiel.de",
                    name=name,
                    role="mitarbeiter",
                    personalnummer=pn,
                    department=dept,
                    aktiv=True,
                )
                u.set_password("demo123")
                db.session.add(u)
        if not Abrechnungszeitraum.query.filter_by(jahr=2026, monat=9).first():
            db.session.add(Abrechnungszeitraum(jahr=2026, monat=9, status="offen"))
        db.session.commit()
        click.echo("Demo-Daten angelegt (Login: admin@beispiel.de / admin123).")
