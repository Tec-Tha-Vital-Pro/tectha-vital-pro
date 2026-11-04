#!/usr/bin/env bash
# Tec Tha Vital - one-command demo on a Mac or Linux laptop.
#
#   ./scripts/setup-and-run-demo.sh                 set up, load sample data, start, open the browser
#   ./scripts/setup-and-run-demo.sh --keep-data     do not reload the sample data
#   ./scripts/setup-and-run-demo.sh --fresh         delete the demo database first (also removes the demo login)
#   ./scripts/setup-and-run-demo.sh --port 8010 --no-browser
#
# What it does: creates .venv, installs requirements, loads sample data for two branches,
# creates an admin login called "demo", starts the server on http://127.0.0.1:<port> and opens it.
# WhatsApp is forced to simulator mode: nothing is sent to real phones.
# The demo uses its own database (data/demo.db) so a real database is never wiped by accident.
# Stop the server with Ctrl+C.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${TT_PORT:-8000}"
OPEN_BROWSER=1
SEED=1
FRESH=0
ADMIN_USER="${TT_DEMO_USER:-demo}"

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-browser) OPEN_BROWSER=0; shift ;;
    --keep-data) SEED=0; shift ;;
    --fresh) FRESH=1; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done
[ "${TT_NO_BROWSER:-}" = "1" ] && OPEN_BROWSER=0

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# ---- 1. Python 3.11 or newer
PY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/ (Mac: 'brew install python@3.12'; Ubuntu: 'sudo apt install python3 python3-venv') and run this again."
say "Using $("$PY" --version) ($(command -v "$PY"))"

# ---- 2. Virtual environment and requirements (re-installed only when requirements.txt changes)
if [ ! -x .venv/bin/python ]; then
  say "Creating virtual environment in .venv"
  "$PY" -m venv .venv || fail "Could not create .venv. On Ubuntu/Debian run: sudo apt install python3-venv"
fi
VPY="$ROOT/.venv/bin/python"
REQ_HASH="$("$VPY" -c 'import hashlib,sys; print(hashlib.sha256(open("requirements.txt","rb").read()).hexdigest())')"
if [ "$(cat .venv/.tt-requirements.sha256 2>/dev/null || true)" != "$REQ_HASH" ]; then
  say "Installing requirements (first run takes a minute or two)"
  "$VPY" -m pip install --disable-pip-version-check -q --upgrade pip
  "$VPY" -m pip install --disable-pip-version-check -q -r requirements.txt
  echo "$REQ_HASH" > .venv/.tt-requirements.sha256
else
  say "Requirements already installed"
fi

# ---- 3. Demo settings (never live WhatsApp from this script)
export TT_DB_PATH="${TT_DB_PATH:-$ROOT/data/demo.db}"
if [ "${TT_WHATSAPP_MODE:-simulator}" != "simulator" ]; then
  fail "TT_WHATSAPP_MODE is '${TT_WHATSAPP_MODE}'. This demo script only runs in simulator mode. Unset it and try again."
fi
export TT_WHATSAPP_MODE=simulator
# A fresh random cookie secret each run (staff simply log in again after a restart).
export TT_SESSION_SECRET="${TT_SESSION_SECRET:-$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(32))')}"
mkdir -p "$(dirname "$TT_DB_PATH")"

if [ "$FRESH" = "1" ] && [ -f "$TT_DB_PATH" ]; then
  say "Deleting demo database $TT_DB_PATH"
  rm -f "$TT_DB_PATH" "$TT_DB_PATH-journal" "$TT_DB_PATH-wal" "$TT_DB_PATH-shm"
fi

# ---- 4. Sample data
if [ "$SEED" = "1" ] || [ ! -f "$TT_DB_PATH" ]; then
  say "Loading sample data for two branches into $TT_DB_PATH (staff logins are kept)"
  "$VPY" -m app.seed
fi

# ---- 5. Admin login
USER_EXISTS="$("$VPY" -c 'import sys; from app import db; db.init_db(); print(1 if db.one("SELECT id FROM users WHERE username = ?", (sys.argv[1].lower(),)) else 0)' "$ADMIN_USER")"
SHOW_PASSWORD=""
if [ "$USER_EXISTS" = "1" ]; then
  say "Login '$ADMIN_USER' already exists in this demo database; use the password you chose before."
  echo "    Forgot it? Run again with --fresh to start over with a new password."
else
  PASSWORD="${TT_ADMIN_PASSWORD:-}"
  if [ -z "$PASSWORD" ] && [ -t 0 ]; then
    echo
    echo "Choose a password for the demo login '$ADMIN_USER' (at least 8 characters)."
    echo "Press Enter without typing anything to get a random password instead."
    while :; do
      read -r -s -p "Password: " PASSWORD; echo
      [ -z "$PASSWORD" ] && break
      if [ "${#PASSWORD}" -lt 8 ]; then echo "Too short, try again."; continue; fi
      read -r -s -p "Repeat password: " P2; echo
      [ "$PASSWORD" = "$P2" ] && break
      echo "The two passwords do not match, try again."
    done
  fi
  if [ -z "$PASSWORD" ]; then
    PASSWORD="$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(12))')"
    SHOW_PASSWORD="$PASSWORD"
  fi
  TT_ADMIN_PASSWORD="$PASSWORD" "$VPY" -m app.auth create-admin "$ADMIN_USER" "Demo Admin"
  unset PASSWORD P2
fi

URL="http://127.0.0.1:$PORT"

# ---- 6. Open the browser once the server answers
if [ "$OPEN_BROWSER" = "1" ]; then
  (
    "$VPY" - "$URL" <<'PYEOF' || exit 0
import sys, time, urllib.request
url = sys.argv[1]
for _ in range(60):
    try:
        urllib.request.urlopen(url + "/api/health", timeout=2); sys.exit(0)
    except Exception:
        time.sleep(0.5)
sys.exit(1)
PYEOF
    if command -v open >/dev/null 2>&1 && [ "$(uname)" = "Darwin" ]; then open "$URL/login"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL/login" >/dev/null 2>&1 || true
    fi
  ) &
fi

# ---- 7. Start
echo
echo "------------------------------------------------------------------"
echo " Tec Tha Vital demo"
echo "   Open:      $URL/login"
echo "   Login:     $ADMIN_USER"
if [ -n "$SHOW_PASSWORD" ]; then
echo "   Password:  $SHOW_PASSWORD   (random, shown only once; not saved anywhere)"
fi
echo "   Database:  $TT_DB_PATH   (sample data, WhatsApp simulator)"
echo "   Stop:      Ctrl+C"
echo "------------------------------------------------------------------"
echo
# One worker only: the automation scheduler runs inside the server process.
exec "$VPY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --workers 1
