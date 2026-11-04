#!/usr/bin/env bash
# Quick health check for cron or by hand. Prints one line per check; exits 1 if anything is wrong.
#
#   deploy/healthcheck.sh
#   TT_URL=http://127.0.0.1:8000 TT_DB_PATH=/var/lib/tectha-care/tectha.db deploy/healthcheck.sh
#
# Checks: the app answers /api/health; free disk space; the database opens; failed WhatsApp sends,
# automation errors and the newest automation activity in the last 24 hours (from the audit log).
# Optional: TT_HEALTHCHECK_PING_URL (e.g. a free healthchecks.io check) is pinged on success, and
# "<url>/fail" on failure, so you get an email when the server is down.
set -uo pipefail

URL="${TT_URL:-http://127.0.0.1:8000}"
DB="${TT_DB_PATH:-$(cd "$(dirname "$0")/.." && pwd)/data/tectha.db}"
MIN_FREE_MB="${TT_MIN_FREE_MB:-1024}"
PY="${PYTHON:-python3}"
BAD=0

if curl -fsS -m 10 "$URL/api/health" >/dev/null 2>&1; then echo "OK   app answers $URL/api/health"
else echo "FAIL app does not answer $URL/api/health"; BAD=1; fi

FREE_MB=$(df -Pm "$(dirname "$DB")" | awk 'NR==2 {print $4}')
if [ "$FREE_MB" -ge "$MIN_FREE_MB" ]; then echo "OK   disk free ${FREE_MB} MB"
else echo "FAIL disk free only ${FREE_MB} MB (limit ${MIN_FREE_MB} MB)"; BAD=1; fi

"$PY" - "$DB" <<'PYEOF' || BAD=1
import sqlite3, sys
from datetime import datetime, timedelta, timezone
ist = datetime.now(timezone(timedelta(hours=5, minutes=30))).replace(tzinfo=None)
since = (ist - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
try:
    d = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=10)
    q = lambda sql, *a: d.execute(sql, a).fetchone()[0]
    failed = q("SELECT COUNT(*) FROM messages WHERE status='failed' AND created_at >= ?", since)
    errors = q("SELECT COUNT(*) FROM audit_log WHERE action='automation_error' AND created_at >= ?", since)
    last_auto = q("SELECT MAX(created_at) FROM audit_log WHERE actor='automation'")
except sqlite3.Error as e:
    print(f"FAIL database {sys.argv[1]}: {e}"); sys.exit(1)
bad = False
print(("OK  " if failed == 0 else "WARN") + f" failed WhatsApp sends in last 24 h: {failed}")
print(("OK  " if errors == 0 else "FAIL") + f" automation errors in last 24 h: {errors}")
bad |= errors > 0
print(f"INFO newest automation activity in audit log: {last_auto or 'none'} (IST)")
sys.exit(1 if bad else 0)
PYEOF

if [ -n "${TT_HEALTHCHECK_PING_URL:-}" ]; then
  if [ "$BAD" = 0 ]; then curl -fsS -m 10 "$TT_HEALTHCHECK_PING_URL" >/dev/null || true
  else curl -fsS -m 10 "$TT_HEALTHCHECK_PING_URL/fail" >/dev/null || true; fi
fi
exit $BAD
