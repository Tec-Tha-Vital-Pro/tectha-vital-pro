#!/usr/bin/env bash
# Nightly backup of the Tec Tha SQLite database.
#
#   deploy/backup.sh                       uses TT_DB_PATH and TT_BACKUP_DIR from the environment
#   TT_DB_PATH=/var/lib/tectha-care/tectha.db TT_BACKUP_DIR=/var/backups/tectha-care deploy/backup.sh
#
# Safe while the app is running: it uses SQLite's online backup API (a consistent copy, never a
# half-written file), checks the copy with PRAGMA integrity_check, compresses it, and deletes
# backups older than TT_BACKUP_KEEP_DAYS (default 30).
#
# Optional:
#   TT_BACKUP_AGE_RECIPIENT=age1...   encrypt the backup with `age` (recommended before copying off the server)
#   TT_BACKUP_RCLONE_REMOTE=remote:path   copy the finished file off the server with `rclone copy`
#   PYTHON=/opt/tectha-care/.venv/bin/python   which Python to use (default python3)
# Exit code is non-zero on any failure, so cron mails you / the healthcheck sees it.
set -euo pipefail
umask 077

DB="${TT_DB_PATH:-$(cd "$(dirname "$0")/.." && pwd)/data/tectha.db}"
DEST="${TT_BACKUP_DIR:-$(dirname "$DB")/backups}"
KEEP_DAYS="${TT_BACKUP_KEEP_DAYS:-30}"
PY="${PYTHON:-python3}"

[ -f "$DB" ] || { echo "backup: database not found: $DB" >&2; exit 1; }
mkdir -p "$DEST"
chmod 700 "$DEST"

STAMP="$(date +%Y%m%d-%H%M%S)"
TMP="$DEST/.tectha-$STAMP.db.partial"
OUT="$DEST/tectha-$STAMP.db.gz"
trap 'rm -f "$TMP" "$TMP.gz"' EXIT

# Free space check: need at least 2x the database size.
DB_KB=$(du -k "$DB" | cut -f1)
FREE_KB=$(df -Pk "$DEST" | awk 'NR==2 {print $4}')
if [ "$FREE_KB" -lt $((DB_KB * 2)) ]; then
  echo "backup: not enough free space in $DEST (${FREE_KB} KB free, need $((DB_KB * 2)) KB)" >&2
  exit 1
fi

"$PY" - "$DB" "$TMP" <<'PYEOF'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
d = sqlite3.connect(dst)
s.backup(d)
s.close()
ok = d.execute("PRAGMA integrity_check").fetchone()[0]
counts = {t: d.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("patients", "bills", "messages", "audit_log", "users")}
d.close()
if ok != "ok":
    sys.exit(f"backup: integrity_check failed on the copy: {ok}")
print("backup: copy ok, rows " + ", ".join(f"{k}={v}" for k, v in counts.items()))
PYEOF

gzip -9 "$TMP"
if [ -n "${TT_BACKUP_AGE_RECIPIENT:-}" ]; then
  command -v age >/dev/null || { echo "backup: TT_BACKUP_AGE_RECIPIENT is set but 'age' is not installed" >&2; exit 1; }
  OUT="$OUT.age"
  age -r "$TT_BACKUP_AGE_RECIPIENT" -o "$OUT" "$TMP.gz"
  rm -f "$TMP.gz"
else
  mv "$TMP.gz" "$OUT"
fi
chmod 600 "$OUT"
echo "backup: wrote $OUT ($(du -h "$OUT" | cut -f1))"

if [ -n "${TT_BACKUP_RCLONE_REMOTE:-}" ]; then
  rclone copy "$OUT" "$TT_BACKUP_RCLONE_REMOTE" && echo "backup: copied to $TT_BACKUP_RCLONE_REMOTE"
fi

find "$DEST" -maxdepth 1 -name 'tectha-*.db.gz*' -mtime +"$KEEP_DAYS" -print -delete | sed 's/^/backup: deleted old /'
