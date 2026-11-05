"""Two-step login for staff: TOTP (RFC 6238, works with Google Authenticator, Microsoft Authenticator,
Authy) and one-time recovery codes.

The secret is stored when enrolment starts but only counts once the user proves it with a code.
Each 30-second step can be used once (no replay). Recovery codes are stored as hashes and work once.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from app import audit, config, db, util

STEP = 30
DIGITS = 6
WINDOW = 1                  # accept the previous and next step too (phone clocks drift)
RECOVERY_CODES = 10


# ---------------------------------------------------------------- TOTP maths

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return f"{code:0{DIGITS}d}"


def totp(secret: str, at: float | None = None) -> str:
    return hotp(secret, int((at if at is not None else time.time()) // STEP))


def _matching_step(secret: str, code: str, at: float | None = None) -> int | None:
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = int((at if at is not None else time.time()) // STEP)
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if hmac.compare_digest(hotp(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, username: str) -> str:
    issuer = config.PRODUCT_NAME
    label = quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


def qr_svg_data_uri(text: str) -> str | None:
    """QR code as an SVG data URI (segno, pure Python). None if segno is not installed."""
    try:
        import segno
    except ImportError:
        return None
    return segno.make(text, error="m").svg_data_uri(scale=5, border=2)


# ---------------------------------------------------------------- enrolment and checks

def start_enrolment(user_id: int, actor: str) -> str:
    """Create a fresh secret (two-step login stays off until confirm_enrolment succeeds)."""
    u = db.one("SELECT totp_enabled FROM users WHERE id = ?", (user_id,))
    if u is None:
        raise LookupError("User not found")
    if u["totp_enabled"]:
        raise ValueError("Two-step login is already on. Turn it off first to set up a new phone.")
    secret = new_secret()
    db.execute("UPDATE users SET totp_secret = ?, totp_last_step = 0 WHERE id = ?", (secret, user_id))
    audit.log(actor, "totp_enrolment_started", "user", user_id)
    return secret


def confirm_enrolment(user_id: int, code: str, actor: str) -> list[str]:
    """Turn two-step login on after a valid code. Returns the recovery codes (shown once)."""
    u = db.one("SELECT totp_secret, totp_enabled FROM users WHERE id = ?", (user_id,))
    if u is None or not u["totp_secret"]:
        raise ValueError("Start the set-up again: no authenticator was being added.")
    step = _matching_step(u["totp_secret"], code)
    if step is None:
        raise ValueError("That code didn't match. Check the phone's time is set automatically and try the newest code.")
    db.execute("UPDATE users SET totp_enabled = 1, totp_last_step = ? WHERE id = ?", (step, user_id))
    audit.log(actor, "totp_enabled", "user", user_id)
    return new_recovery_codes(user_id, actor)


def verify(user_id: int, code: str) -> bool:
    """Check a login code: a fresh TOTP step, or an unused recovery code."""
    u = db.one("SELECT totp_secret, totp_enabled, totp_last_step FROM users WHERE id = ?", (user_id,))
    if u is None or not u["totp_enabled"]:
        return False
    step = _matching_step(u["totp_secret"], code)
    if step is not None:
        if step <= u["totp_last_step"]:
            return False                     # this code was already used
        db.execute("UPDATE users SET totp_last_step = ? WHERE id = ?", (step, user_id))
        return True
    return use_recovery_code(user_id, code)


def disable(user_id: int, actor: str) -> None:
    db.execute("UPDATE users SET totp_enabled = 0, totp_secret = NULL, totp_last_step = 0 WHERE id = ?", (user_id,))
    db.execute("DELETE FROM user_recovery_codes WHERE user_id = ?", (user_id,))
    audit.log(actor, "totp_disabled", "user", user_id)


# ---------------------------------------------------------------- recovery codes

def _hash(code: str) -> str:
    norm = "".join(ch for ch in code.lower() if ch.isalnum())
    return hmac.new(config.settings.session_secret.encode(), norm.encode(), hashlib.sha256).hexdigest()


def new_recovery_codes(user_id: int, actor: str) -> list[str]:
    """Replace this user's recovery codes. The plain codes are returned once and never stored."""
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_CODES)]
    now = util.ts(util.now())
    db.execute("DELETE FROM user_recovery_codes WHERE user_id = ?", (user_id,))
    for c in codes:
        db.execute("INSERT INTO user_recovery_codes(user_id, code_hash, created_at) VALUES (?,?,?)",
                   (user_id, _hash(c), now))
    audit.log(actor, "recovery_codes_created", "user", user_id, {"count": len(codes)})
    return codes


def use_recovery_code(user_id: int, code: str) -> bool:
    if not code or len("".join(ch for ch in code if ch.isalnum())) < 8:
        return False
    row = db.one("SELECT id FROM user_recovery_codes WHERE user_id = ? AND code_hash = ? AND used_at IS NULL",
                 (user_id, _hash(code)))
    if row is None:
        return False
    db.execute("UPDATE user_recovery_codes SET used_at = ? WHERE id = ?", (util.ts(util.now()), row["id"]))
    audit.log(f"user:{user_id}", "recovery_code_used", "user", user_id)
    return True


def recovery_codes_left(user_id: int) -> int:
    return db.scalar("SELECT COUNT(*) FROM user_recovery_codes WHERE user_id = ? AND used_at IS NULL", (user_id,)) or 0
