from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager

ROLES = ("admin", "chef", "mitarbeiter")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="mitarbeiter")  # admin|chef|mitarbeiter
    personalnummer = db.Column(db.String(32), unique=True, nullable=True)  # DATEV-Personalnummer
    department = db.Column(db.String(80), nullable=True)
    urlaubsanspruch_tage = db.Column(db.Float, nullable=False, default=30.0)
    # "konto" = Urlaub belastet das Urlaubskonto (Tage); "auszahlung" = Zwölftel der Monatsstunden wird ausgezahlt
    urlaub_modus = db.Column(db.String(20), nullable=False, default="konto", server_default="konto")
    urlaub_stunden_pro_tag = db.Column(db.Float, nullable=False, default=8.0, server_default=db.text("8.0"))
    soll_wochenstunden = db.Column(db.Float, nullable=False, default=40.0)
    aktiv = db.Column(db.Boolean, nullable=False, default=True)
    # JSON-Overrides für Berechtigungen, z. B. {"timer": "0", "manual": "1"} — leer = globale Einstellung
    perm_overrides = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_chef(self):
        return self.role in ("admin", "chef")

    def __repr__(self):
        return f"<User {self.email}>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Abrechnungszeitraum(db.Model):
    __tablename__ = "abrechnungszeitraeume"

    id = db.Column(db.Integer, primary_key=True)
    jahr = db.Column(db.Integer, nullable=False)
    monat = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="offen")  # offen|gesperrt|abgerechnet
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    geschlossen_am = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint("jahr", "monat", name="uq_period"),)

    @property
    def name(self):
        return f"{self.jahr}-{self.monat:02d}"

    @property
    def gesperrt(self):
        return self.status in ("gesperrt", "abgerechnet")

    def __repr__(self):
        return f"<Zeitraum {self.name} {self.status}>"


class TimeEntry(db.Model):
    __tablename__ = "time_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    start = db.Column(db.DateTime, nullable=False, index=True)
    ende = db.Column(db.DateTime, nullable=True)  # None = laufende Buchung
    dauer_minuten = db.Column(db.Integer, nullable=True)
    kategorie = db.Column(db.String(80), nullable=False, default="Allgemein")
    bemerkung = db.Column(db.Text, nullable=True)
    quelle = db.Column(db.String(20), nullable=False, default="manuell")  # manuell|stempeluhr
    origin = db.Column(db.String(40), nullable=True)  # z. B. "RFID/Manuell"
    import_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("entries", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "start", "quelle", name="uq_entry_dedupe"),
    )

    @property
    def laufend(self):
        return self.ende is None

    @property
    def dauer(self):
        if self.dauer_minuten is not None:
            return self.dauer_minuten
        if self.ende is None:
            return int((datetime.utcnow() - self.start).total_seconds() // 60)
        return int((self.ende - self.start).total_seconds() // 60)

    def __repr__(self):
        return f"<TimeEntry user={self.user_id} {self.start}>"


class ImportBatch(db.Model):
    __tablename__ = "import_batches"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    hochgeladen_von = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    hochgeladen_am = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False, default="ok")  # ok|mit_fehlern|fehler
    zeilen = db.Column(db.Integer, nullable=False, default=0)
    importiert = db.Column(db.Integer, nullable=False, default=0)
    doppelt = db.Column(db.Integer, nullable=False, default=0)
    fehler = db.Column(db.Integer, nullable=False, default=0)
    abwesenheit = db.Column(db.Integer, nullable=False, default=0)
    log = db.Column(db.Text, nullable=True)  # JSON-Liste der Zeilenprotokolle

    uploader = db.relationship("User", backref="imports")


class Urlaubsantrag(db.Model):
    __tablename__ = "urlaubsantraege"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    von = db.Column(db.Date, nullable=False)
    bis = db.Column(db.Date, nullable=False)
    tage = db.Column(db.Float, nullable=False, default=0.0)  # Arbeitstage (Mo-Fr)
    bemerkung = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="beantragt")  # beantragt|genehmigt|abgelehnt
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    genehmigt_von = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    genehmigt_am = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], backref="urlaubsantraege")
    genehmiger = db.relationship("User", foreign_keys=[genehmigt_von])


class Abwesenheit(db.Model):
    """Abwesenheit aus der Stempeluhr (z. B. Urlaub, Krank) — eigener Eintrag, keine Zeitbuchung."""

    __tablename__ = "absenzen"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    datum = db.Column(db.Date, nullable=False, index=True)
    typ = db.Column(db.String(40), nullable=False, default="Sonstiges")  # z. B. Urlaub, Krank
    bemerkung = db.Column(db.Text, nullable=True)
    quelle = db.Column(db.String(20), nullable=False, default="stempeluhr")
    import_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("absenzen", lazy="dynamic"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "datum", "quelle", "typ", name="uq_absenz"),
    )

    def __repr__(self):
        return f"<Abwesenheit {self.user_id} {self.datum} {self.typ}>"


class Setting(db.Model):
    __tablename__ = "settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=True)
