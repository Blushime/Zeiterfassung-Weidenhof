#!/usr/bin/env bash
# Backup der SQLite-Datenbank — auch bei laufender App sicher (sqlite3 Online-Backup-API).
# Nutzung: ./scripts/backup-db.sh   (Backup landet in backups/, letzte 30 werden behalten)
# Cron (täglich 03:00):  0 3 * * * /srv/zeiterfassung/scripts/backup-db.sh >> /var/log/zeiterfassung-backup.log 2>&1
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB="$BASE_DIR/instance/zeiterfassung.db"
BACKUP_DIR="$BASE_DIR/backups"
KEEP="${KEEP:-30}"

if [ ! -f "$DB" ]; then
    echo "Keine Datenbank gefunden: $DB" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$BACKUP_DIR/zeiterfassung_${STAMP}.db"

python3 - "$DB" "$DEST" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)   # konsistentes Online-Backup
src.close()
dst.close()
PY

# alte Backups rotieren
ls -1t "$BACKUP_DIR"/zeiterfassung_*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "Backup erstellt: $DEST ($(du -h "$DEST" | cut -f1))"
