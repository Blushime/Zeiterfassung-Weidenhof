# Zeiterfassung Weidenhof

Team-Zeiterfassung (Web-App) mit **Urlaubsverwaltung**, **Stempeluhr-Excel-Import**,
**Abrechnungszeiträumen / Zeitkonten** und **DATEV-Export (Unternehmen online)**.

## Features

- **Login & Rollen**: `admin`, `chef`, `mitarbeiter` — responsiv, funktioniert auf PC, Tablet und Handy
- **Zeiterfassung**: Start/Stopp-Timer + manuelle Buchungen (Datum, Von–Bis, Kategorie, Bemerkung)
- **Zeitkonto**: Ist vs. Soll (Soll = Soll-Wochenstunden des Mitarbeiters × Werktage/5) mit Gleitzeit-Saldo
- **Abrechnungszeiträume**: anlegen, sperren (keine Änderungen mehr), abrechnen
- **Stempeluhr-Import**: Excel-"Zeitbericht" hochladen — Mitarbeiter-Zuordnung über `Zweite Mitarbeiternr.`
  (Personalnummer) oder Name, Forward-Fill von Folgezeilen, Duplikatschutz (erneuter Import importiert nichts doppelt),
  Protokoll pro Zeile (ok / doppelt / Fehler / Abwesenheit)
- **Urlaub**: Antrag stellen (Arbeitstage Mo–Fr werden automatisch gezählt), Genehmigung/Ablehnung durch Chef,
  Urlaubskonto (Anspruch − genehmigte Tage = Rest); **E-Mail-Benachrichtigung** an alle aktiven Chef/Admin bei neuem Antrag
  (SMTP konfigurierbar unter Admin → Einstellungen; ohne SMTP-Host stumm deaktiviert)
- **Abwesenheiten**: In der Stempeluhr-Datei markierte Tage (Spalte `Abwesenheit`, z. B. Urlaub/Krank) werden als eigene
  Abwesenheitseinträge importiert (mit Duplikatschutz) und in Listen + PDF-Bericht angezeigt
- **Monatsbericht als PDF**: Mitarbeiter laden ihren eigenen Bericht (Buchungen, Zeitkonto, Abwesenheiten, Urlaubskonto)
  unter `/report` herunter; Admin/Chef kann Berichte beliebiger Mitarbeiter erzeugen (Mitarbeiterliste → PDF-Symbol)
- **Berechtigungen**: Admin kann unter Einstellungen pro Funktion schalten: **Start/Stopp-Timer**, **manuelle Buchungen**,
  **Zeitpassung** (eigene Buchungen bearbeiten/löschen) — deaktivierte Funktionen sind für Mitarbeiter gesperrt
- **DATEV-Export**: Bewegungsdaten (Lohnarten) für **DATEV Unternehmen online** als Semikolon-CSV
  (`Personalnummer;Abrechnungsmonat;Lohnart;Stunden`, Dezimalkomma), aggregiert pro Personalnummer + Lohnart.
  Lohnarten-Mapping konfigurierbar in den Admin-Einstellungen — **Feldfolge bitte mit dem Steuerberater abstimmen**
- **CSV-Berichte** aller Buchungen pro Zeitraum

## Tech-Stack

Python 3.12 · Flask · Flask-SQLAlchemy (SQLite, später PostgreSQL via `DATABASE_URL`) · Flask-Login ·
Flask-WTF (CSRF) · openpyxl (Excel-Import) · fpdf2 (PDF-Monatsberichte) · smtplib (E-Mail) · Jinja2-Templates, kein schweres JS-Framework

## Setup (lokal)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# erstes Admin-Konto anlegen
flask --app run.py create-admin

# optional: Demo-Daten (admin@beispiel.de / admin123 + 3 Mitarbeiter + Zeitraum 2026-09)
flask --app run.py seed-demo

# starten
python run.py        # http://localhost:5000
```

## Produktion (öffentlich mit HTTPS)

```bash
docker build -t zeiterfassung .
docker run -p 8000:8000 -e SECRET_KEY="..." -v zeiterfassung-data:/app/instance zeiterfassung
```

Davor einen Reverse Proxy mit automatischem HTTPS (z. B. Caddy):

```caddy
zeiterfassung.example.de {
    reverse_proxy localhost:8000
}
```

Zusätzlich empfohlen: regelmäßige Backups der Datei `instance/zeiterfassung.db`, starke Passwörter,
DSGVO-konforme Löschung von Konten auf Wunsch.

## Stempeluhr-Excel (Format)

Blatt `Zeitbericht`, Kopfzeile in Zeile 1. Relevante Spalten:

| Spalte | Bedeutung |
|---|---|
| `Vorname`, `Nachname`, `Datum` | leer bei Folgezeilen (gleicher Tag) → Forward-Fill |
| `Hinein` / `Hinaus` | `HH:MM`, leer = kein Dienst |
| `In Origin` / `Out Origin` | z. B. `RFID` / `Manuell` |
| `Dauer` | `HH:MM` |
| `Zweite Mitarbeiternr.` | echte Personalnummer → DATEV-Personalnummer |
| `Projekt` | → Kategorie → Lohnart (Mapping) |
| `Abwesenheit` | Text (z. B. `Urlaub`) wird als Abwesenheit protokolliert |

## Tests

```bash
pip install pytest
pytest -q
```

## Projektstruktur

```
app/
  __init__.py      # App-Factory
  config.py        # Konfiguration (Env: SECRET_KEY, DATABASE_URL)
  models.py        # User, TimeEntry, Abrechnungszeitraum, ImportBatch, Urlaubsantrag, Setting
  importers.py     # Stempeluhr-Excel-Import
  datev.py         # DATEV-Export + CSV-Berichte
  auth.py / main.py / admin.py   # Blueprints
  cli.py           # flask create-admin / seed-demo
  templates/       # Jinja2-Templates
  static/          # CSS
tests/             # pytest
```
