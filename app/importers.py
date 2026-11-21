"""Import der Stempeluhr-Excel ('Zeitbericht').

Aufbau (Blatt 'Zeitbericht', Kopfzeile in Zeile 1):
Vorname | Nachname | Datum (DD-MM-YYYY) | Hinein (HH:MM) | In Origin | Hinaus | Out Origin |
Dauer (HH:MM) | Projekt | Mitarbeiternummer | Zweite Mitarbeiternr. | ... | Abwesenheit | Remarks | ...

Folgezeilen (weitere Buchung am selben Tag) haben Vorname/Nachname/Datum leer -> Forward-Fill.
Die echte Personalnummer steht in 'Zweite Mitarbeiternr.' (Spalte 'Mitarbeiternummer' ist leer).
"""

import json
from datetime import datetime, timedelta

import openpyxl

from .extensions import db
from .models import Abwesenheit, ImportBatch, TimeEntry, User
from .utils import get_or_create_period, parse_datum, parse_hhmm, parse_time, period_for

COLUMN_ALIASES = {
    "vorname": ["vorname", "firstname"],
    "nachname": ["nachname", "lastname", "name"],
    "datum": ["datum", "date"],
    "hinein": ["hinein", "in", "kommen", "start"],
    "in_origin": ["in origin", "in-origin", "origin in", "quelle in"],
    "hinaus": ["hinaus", "out", "gehen", "ende"],
    "out_origin": ["out origin", "out-origin", "quelle out"],
    "dauer": ["dauer", "duration"],
    "projekt": ["projekt", "project", "kategorie"],
    "mitarbeiternummer": ["mitarbeiternummer", "personalnummer", "mitarbeiter-nr", "personal-nr"],
    "zweite_mitarbeiternr": ["zweite mitarbeiternr.", "zweite mitarbeiternummer", "zweite nr", "mitarbeiter nr 2"],
    "abwesenheit": ["abwesenheit", "absence", "grund"],
    "remarks": ["remarks", "bemerkung", "notiz"],
    "comments": ["comments", "kommentar"],
    "buchungsstandort": ["buchungsstandort", "standort"],
    "department": ["department", "abteilung"],
}


def _find_columns(header):
    mapping = {}
    for idx, cell in enumerate(header):
        name = str(cell).strip().lower() if cell is not None else ""
        for key, aliases in COLUMN_ALIASES.items():
            if key not in mapping and name in aliases:
                mapping[key] = idx
    return mapping


def _find_user(vorname, nachname, personalnummer):
    if personalnummer not in (None, ""):
        u = User.query.filter(User.personalnummer == str(personalnummer).strip()).first()
        if u:
            return u
    if vorname and nachname:
        name = f"{vorname} {nachname}".strip()
        return User.query.filter(db.func.lower(User.name) == name.lower()).first()
    return None


