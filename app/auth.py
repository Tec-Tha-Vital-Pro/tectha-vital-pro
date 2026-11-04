"""Staff logins: password hashing, signed session cookie, role checks.

CLI:  python -m app.auth create-admin <username> "<full name>"
      (password from TT_ADMIN_PASSWORD, otherwise prompted)
"""
import getpass
import hashlib
import hmac
import os
import secrets
import sys

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import audit, config, db, util

COOKIE = "tt_session"
MAX_AGE = 8 * 60 * 60
ITERATIONS = 200_000
ROLES = ("admin", "frontdesk", "billing", "doctor")

# Who may open which screen.
ADMIN = {"admin"}
FRONT = {"admin", "frontdesk"}
CLINICAL = {"admin", "frontdesk", "doctor"}
BILLING = {"admin", "billing"}
STAFF = {"admin", "frontdesk", "billing", "doctor"}


class LoginRequired(Exception):
    pass


class Forbidden(Exception):
    pass


class CsrfFailed(Exception):
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
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if db.one("SELECT id FROM users WHERE username = ?", (username,)):
        raise ValueError(f"Username {username!r} already exists")
    uid = db.execute(
        "INSERT INTO users(username, full_name, password_hash, role, branch_id, created_at) VALUES (?,?,?,?,?,?)",
        (username, full_name.strip(), hash_password(password), role, branch_id or None, util.ts(util.now())),
    )
    audit.log(actor, "create", "user", uid, {"username": username, "role": role, "branch": branch_id})
    return uid


def authenticate(username: str, password: str) -> dict | None:
    username = (username or "").strip().lower()
    u = db.one("SELECT * FROM users WHERE username = ? AND active = 1", (username,))
    ok = bool(u) and verify_password(password or "", u["password_hash"])
    audit.log(f"user:{username or '?'}", "login_success" if ok else "login_failed", "user", u["id"] if u else None)
    return u if ok else None


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.settings.session_secret, salt="tt-session")


def make_session(user_id: int) -> str:
    return _serializer().dumps({"u": user_id, "c": secrets.token_urlsafe(24)})


def set_session_cookie(response, request: Request, user_id: int) -> None:
    response.set_cookie(COOKIE, make_session(user_id), max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")


def current_user(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    u = db.one("SELECT id, username, full_name, role, branch_id FROM users WHERE id = ? AND active = 1", (data.get("u"),))
    if u is None:
        return None
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
    if not (isinstance(token, str) and hmac.compare_digest(token, user["csrf"])):
        raise CsrfFailed()
    return user


def actor(user: dict) -> str:
    return f"user:{user['username']}"


def _cli(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "create-admin":
        print('Usage: python -m app.auth create-admin <username> "<full name>"', file=sys.stderr)
        return 2
    db.init_db()
    password = os.environ.get("TT_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password (min 8 characters): ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match", file=sys.stderr)
            return 1
    try:
        uid = create_user(argv[1], argv[2], password, "admin", actor="cli")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Admin user {argv[1]!r} created (id {uid}).")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
