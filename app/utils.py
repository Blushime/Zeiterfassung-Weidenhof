import json
from calendar import monthrange
from datetime import date, datetime, timedelta

from .extensions import db
from .models import Abrechnungszeitraum, Setting, TimeEntry, Urlaubsantrag

# Admin-seitig schaltbare Berechtigungen (Settings-Schlüssel: perm_<name> = "1"/"0")
PERMISSIONS = {
    "timer": "Start/Stopp-Timer erlauben",
    "manual": "Manuelle Buchungen erlauben",
    "edit": "Zeitpassung erlauben (eigene Buchungen bearbeiten/löschen)",
}


def get_setting(key, default=None):
    s = Setting.query.filter_by(key=key).first()
    return s.value if s and s.value not in (None, "") else default


def set_setting(key, value):
    s = Setting.query.filter_by(key=key).first()
    if s is None:
        s = Setting(key=key)
        db.session.add(s)
    s.value = value
    return s


def user_perm_override(user, name):
    """Liefert das benutzerspezifische Override ('0'/'1') oder None, wenn keines gesetzt ist."""
    raw = getattr(user, "perm_overrides", None) if user else None
    if not raw:
        return None
    try:
        v = json.loads(raw).get(name)
        return v if v in ("0", "1") else None
    except Exception:
        return None


def permission_enabled(name, user=None, default=True):
    """Effektive Berechtigung: User-Override > globale Einstellung > default.

    name z. B. 'timer' (Start/Stopp), 'manual' (manuelle Buchungen), 'edit' (Zeitpassung).
    """
    if name not in PERMISSIONS:
        return default
    if user is not None:
        ov = user_perm_override(user, name)
        if ov is not None:
            return ov == "1"
    return get_setting(f"perm_{name}", "1" if default else "0") == "1"


def parse_datum(value):
    """Wandelt Zellenwerte (str 'DD-MM-YYYY' / 'YYYY-MM-DD' / datetime / date) in ein date um."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def parse_time(value):
    """Wandelt Zellenwerte (str 'HH:MM' / time / datetime) in ein time um."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.time()
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value
    s = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


def parse_hhmm(value):
    """'HH:MM' -> Minuten (int) oder None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def fmt_hhmm(minuten):
    if minuten is None:
        return "00:00"
    sign = "-" if minuten < 0 else ""
    minuten = abs(int(minuten))
    return f"{sign}{minuten // 60:02d}:{minuten % 60:02d}"


def workdays_between(von: date, bis: date) -> int:
    """Arbeitstage (Mo-Fr) inkl. Start- und Endtag."""
    count = 0
    d = von
    while d <= bis:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


DEFAULT_PLAN = {0, 1, 2, 3, 4}  # Mo-Fr


def user_plan_days(user) -> set:
    """Wochentage (0=Mo..6=So) laut individuellem Arbeitsplan des Mitarbeiters; leer -> Mo-Fr."""
    raw = getattr(user, "arbeitsplan", None) or ""
    try:
        days = {int(x) for x in raw.split(",") if x.strip() != ""}
    except ValueError:
        days = set()
    return days if days else set(DEFAULT_PLAN)


def plan_days_between(user, von: date, bis: date) -> int:
    """Tage im Bereich [von, bis], die laut Arbeitsplan des Mitarbeiters Arbeitstage sind."""
    plan = user_plan_days(user)
    count = 0
    d = von
    while d <= bis:
        if d.weekday() in plan:
            count += 1
        d += timedelta(days=1)
    return count


def workdays_in_month(jahr: int, monat: int) -> int:
    last = monthrange(jahr, monat)[1]
    return workdays_between(date(jahr, monat, 1), date(jahr, monat, last))


def period_bounds(period):
    start = datetime(period.jahr, period.monat, 1)
    if period.monat == 12:
        end = datetime(period.jahr + 1, 1, 1)
    else:
        end = datetime(period.jahr, period.monat + 1, 1)
    return start, end


def period_for(jahr, monat):
    if not jahr or not monat:
        return None
    return Abrechnungszeitraum.query.filter_by(jahr=jahr, monat=monat).first()


def get_or_create_period(dt: datetime) -> Abrechnungszeitraum:
    p = period_for(dt.year, dt.month)
    if p is None:
        p = Abrechnungszeitraum(jahr=dt.year, monat=dt.month, status="offen")
        db.session.add(p)
        db.session.flush()
    return p


def entries_in_period(user_id, period):
    s, e = period_bounds(period)
    return (
        TimeEntry.query.filter(
            TimeEntry.user_id == user_id, TimeEntry.start >= s, TimeEntry.start < e
        )
        .order_by(TimeEntry.start)
        .all()
    )


def ist_minuten(user_id, period) -> int:
    return sum(en.dauer for en in entries_in_period(user_id, period))


def soll_minuten(user, period) -> int:
    """Soll-Minuten für einen Monat.

    Priorität:
    1. hat_soll=False (z. B. Minijobber) -> 0, Saldo = Ist
    2. individueller Monats-Soll des Mitarbeiters (soll_stunden_monat)
    3. Monats-Soll des Abrechnungszeitraums (soll_stunden, global vom Admin)
    4. Fallback (Legacy): Soll_wochenstunden/5 x Werktage
    """
    if not getattr(user, "hat_soll", True):
        return 0
    if getattr(user, "soll_stunden_monat", None):
        return int(round(user.soll_stunden_monat * 60))
    if getattr(period, "soll_stunden", None):
        return int(round(period.soll_stunden * 60))
    return int(round(user.soll_wochenstunden / 5 * workdays_in_month(period.jahr, period.monat) * 60))


def saldo_minuten(user, period) -> int:
    return ist_minuten(user.id, period) - soll_minuten(user, period)


def urlaub_modus(user):
    """'konto' (default) oder 'auszahlung' (Zwölftel der Monatsstunden, belastet nicht das Konto)."""
    return getattr(user, "urlaub_modus", None) or "konto"


def urlaub_stunden(user, tage) -> float:
    """Urlaubstage -> Stunden (pro Mitarbeiter konfigurierbar, Default 8 h/Tag)."""
    return round((tage or 0) * (getattr(user, "urlaub_stunden_pro_tag", None) or 8.0), 2)


def urlaubauszahlung_stunden(ist_minuten) -> float:
    """Auszahlungsmodus: Zwölftel der gearbeiteten Monatsstunden."""
    return round((ist_minuten or 0) / 60 / 12, 2)


def urlaubskonto(user, jahr: int) -> dict:
    anspruch = user.urlaubsanspruch_tage
    if urlaub_modus(user) == "auszahlung":
        genommen = 0  # Auszahlungsmodus belastet das Urlaubskonto nicht
    else:
        genommen = (
            db.session.query(db.func.sum(Urlaubsantrag.tage))
            .filter(
                Urlaubsantrag.user_id == user.id,
                Urlaubsantrag.status == "genehmigt",
                db.extract("year", Urlaubsantrag.von) == jahr,
            )
            .scalar()
            or 0
        )
    return {"jahr": jahr, "anspruch": anspruch, "genommen": genommen, "rest": anspruch - genommen}
