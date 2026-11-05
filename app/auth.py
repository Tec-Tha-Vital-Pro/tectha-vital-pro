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
import time
from datetime import timedelta

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import audit, config, db, security, util

COOKIE = "tt_session"
MAX_AGE = 8 * 60 * 60
ITERATIONS = 200_000
ROLES = ("admin", "owner", "doctor", "nurse", "frontdesk", "billing", "lab", "pharmacy")
ROLE_LABELS = {"admin": "Admin", "owner": "Owner", "doctor": "Doctor", "nurse": "Nurse", "frontdesk": "Front desk",
               "billing": "Billing / insurance", "lab": "Lab / radiology", "pharmacy": "Pharmacy"}

# Who may open which screen.
ADMIN = {"admin"}
OWNER_VIEW = {"admin", "owner"}             # dashboard and reports
FRONT = {"admin", "frontdesk"}
CLINICAL = {"admin", "frontdesk", "doctor", "nurse"}   # appointments, patient records
BILLING = {"admin", "billing"}              # change bills, payments, claims
BILLING_VIEW = BILLING | {"owner"}          # read billing and claims (the owner is read-only)
LAB = {"admin", "lab", "doctor"}            # lab and radiology worklists
PHARMACY = {"admin", "pharmacy"}            # dispensing and stock
STAFF = set(ROLES)

# Staff login throttling (S-07): this many failures per username + IP inside the window -> 429.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW = timedelta(minutes=15)

# Shared terminals: a staff session ends after this many minutes without any request (TT_STAFF_IDLE_MINUTES).
IDLE_MINUTES = int(os.environ.get("TT_STAFF_IDLE_MINUTES", "15"))
REFRESH_AFTER_SECONDS = 60      # how often an active session's idle clock is pushed forward

# Two-step login. Pages a user may still open while their role requires 2FA they haven't set up.
TWO_FACTOR_SETUP_PATHS = ("/account", "/logout", "/login")


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


class TwoFactorSetupRequired(Exception):
    """The user's role requires two-step login and they haven't set it up yet."""


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


def _epoch() -> int:
    return int(time.time())


def make_session(user_id: int, version: int = 0, *, csrf: str | None = None, issued: int | None = None) -> str:
    """Cookie payload: user, session version, CSRF token, issued-at and last-activity (for the idle timeout)."""
    now = _epoch()
    return _serializer().dumps({"u": user_id, "v": version, "c": csrf or secrets.token_urlsafe(24),
                                "i": issued or now, "t": now})


def set_session_cookie(response, request: Request, user_id: int, *, csrf: str | None = None,
                       issued: int | None = None) -> None:
    version = db.scalar("SELECT session_version FROM users WHERE id = ?", (user_id,)) or 0
    response.set_cookie(COOKIE, make_session(user_id, version, csrf=csrf, issued=issued), max_age=MAX_AGE,
                        httponly=True, samesite="lax", secure=security.is_https(request), path="/")


def _session_data(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    now = _epoch()
    if now - int(data.get("i", 0)) > MAX_AGE:          # absolute limit, however active the session is
        return None
    if IDLE_MINUTES > 0 and now - int(data.get("t", 0)) > IDLE_MINUTES * 60:
        return None                                    # idle too long on a shared terminal
    return data


class SessionRefresh:
    """ASGI middleware: pushes an active staff session's idle clock forward (at most once a minute).

    Skipped when the response sets or deletes the session cookie itself (login, logout, sign-out-others).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        data = _session_data(request)
        stale = data is not None and _epoch() - int(data.get("t", 0)) >= REFRESH_AFTER_SECONDS

        async def wrapped_send(message):
            if stale and message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                sets_own = any(k.lower() == b"set-cookie" and v.startswith(COOKIE.encode() + b"=") for k, v in headers)
                if not sets_own:
                    v = db.scalar("SELECT session_version FROM users WHERE id = ? AND active = 1", (data["u"],))
                    if v is not None and v == data.get("v"):
                        cookie = make_session(data["u"], v, csrf=data["c"], issued=data.get("i"))
                        attrs = f"{COOKIE}={cookie}; Max-Age={MAX_AGE}; Path=/; HttpOnly; SameSite=lax"
                        if security.is_https(request):
                            attrs += "; Secure"
                        headers.append((b"set-cookie", attrs.encode()))
            await send(message)

        await self.app(scope, receive, wrapped_send)


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
    data = _session_data(request)
    if data is None:
        return None
    u = db.one("SELECT id, username, full_name, role, branch_id, session_version, totp_enabled FROM users"
               " WHERE id = ? AND active = 1", (data.get("u"),))
    if u is None or data.get("v") != u["session_version"]:
        return None  # deactivated, logged out, or password changed since this cookie was issued
    u["csrf"] = data["c"]
    u["issued"] = data.get("i")
    return u


def two_factor_required_roles() -> set[str]:
    raw = db.get_setting("require_2fa_roles", "")
    return {r for r in raw.split(",") if r in ROLES}


def needs_two_factor_setup(user: dict) -> bool:
    return user["role"] in two_factor_required_roles() and not user.get("totp_enabled")


def require(request: Request, roles: set[str]) -> dict:
    user = current_user(request)
    if user is None:
        raise LoginRequired()
    if needs_two_factor_setup(user) and not request.url.path.startswith(TWO_FACTOR_SETUP_PATHS):
        raise TwoFactorSetupRequired()
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