def import_stempeluhr_xlsx(path, hochgeladen_von_id, filename=None):
    """Importiert eine Stempeluhr-Excel-Datei. Liefert den ImportBatch (commit ist inkludiert)."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheet_name = "Zeitbericht" if "Zeitbericht" in wb.sheetnames else wb.sheetnames[0]
        ws = wb[sheet_name]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            raise ValueError("Datei ist leer (keine Kopfzeile gefunden).")
        cols = _find_columns(header)
        if "datum" not in cols:
            raise ValueError("Spalte 'Datum' wurde nicht gefunden.")

        batch = ImportBatch(
            filename=filename or path,
            hochgeladen_von=hochgeladen_von_id,
            status="ok",
        )
        db.session.add(batch)
        db.session.flush()

        log = []
        counts = {"zeilen": 0, "importiert": 0, "doppelt": 0, "fehler": 0, "abwesenheit": 0}
        current = {"vorname": None, "nachname": None, "datum": None}

        def cell(row, key):
            idx = cols.get(key)
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        for lineno, row in enumerate(rows, start=2):
            counts["zeilen"] += 1
            vorname = cell(row, "vorname")
            nachname = cell(row, "nachname")
            datum = cell(row, "datum")
            if vorname or nachname or datum:
                current["vorname"] = vorname or current["vorname"]
                current["nachname"] = nachname or current["nachname"]
                current["datum"] = datum or current["datum"]

            d = parse_datum(current["datum"])
            if d is None:
                counts["fehler"] += 1
                log.append({"zeile": lineno, "status": "fehler", "meldung": f"Kein Datum erkannt: {current['datum']!r}"})
                continue

            hinein = parse_time(cell(row, "hinein"))
            hinaus = parse_time(cell(row, "hinaus"))
            abw = cell(row, "abwesenheit")
            abw_text = str(abw).strip() if abw is not None else ""

            pn = cell(row, "zweite_mitarbeiternr") or cell(row, "mitarbeiternummer")
            user = _find_user(current["vorname"], current["nachname"], pn)
            if user is None:
                counts["fehler"] += 1
                log.append({
                    "zeile": lineno,
                    "status": "fehler",
                    "datum": d.isoformat(),
                    "meldung": f"Kein Mitarbeiter gefunden ({current['vorname']} {current['nachname']}, Nr. {pn!r}).",
                })
                continue

            if hinein is None and hinaus is None:
                # Kein Dienst — ggf. Abwesenheit (Urlaub/Krank/...) als eigener Eintrag speichern
                if abw_text and abw_text not in ("00:00", "0:00"):
                    p = period_for(d.year, d.month)
                    if p and p.gesperrt:
                        counts["fehler"] += 1
                        log.append({
                            "zeile": lineno,
                            "status": "fehler",
                            "mitarbeiter": user.name,
                            "datum": d.isoformat(),
                            "meldung": f"Zeitraum {p.name} ist gesperrt — Abwesenheit nicht übernommen.",
                        })
                        continue
                    typ = abw_text[:40]
                    exists = Abwesenheit.query.filter_by(
                        user_id=user.id, datum=d, quelle="stempeluhr", typ=typ
                    ).first()
                    if exists:
                        counts["doppelt"] += 1
                        log.append({
                            "zeile": lineno,
                            "status": "doppelt",
                            "mitarbeiter": user.name,
                            "datum": d.isoformat(),
                            "meldung": f"Abwesenheit '{typ}' bereits importiert.",
                        })
                    else:
                        db.session.add(Abwesenheit(
                            user_id=user.id,
                            datum=d,
                            typ=typ,
                            bemerkung=str(cell(row, "remarks") or "").strip() or None,
                            quelle="stempeluhr",
                            import_id=batch.id,
                        ))
                        counts["abwesenheit"] += 1
                        log.append({
                            "zeile": lineno,
                            "status": "abwesenheit",
                            "mitarbeiter": user.name,
                            "datum": d.isoformat(),
                            "meldung": typ,
                        })
                continue  # kein Dienst an diesem Tag

            if hinein is None or hinaus is None:
                counts["fehler"] += 1
                log.append({
                    "zeile": lineno,
                    "status": "fehler",
                    "datum": d.isoformat(),
                    "meldung": "Nur Kommen ODER Gehen gebucht — Zeile übersprungen.",
                })
                continue

            start = datetime.combine(d, hinein)
            ende = datetime.combine(d, hinaus)
            if ende < start:  # Buchung über Nacht
                ende += timedelta(days=1)
            dauer = parse_hhmm(cell(row, "dauer"))
            if dauer is None:
                dauer = int((ende - start).total_seconds() // 60)

            period = get_or_create_period(start)
            if period.gesperrt:
                counts["fehler"] += 1
                log.append({
                    "zeile": lineno,
                    "status": "fehler",
                    "datum": d.isoformat(),
                    "meldung": f"Zeitraum {period.name} ist gesperrt.",
                })
                continue

            exists = TimeEntry.query.filter_by(user_id=user.id, start=start, quelle="stempeluhr").first()
            if exists:
                counts["doppelt"] += 1
                log.append({
                    "zeile": lineno,
                    "status": "doppelt",
                    "mitarbeiter": user.name,
                    "datum": d.isoformat(),
                    "start": start.strftime("%H:%M"),
                    "meldung": "Bereits importiert — übersprungen.",
                })
                continue

            kategorie = str(cell(row, "projekt") or "Allgemein").strip() or "Allgemein"
            bemerkung = " | ".join(
                str(x).strip() for x in (cell(row, "remarks"), cell(row, "comments")) if x
            ) or None
            origin = f"{cell(row, 'in_origin') or ''}/{cell(row, 'out_origin') or ''}".strip("/") or None

            entry = TimeEntry(
                user_id=user.id,
                start=start,
                ende=ende,
                dauer_minuten=dauer,
                kategorie=kategorie,
                bemerkung=bemerkung,
                quelle="stempeluhr",
                origin=origin,
                import_id=batch.id,
            )
            db.session.add(entry)
            counts["importiert"] += 1
            log.append({
                "zeile": lineno,
                "status": "ok",
                "mitarbeiter": user.name,
                "datum": d.isoformat(),
                "start": start.strftime("%H:%M"),
                "ende": ende.strftime("%H:%M"),
            })

        batch.zeilen = counts["zeilen"]
        batch.importiert = counts["importiert"]
        batch.doppelt = counts["doppelt"]
        batch.fehler = counts["fehler"]
        batch.abwesenheit = counts["abwesenheit"]
        batch.log = json.dumps(log, ensure_ascii=False)
        if counts["fehler"] and counts["importiert"] == 0:
            batch.status = "fehler"
        elif counts["fehler"]:
            batch.status = "mit_fehlern"
        db.session.commit()
        return batch
    finally:
        wb.close()
