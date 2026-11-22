"""DATEV-Export (DATEV Unternehmen online — Bewegungsdaten/Lohnarten als Semikolon-CSV).

Hinweis: Die exakte Feldfolge/Spalten des Imports in Unternehmen online bitte mit dem
Steuerberater abstimmen. Lohnarten-Mapping und Default-Lohnart sind in den Admin-Settings
konfigurierbar (JSON, z. B. {"Allgemein": "1000", "Überstunden": "2010"}).
"""

import csv
import io
import json
from collections import defaultdict

from .models import TimeEntry, User
from .utils import get_setting, period_bounds, urlaub_modus


def lohnarten_mapping():
    raw = get_setting("lohnarten_mapping", "{}")
    try:
        m = json.loads(raw)
        return {str(k): str(v) for k, v in m.items()}
    except Exception:
        return {}


def export_datev_unternehmen_online(period) -> str:
    """Aggregierte Stunden pro Personalnummer + Lohnart als CSV (Semikolon, Dezimalkomma)."""
    mapping = lohnarten_mapping()
    default_lohnart = get_setting("datev_lohnart_default", "1000")
    abrechnungsmonat = f"{period.jahr}{period.monat:02d}"

    s, e = period_bounds(period)
    entries = TimeEntry.query.filter(TimeEntry.start >= s, TimeEntry.start < e).all()
    users = {u.id: u for u in User.query.all()}

    agg = defaultdict(float)  # (personalnummer, lohnart) -> stunden
    user_ist = defaultdict(float)  # personalnummer -> minuten (für Urlaubsauszahlung)
    for en in entries:
        u = users.get(en.user_id)
        pn = (u.personalnummer or "").strip() if u else ""
        if not pn:
            continue  # ohne Personalnummer nicht an DATEV exportierbar
        lohnart = mapping.get(en.kategorie, default_lohnart)
        agg[(pn, lohnart)] += en.dauer / 60.0
        user_ist[pn] += en.dauer

    rows = list(agg.items())

    # Urlaubsauszahlung: Mitarbeiter mit Modus 'auszahlung' bekommen das Zwölftel
    # ihrer gearbeiteten Monatsstunden als eigene Lohnart ausgezahlt.
    payout_lohnart = get_setting("datev_lohnart_urlaub_auszahlung", "9000")
    for u in User.query.all():
        pn = (u.personalnummer or "").strip()
        if pn and urlaub_modus(u) == "auszahlung" and user_ist.get(pn):
            rows.append(((pn, payout_lohnart), user_ist[pn] / 60 / 12))

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Personalnummer", "Abrechnungsmonat", "Lohnart", "Stunden"])
    for (pn, lohnart), stunden in sorted(rows):
        w.writerow([pn, abrechnungsmonat, lohnart, f"{stunden:.2f}".replace(".", ",")])
    return buf.getvalue()


def export_entries_csv(period, user_id=None) -> str:
    """Rohdaten-Export aller Buchungen eines Zeitraums (Semikolon-CSV, Deutsch)."""
    s, e = period_bounds(period)
    q = TimeEntry.query.filter(TimeEntry.start >= s, TimeEntry.start < e)
    if user_id:
        q = q.filter_by(user_id=user_id)
    items = q.order_by(TimeEntry.start).all()
    users = {u.id: u for u in User.query.all()}

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(
        ["Personalnummer", "Name", "Datum", "Von", "Bis", "Dauer (h)", "Kategorie", "Quelle", "Bemerkung"]
    )
    for en in items:
        u = users.get(en.user_id)
        w.writerow(
            [
                (u.personalnummer if u else "") or "",
                (u.name if u else "") or "",
                en.start.strftime("%d.%m.%Y"),
                en.start.strftime("%H:%M"),
                en.ende.strftime("%H:%M") if en.ende else "",
                f"{en.dauer / 60:.2f}".replace(".", ","),
                en.kategorie,
                en.quelle,
                en.bemerkung or "",
            ]
        )
    return buf.getvalue()
