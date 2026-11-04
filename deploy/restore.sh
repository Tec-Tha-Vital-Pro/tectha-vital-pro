#!/usr/bin/env bash
# Restore (or test-restore) a Tec Tha backup made by deploy/backup.sh.
#
#   deploy/restore.sh --test  /var/backups/tectha-care/tectha-20261104-023000.db.gz
#       Unpacks into a temp file, runs integrity_check and prints row counts. Touches nothing live.
#       Do this once a month (see docs/RUNBOOK.md).
#
#   deploy/restore.sh --restore /var/backups/tectha-care/tectha-20261104-023000.db.gz
#       Replaces TT_DB_PATH with the backup. STOP THE APP FIRST
#       (sudo systemctl stop tectha-care   or   docker compose stop app).
#       The current database is kept next to it as <db>.before-restore-<time>.
#
# Encrypted backups (.age): set TT_BACKUP_AGE_IDENTITY=/path/to/key.txt
# PYTHON=... chooses the Python to use (default python3).
set -euo pipefail
umask 077

MODE="${1:-}"; FILE="${2:-}"
[ "$MODE" = "--test" ] || [ "$MODE" = "--restore" ] || { sed -n '2,16p' "$0"; exit 2; }
[ -f "$FILE" ] || { echo "restore: backup file not found: $FILE" >&2; exit 1; }
DB="${TT_DB_PATH:-$(cd "$(dirname "$0")/.." && pwd)/data/tectha.db}"
PY="${PYTHON:-python3}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
CANDIDATE="$WORK/restore.db"

case "$FILE" in
  *.age)
    [ -n "${TT_BACKUP_AGE_IDENTITY:-}" ] || { echo "restore: set TT_BACKUP_AGE_IDENTITY to the age key file" >&2; exit 1; }
    age -d -i "$TT_BACKUP_AGE_IDENTITY" "$FILE" | gunzip -c > "$CANDIDATE" ;;
  *.gz) gunzip -c "$FILE" > "$CANDIDATE" ;;
  *) cp "$FILE" "$CANDIDATE" ;;
esac

"$PY" - "$CANDIDATE" <<'PYEOF'
import sqlite3, sys
d = sqlite3.connect(sys.argv[1])
ok = d.execute("PRAGMA integrity_check").fetchone()[0]
if ok != "ok":
    sys.exit(f"restore: integrity_check FAILED: {ok}")
for t in ("patients", "appointments", "bills", "payments", "messages", "audit_log", "users"):
    print(f"  {t:13} {d.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
last = d.execute("SELECT MAX(created_at) FROM audit_log").fetchone()[0]
print(f"  last audit entry: {last}")
print("restore: backup is readable and passes integrity_check")
PYEOF

if [ "$MODE" = "--test" ]; then
  echo "restore: test only, live database not touched"
  exit 0
fi

# Refuse if something still has the database open (best effort; fuser may be missing).
if command -v fuser >/dev/null 2>&1 && [ -f "$DB" ] && fuser "$DB" >/dev/null 2>&1; then
  echo "restore: $DB is still open by a running process. Stop the app first." >&2
  exit 1
fi

if [ -f "$DB" ]; then
  KEEP="$DB.before-restore-$(date +%Y%m%d-%H%M%S)"
  mv "$DB" "$KEEP"
  echo "restore: previous database kept as $KEEP"
fi
rm -f "$DB-journal" "$DB-wal" "$DB-shm"
mkdir -p "$(dirname "$DB")"
cp "$CANDIDATE" "$DB"
chmod 600 "$DB"
echo "restore: restored $FILE -> $DB"
echo "restore: check ownership (e.g. sudo chown tectha:tectha \"$DB\"), then start the app and log in."
