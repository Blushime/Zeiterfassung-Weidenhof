#!/usr/bin/env bash
# Backup: SQLite-DB (online, konsistent) + Uploads (tar.gz) -> backups/
# Optional: Offsite-Kopie via rclone (BACKUP_REMOTE in .env, z. B. onedrive:Zeiterfassung-Backups)
#
# Nutzung:  ./scripts/backup-db.sh
# Cron (lokal alle 6 h):  0 */6 * * * /srv/zeiterfassung/scripts/backup-db.sh >> /var/log/zeiterfassung-backup.log 2>&1
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB="$BASE_DIR/instance/zeiterfassung.db"
UPLOADS_DIR="$BASE_DIR/uploads"
BACKUP_DIR="$BASE_DIR/backups"
KEEP="${KEEP:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"

# .env laden (optional — dort kann BACKUP_REMOTE stehen)
if [ -f "$BASE_DIR/.env" ]; then
    set -a; . "$BASE_DIR/.env"; set +a
fi
BACKUP_REMOTE="${BACKUP_REMOTE:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

mkdir -p "$BACKUP_DIR"

# --- 1. Datenbank-Backup (online & konsistent, auch bei laufender App) ---
if [ -f "$DB" ]; then
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
    chmod 600 "$DEST"
    CHECK="$(python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0])" "$DEST")"
    log "DB-Backup: $DEST (integrity_check: $CHECK)"
    [ "$CHECK" = "ok" ] || log "WARNUNG: integrity_check ergab '$CHECK'!"
else
    log "WARNUNG: keine DB gefunden unter $DB"
fi

# --- 2. Uploads (Stempeluhr-Excel-Rohdaten) sichern ---
if [ -d "$UPLOADS_DIR" ] && [ -n "$(ls -A "$UPLOADS_DIR" 2>/dev/null)" ]; then
    TAR="$BACKUP_DIR/uploads_${STAMP}.tar.gz"
    tar -czf "$TAR" -C "$BASE_DIR" uploads
    chmod 600 "$TAR"
    log "Uploads-Backup: $TAR ($(du -h "$TAR" | cut -f1))"
fi

# --- 3. Rotation (lokal, letzte KEEP) ---
ls -1t "$BACKUP_DIR"/zeiterfassung_*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
ls -1t "$BACKUP_DIR"/uploads_*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

# --- 4. Offsite via rclone (z. B. OneDrive/Microsoft 365) ---
if [ -n "$BACKUP_REMOTE" ]; then
    if command -v rclone >/dev/null 2>&1; then
        if rclone copy "$BACKUP_DIR" "$BACKUP_REMOTE" --log-file "$BACKUP_DIR/rclone.log" 2>>"$BACKUP_DIR/rclone.err"; then
            log "Offsite-Kopie nach $BACKUP_REMOTE OK"
        else
            log "WARNUNG: Offsite-Kopie fehlgeschlagen (siehe $BACKUP_DIR/rclone.err)"
        fi
    else
        log "Hinweis: BACKUP_REMOTE='$BACKUP_REMOTE' gesetzt, aber rclone nicht installiert -> nur lokal gesichert"
    fi
fi

log "Backup-Lauf fertig."
