#!/usr/bin/env bash
# Restore der SQLite-DB aus einem Backup (mit Integritätsprüfung).
# Stoppt die App (docker compose, falls vorhanden), sichert die aktuelle DB, spielt das Backup ein, startet neu.
#
# Nutzung:  ./scripts/restore-db.sh backups/zeiterfassung_20260101_030000.db
#           ./scripts/restore-db.sh            (zeigt die neuesten Backups zur Auswahl)
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB="$BASE_DIR/instance/zeiterfassung.db"
BACKUP="${1:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if [ -z "$BACKUP" ]; then
    echo "Nutzung: $0 <backup-datei>" >&2
    echo "Neueste Backups:" >&2
    ls -1t "$BASE_DIR/backups"/zeiterfassung_*.db 2>/dev/null | head -5 >&2
    exit 1
fi
if [ ! -f "$BACKUP" ]; then
    echo "Backup nicht gefunden: $BACKUP" >&2
    exit 1
fi

# Integrität des Backups prüfen — defektes Backup niemals einspielen
CHECK="$(python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0])" "$BACKUP")"
if [ "$CHECK" != "ok" ]; then
    echo "ABBRUCH: Backup ist defekt (integrity_check=$CHECK): $BACKUP" >&2
    exit 1
fi

# App stoppen (docker compose, falls vorhanden)
DOCKER_MODE=0
if command -v docker >/dev/null 2>&1 && [ -f "$BASE_DIR/docker-compose.yml" ] && docker compose version >/dev/null 2>&1; then
    (cd "$BASE_DIR" && docker compose stop app) && DOCKER_MODE=1 && log "App gestoppt (docker compose)"
else
    log "Hinweis: kein docker compose gefunden — App ggf. manuell stoppen (Ctrl+C / systemctl), dann Enter"
    read -r _ || true
fi

mkdir -p "$BASE_DIR/instance"
# aktuelle DB als Fallback sichern
if [ -f "$DB" ]; then
    cp "$DB" "$DB.pre-restore.$(date +%Y%m%d_%H%M%S)"
    log "aktuelle DB gesichert als: $DB.pre-restore.*"
fi

cp "$BACKUP" "$DB"
chmod 600 "$DB"
log "DB wiederhergestellt aus: $BACKUP"

if [ "$DOCKER_MODE" = "1" ]; then
    (cd "$BASE_DIR" && docker compose start app) && log "App gestartet (docker compose)"
else
    log "Bitte App manuell neu starten (z. B. python run.py bzw. docker compose up -d)"
fi
log "Restore fertig."
