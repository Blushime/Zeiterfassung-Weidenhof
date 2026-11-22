# Zeiterfassung Weidenhof

Team-Zeiterfassung (Web-App) mit **Urlaubsverwaltung**, **Stempeluhr-Excel-Import**,
**Abrechnungszeiträumen / Zeitkonten** und **DATEV-Export (Unternehmen online)**.

## Features

- **Login & Rollen**: `admin`, `chef`, `mitarbeiter` — responsiv, funktioniert auf PC, Tablet und Handy
- **Zeiterfassung**: Start/Stopp-Timer + manuelle Buchungen (Datum, Von–Bis, Kategorie, Bemerkung)
- **Zeitkonto**: Ist vs. Soll mit Gleitzeit-Saldo. **Soll-Stunden pro Monat, pro Mitarbeiter einstellbar**:
  individuell am Mitarbeiter (Admin → Mitarbeiter, z. B. Vollzeit 160 h, Teilzeit 80 h) — Vorrang vor dem globalen
  Monats-Soll am Abrechnungszeitraum (Admin → Abrechnungszeiträume); Mitarbeiter **ohne Soll** (z. B. Minijobber —
  Checkbox „Hat Soll-Stunden? = nein") haben Saldo = Ist
- **Abrechnungszeiträume**: anlegen, sperren (keine Änderungen mehr), abrechnen
- **Stempeluhr-Import**: Excel-"Zeitbericht" hochladen — Mitarbeiter-Zuordnung über `Zweite Mitarbeiternr.`
  (Personalnummer) oder Name, Forward-Fill von Folgezeilen, Duplikatschutz (erneuter Import importiert nichts doppelt),
  Protokoll pro Zeile (ok / doppelt / Fehler / Abwesenheit)
- **Urlaub**: Antrag stellen (Arbeitstage Mo–Fr werden automatisch gezählt), Genehmigung/Ablehnung durch Chef,
  Urlaubskonto (Anspruch − genehmigte Tage = Rest); **E-Mail-Benachrichtigung** an alle aktiven Chef/Admin bei neuem Antrag
  (SMTP konfigurierbar unter Admin → Einstellungen; ohne SMTP-Host stumm deaktiviert).
  **Pro Mitarbeiter konfigurierbar**: Urlaubsmodus „Konto" (default) oder **„Auszahlung"** (Zwölftel der gearbeiteten
  Monatsstunden wird als Urlaub ausgezahlt, belastet das Urlaubskonto nicht — erscheint als eigene Lohnart im DATEV-Export,
  Lohnart konfigurierbar unter Einstellungen) sowie **Urlaubsstunden pro Tag** (default 8 h, Umrechnung Tage↔Stunden in Listen)
- **Abwesenheiten**: In der Stempeluhr-Datei markierte Tage (Spalte `Abwesenheit`, z. B. Urlaub/Krank) werden als eigene
  Abwesenheitseinträge importiert (mit Duplikatschutz) und in Listen + PDF-Bericht angezeigt
- **Monatsbericht als PDF**: Mitarbeiter laden ihren eigenen Bericht (Buchungen, Zeitkonto, Abwesenheiten, Urlaubskonto)
  unter `/report` herunter; Admin/Chef kann Berichte beliebiger Mitarbeiter erzeugen (Mitarbeiterliste → PDF-Symbol)
- **Admin-Sicht auf Mitarbeiter**: Admin/Chef sieht pro Mitarbeiter unter „Stände" alles, was der Mitarbeiter selbst sieht
  (Zeitkonto Ist/Soll/Saldo, Buchungen, Abwesenheiten, Urlaubskonto/Anträge, PDF-Link) — und kann in der Buchungsübersicht
  **fremde Buchungen bearbeiten** (gesperrte Zeiträume bleiben geschützt)
- **Berechtigungen**: Admin kann unter Einstellungen pro Funktion schalten: **Start/Stopp-Timer**, **manuelle Buchungen**,
  **Zeitpassung** (eigene Buchungen bearbeiten/löschen) — deaktivierte Funktionen sind für Mitarbeiter gesperrt.
  Zusätzlich **pro Mitarbeiter** überschreibbar (Mitarbeiter-Formular: „Standard / erlaubt / verboten“ je Berechtigung;
  Vorrang: Mitarbeiter-Override > globale Einstellung)
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

# Datenbankschema per Migration anlegen (Flask-Migrate/Alembic, migrations/)
flask --app run.py db upgrade
# Hinweis: bestehende DB ohne alembic_version einmalig stempeln: flask --app run.py db stamp head

# erstes Admin-Konto anlegen
flask --app run.py create-admin

# optional: Demo-Daten (admin@beispiel.de / admin123 + 3 Mitarbeiter + Zeitraum 2026-09)
flask --app run.py seed-demo

# starten
python run.py        # http://localhost:5000
```

## Schema-Änderungen später

Neu modellieren, dann Migration generieren und ausführen — die Daten bleiben erhalten:

```bash
flask --app run.py db migrate -m "beschreibung der änderung"   # autogenerate
flask --app run.py db upgrade                                    # ausführen
```

## Produktion (öffentlich mit HTTPS) — Docker Compose + Caddy

Voraussetzungen: Linux-Server (VPS) mit Docker + Docker Compose, Ports 80/443 offen,
**DNS-A-Record** von deiner Domain (z. B. `zeiterfassung.example.de`) zeigt auf die Server-IP.

```bash
# 1. Repo auf den Server
 git clone https://github.com/Blushime/Zeiterfassung-Weidenhof.git /srv/zeiterfassung
cd /srv/zeiterfassung && git checkout main   # nach Merge des PR

# 2. .env anlegen und ausfüllen (SECRET_KEY + DOMAIN)
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # -> in .env als SECRET_KEY eintragen
# DOMAIN in .env auf deine echte Domain setzen

# 3. starten (baut das Image, Caddy holt automatisch Let's-Encrypt-Zertifikat)
docker compose up -d --build

# 4. erster Admin + Migrationen (einmalig, im Container)
docker compose exec app flask --app run.py db upgrade
docker compose exec app flask --app run.py create-admin
```

App erreichbar unter **https://DEINE-DOMAIN**. Lokal testen vorher mit `DOMAIN=localhost` → https://localhost.

### Updates (Code/Schema-Änderungen im Betrieb)

```bash
cd /srv/zeiterfassung
git pull                                   # main aktualisieren
# DB-Backup VOR Schema-Änderungen:
docker compose stop app
./scripts/backup-db.sh
docker compose up -d --build               # neues Image
docker compose exec app flask --app run.py db upgrade   # Migrationen (App läuft wieder, SQLite-Schema-Upgrade kurz stoppen besser:)
# sicherer: Upgrade bei gestoppter App:
#   docker compose stop app && docker compose exec app flask --app run.py db upgrade && docker compose start app
docker compose start app 2>/dev/null || true
```

**Rollback:** DB-Backup aus `backups/` zurückkopieren (`docker compose stop app`, Datei tauschen, `start`) + altes Image deployen (`docker tag` vor Updates vergeben, z. B. `zeiterfassung:v1`).

### Backups (automatisch)

`scripts/backup-db.sh` sichert die SQLite-DB **online** (konsistent, auch bei laufender App) nach `backups/`
und behält die letzten 30. Als Cron (täglich 03:00 Uhr):

```bash
0 3 * * * /srv/zeiterfassung/scripts/backup-db.sh >> /var/log/zeiterfassung-backup.log 2>&1
```

Zusätzlich empfohlen: Backups regelmäßig extern wegkopieren (z. B. per `rclone`/`scp` auf anderen Server/Cloud),
starke Passwörter, DSGVO-konforme Löschung von Konten auf Wunsch.

### Hinweise

- SQLite läuft mit **1 Gunicorn-Worker** (im Dockerfile fest eingestellt). Bei mehr gleichzeitigen Nutzern:
  `DATABASE_URL=postgres://...` in `.env` setzen — kein Code-Änderung nötig.
- `instance/` und `uploads/` liegen in Docker-Volumes (`app-data`, `app-uploads`) und überleben Container-Neustarts.

## Backup-Strategie

**Was wird gesichert** (`scripts/backup-db.sh`):
- `instance/zeiterfassung.db` — **online & konsistent** (sqlite3-Backup-API, App läuft weiter), danach `PRAGMA integrity_check`, Rechte `600`
- `uploads/` (hochgeladene Stempeluhr-Excel-Rohdaten) als `uploads_<timestamp>.tar.gz`
- Ablage: `backups/` lokal (Rotation: letzte 30), **Offsite** via rclone (siehe unten)

**Wie oft:** lokal alle 6 h (Datei ist klein → RPO ≈ 6 h):

```bash
0 */6 * * * /srv/zeiterfassung/scripts/backup-db.sh >> /var/log/zeiterfassung-backup.log 2>&1
```

**Offsite: OneDrive (Microsoft 365) via rclone**

```bash
# einmalig auf dem Server:
apt install rclone            # oder: curl https://rclone.org/install.sh | sudo bash
rclone config                 # -> "n" (neu) -> Typ "onedrive" -> im Browser anmelden -> Token wird gespeichert
rclone listremotes            # prüfen: "onedrive:"
# in .env eintragen:  BACKUP_REMOTE=onedrive:Zeiterfassung-Backups
rclone copy /srv/zeiterfassung/backups onedrive:Zeiterfassung-Backups   # erster manueller Test
```

Danach kopiert `backup-db.sh` jedes neue Backup automatisch in die Cloud (log in `backups/rclone.log`).
Andere Clouds (Azure Blob, S3, Nextcloud …) funktionieren genauso über das jeweilige rclone-Backend.

**3-2-1-Regel:** 3 Kopien (DB im Volume + lokale Backups + OneDrive), 2 Medien (Server + Cloud), 1 offsite (Cloud) ✅

**Restore testen (wichtig!):** mindestens monatlich auf einem Testsystem:

```bash
./scripts/restore-db.sh backups/zeiterfassung_<datum>.db
# -> prüft integrity_check, stoppt die App (docker compose), sichert alte DB als .pre-restore.*, spielt Backup ein, startet neu
```

**Vor Schema-Migrationen** immer Backup machen (siehe Produktion → Updates).

**Optional härten:** Backups vor dem Cloud-Upload verschlüsseln, z. B. `age` oder `gpg` (Key nur lokal/offline aufbewahren) — wegen personenbezogener Daten + Passwort-Hashes in der DB empfohlen.

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
