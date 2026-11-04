"""Transport and abuse protection shared by the staff and patient apps.

- is_https / client_ip: trust proxy headers only when TT_BEHIND_PROXY=1 (the app sits behind
  Caddy or nginx that sets them). Otherwise anyone could send a fake header.
- Rate limits stored in SQLite (rate_events), so they survive a restart.
- Security headers on every response (CSP, no framing, no sniffing, HSTS on HTTPS).
"""
import os
from datetime import timedelta

from fastapi import Request

from app import db, util


def behind_proxy() -> bool:
    return os.environ.get("TT_BEHIND_PROXY", "") == "1"


def _scope_is_https(scope_headers: dict[str, str], scheme: str) -> bool:
    if scheme == "https":
        return True
    if behind_proxy():
        proto = scope_headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        return proto == "https"
    return False


def is_https(request: Request) -> bool:
    """True when the browser talks to us over HTTPS (directly, or through a trusted proxy)."""
    return _scope_is_https({k.lower(): v for k, v in request.headers.items()}, request.url.scheme)


def client_ip(request: Request) -> str:
    """The caller's IP. Behind a trusted proxy, the last X-Forwarded-For hop (the one our proxy added)."""
    if behind_proxy():
        fwd = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in fwd.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- rate limits

def hits(kind: str, key: str, window: timedelta) -> int:
    since = util.ts(util.now() - window)
    return db.scalar("SELECT COUNT(*) FROM rate_events WHERE kind = ? AND key = ? AND created_at >= ?",
                     (kind, key, since)) or 0


def record(kind: str, key: str) -> None:
    now = util.now()
    with db.connect() as conn:
        conn.execute("INSERT INTO rate_events(kind, key, created_at) VALUES (?,?,?)", (kind, key, util.ts(now)))
        # Keep the table small: nothing we check looks back more than a day.
        conn.execute("DELETE FROM rate_events WHERE created_at < ?", (util.ts(now - timedelta(days=1)),))


def clear(kind: str, key: str) -> None:
    db.execute("DELETE FROM rate_events WHERE kind = ? AND key = ?", (kind, key))


# ---------------------------------------------------------------- headers

# Pages use only same-origin scripts (no inline <script>, no on* handlers) and Google Fonts.
# style-src keeps 'unsafe-inline' because two dashboard elements set width/colour with style=""
# (chart legend, funnel bars) and offline.html has a <style> block; scripts stay strict.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

STATIC_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"content-security-policy", CSP.encode()),
]
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeaders:
    """Pure ASGI middleware (no BaseHTTPMiddleware, so streaming and background tasks are untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        req_headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        https = _scope_is_https(req_headers, scope.get("scheme", "http"))
        is_static = scope.get("path", "").startswith("/static/")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for k, v in STATIC_HEADERS:
                    if k not in present:
                        headers.append((k, v))
                if https and HSTS[0] not in present:
                    headers.append(HSTS)
                ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if not is_static and ctype.startswith(b"text/html") and b"cache-control" not in present:
                    # Pages with patient data must not stay in the browser cache of a shared PC (S-19).
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
