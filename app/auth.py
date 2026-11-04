"""Staff logins: password hashing, signed session cookie, role checks.

CLI:  python -m app.auth create-admin <username> "<full name>"
          (password from TT_ADMIN_PASSWORD, otherwise prompted)
      python -m app.auth reset-password <username>
          (new password from TT_NEW_PASSWORD, otherwise prompted; ends that user's sessions)
      python -m app.auth deactivate <username>
          (the login stops working at once, including open sessions)
"""
import getpass
import hashlib
import hmac
import os
import secrets
import sys
from datetime import timedelta

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import audit, config, db, security, util

COOKIE = "tt_session"
MAX_AGE = 8 * 60 * 60
ITERATIONS = 200_000
ROLES = ("admin", "owner", "frontdesk", "billing", "doctor")

# Who may open which screen.
ADMIN = {"admin"}
OWNER_VIEW = {"admin", "owner"}             # dashboard and reports
FRONT = {"admin", "frontdesk"}
CLINICAL = {"admin", "frontdesk", "doctor"}
BILLING = {"admin", "billing"}              # change bills, payments, claims
BILLING_VIEW = BILLING | {"owner"}          # read billing and claims (the owner is read-only)
STAFF = {"admin", "owner", "frontdesk", "billing", "doctor"}

# Staff login throttling (S-07): this many failures per username + IP inside the window -> 429.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW = timedelta(minutes=15)


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


class CsrfFailed(Exception):
    pass


class NotFound(Exception):
    """The record doesn't exist, or belongs to a branch this user can't see (same answer for both)."""

    def __init__(self, what: str = "record"):
        super().__init__(what)
        self.what = what


class TooManyAttempts(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
    return hmac.compare_digest(h.hex(), hash_hex)


def create_user(username: str, full_name: str, password: str, role: str, branch_id: str | None = None,
                actor: str = "system") -> int:
    username = username.strip().lower()
    if not username or not full_name.strip():
        raise ValueError("Username and full name are required")
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}")
    _check_password(password)
    if db.one("SELECT id FROM users WHERE username = ?", (username,)):
        raise ValueError(f"Username {username!r} already exists")
    uid = db.execute(
        "INSERT INTO users(username, full_name, password_hash, role, branch_id, created_at) VALUES (?,?,?,?,?,?)",
        (username, full_name.strip(), hash_password(password), role, branch_id or None, util.ts(util.now())),
    )
    audit.log(actor, "create", "user", uid, {"username": username, "role": role, "branch": branch_id})
    return uid


# Checked when the username doesn't exist, so a wrong username takes as long as a wrong password (S-21).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def authenticate(username: str, password: str, ip: str = "") -> dict | None:
    """Check a staff login. Raises TooManyAttempts after LOGIN_MAX_FAILURES failures per username + IP."""
    username = (username or "").strip().lower()
    key = f"{username}|{ip}"
    if security.hits("login_failed", key, LOGIN_WINDOW) >= LOGIN_MAX_FAILURES:
        audit.log(f"user:{username or '?'}", "login_throttled", "user", None, {"ip": ip})
        raise TooManyAttempts()
    u = db.one("SELECT * FROM users WHERE username = ? AND active = 1", (username,))
    ok = verify_password(password or "", u["password_hash"] if u else _DUMMY_HASH) and bool(u)
    audit.log(f"user:{username or '?'}", "login_success" if ok else "login_failed", "user", u["id"] if u else None,
              {"ip": ip} if ip else None)
    if ok:
        security.clear("login_failed", key)
        return u
    security.record("login_failed", key)
    return None


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.settings.session_secret, salt="tt-session")


def make_session(user_id: int, version: int = 0) -> str:
    return _serializer().dumps({"u": user_id, "v": version, "c": secrets.token_urlsafe(24)})


def set_session_cookie(response, request: Request, user_id: int) -> None:
    version = db.scalar("SELECT session_version FROM users WHERE id = ?", (user_id,)) or 0
    response.set_cookie(COOKIE, make_session(user_id, version), max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=security.is_https(request), path="/")


def end_sessions(user_id: int) -> None:
    """Every cookie issued so far for this user stops working (logout, password change, deactivation)."""
    db.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (user_id,))


def _check_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")


def set_password(user_id: int, password: str, actor: str) -> None:
    _check_password(password)
    u = db.one("SELECT id, username FROM users WHERE id = ?", (user_id,))
    if u is None:
        raise LookupError("User not found")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
    end_sessions(user_id)
    audit.log(actor, "password_reset", "user", user_id, {"username": u["username"]})


def set_active(user_id: int, active: bool, actor: str) -> None:
    u = db.one("SELECT id, username FROM users WHERE id = ?", (user_id,))
    if u is None:
        raise LookupError("User not found")
    db.execute("UPDATE users SET active = ? WHERE id = ?", (1 if active else 0, user_id))
    end_sessions(user_id)
    audit.log(actor, "activate" if active else "deactivate", "user", user_id, {"username": u["username"]})


def current_user(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    u = db.one("SELECT id, username, full_name, role, branch_id, session_version FROM users WHERE id = ? AND active = 1",
               (data.get("u"),))
    if u is None or data.get("v") != u["session_version"]:
        return None  # deactivated, logged out, or password changed since this cookie was issued
    u["csrf"] = data["c"]
    return u


def require(request: Request, roles: set[str]) -> dict:
    user = current_user(request)
    if user is None:
        raise LoginRequired()
    if user["role"] not in roles:
        raise Forbidden()
    return user


async def require_post(request: Request, roles: set[str]) -> dict:
    user = require(request, roles)
    form = await request.form()
    token = form.get("csrf", "")
    if not (isinstance(token, str) and hmac.compare_digest(token.encode(), user["csrf"].encode())):
        raise CsrfFailed()
    return user


def actor(user: dict) -> str:
    return f"user:{user['username']}"


def _read_password(env: str, prompt: str) -> str | None:
    password = os.environ.get(env)
    if password:
        return password
    password = getpass.getpass(prompt)
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match", file=sys.stderr)
        return None
    return password


USAGE = ('Usage: python -m app.auth create-admin <username> "<full name>"\n'
         '       python -m app.auth reset-password <username>\n'
         '       python -m app.auth deactivate <username>')


def _cli(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if not ((cmd == "create-admin" and len(argv) == 3) or (cmd in ("reset-password", "deactivate") and len(argv) == 2)):
        print(USAGE, file=sys.stderr)
        return 2
    db.init_db()
    if cmd == "create-admin":
        password = _read_password("TT_ADMIN_PASSWORD", "Password (min 8 characters): ")
        if password is None:
            return 1
        try:
            uid = create_user(argv[1], argv[2], password, "admin", actor="cli")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Admin user {argv[1]!r} created (id {uid}).")
        return 0
    username = argv[1].strip().lower()
    u = db.one("SELECT id FROM users WHERE username = ?", (username,))
    if u is None:
        print(f"Error: no user {username!r}", file=sys.stderr)
        return 1
    if cmd == "deactivate":
        set_active(u["id"], False, actor="cli")
        print(f"User {username!r} deactivated. Their open sessions have ended.")
        return 0
    password = _read_password("TT_NEW_PASSWORD", "New password (min 8 characters): ")
    if password is None:
        return 1
    try:
        set_password(u["id"], password, actor="cli")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Password for {username!r} changed. Their open sessions have ended.")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
