"""Sign in with Google or Microsoft (OpenID Connect, authorization code + PKCE).

Off until the hospital registers an app with the provider and sets, per provider:
  TT_OIDC_GOOGLE_CLIENT_ID, TT_OIDC_GOOGLE_CLIENT_SECRET
  TT_OIDC_MICROSOFT_CLIENT_ID, TT_OIDC_MICROSOFT_CLIENT_SECRET, TT_OIDC_MICROSOFT_TENANT (default "organizations")
plus TT_PUBLIC_URL (e.g. https://vital.hospital.in) for the redirect address, and optionally
TT_OIDC_ALLOWED_DOMAINS (comma-separated email domains, e.g. "hospital.in").

Nobody gets a login this way that they didn't have already: a staff member first logs in with their
password and links their Google/Microsoft account on the Account page. After that, the provider's
stable user id ("sub") signs them in. No account is ever created from a provider login.

The ID token arrives straight from the provider's token endpoint over TLS, authenticated with the
client secret; per OpenID Connect Core 3.1.3.7 its issuer, audience, expiry and nonce are checked
here (TLS stands in for the signature check on this direct back-channel response).
"""
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from app import audit, db, util

PROVIDERS = ("google", "microsoft")
LABELS = {"google": "Google", "microsoft": "Microsoft"}
TIMEOUT = 15


class OIDCError(Exception):
    """Something in the sign-in exchange was wrong. The message is safe to show to the user."""


def _env(provider: str, name: str, default: str = "") -> str:
    return os.environ.get(f"TT_OIDC_{provider.upper()}_{name}", default)


def enabled(provider: str) -> bool:
    return provider in PROVIDERS and bool(_env(provider, "CLIENT_ID") and _env(provider, "CLIENT_SECRET")
                                          and os.environ.get("TT_PUBLIC_URL"))


def enabled_providers() -> list[str]:
    return [p for p in PROVIDERS if enabled(p)]


def discovery_url(provider: str) -> str:
    if provider == "google":
        return "https://accounts.google.com/.well-known/openid-configuration"
    tenant = _env("microsoft", "TENANT", "organizations")
    return f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"


def redirect_uri(provider: str) -> str:
    return os.environ["TT_PUBLIC_URL"].rstrip("/") + f"/login/oidc/{provider}/callback"


def fetch_discovery(provider: str) -> dict:
    r = httpx.get(discovery_url(provider), timeout=TIMEOUT)
    if r.status_code != 200:
        raise OIDCError(f"{LABELS[provider]} sign-in is not reachable right now. Use your password.")
    return r.json()


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def begin(provider: str) -> tuple[str, dict]:
    """Return (authorization URL, state to keep in a short-lived signed cookie)."""
    if not enabled(provider):
        raise OIDCError("This sign-in option is not set up.")
    meta = fetch_discovery(provider)
    verifier = _b64url(secrets.token_bytes(32))
    state = {"p": provider, "s": secrets.token_urlsafe(24), "n": secrets.token_urlsafe(24), "v": verifier}
    params = {
        "client_id": _env(provider, "CLIENT_ID"), "response_type": "code", "scope": "openid email profile",
        "redirect_uri": redirect_uri(provider), "state": state["s"], "nonce": state["n"],
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return meta["authorization_endpoint"] + "?" + urlencode(params), state


def exchange_code(provider: str, code: str, verifier: str) -> dict:
    meta = fetch_discovery(provider)
    r = httpx.post(meta["token_endpoint"], timeout=TIMEOUT, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(provider),
        "client_id": _env(provider, "CLIENT_ID"), "client_secret": _env(provider, "CLIENT_SECRET"),
        "code_verifier": verifier,
    })
    if r.status_code != 200:
        raise OIDCError(f"{LABELS[provider]} did not accept the sign-in. Please try again.")
    body = r.json()
    if "id_token" not in body:
        raise OIDCError(f"{LABELS[provider]} did not return an identity. Please try again.")
    return {"id_token": body["id_token"], "issuer": meta["issuer"]}


def _decode_payload(id_token: str) -> dict:
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as e:
        raise OIDCError("The sign-in response was not readable. Please try again.") from e


def _issuer_ok(provider: str, claimed: str, expected: str) -> bool:
    if provider == "microsoft" and "{tenantid}" in expected:
        # Multi-tenant endpoints advertise a template issuer; the token carries the real tenant.
        prefix, suffix = expected.split("{tenantid}")
        return claimed.startswith(prefix) and claimed.endswith(suffix)
    return claimed == expected


def identity(provider: str, tokens: dict, nonce: str) -> dict:
    """Check the ID token's claims and return {sub, email}."""
    c = _decode_payload(tokens["id_token"])
    if not _issuer_ok(provider, c.get("iss", ""), tokens["issuer"]):
        raise OIDCError("The sign-in came from an unexpected issuer.")
    aud = c.get("aud")
    if _env(provider, "CLIENT_ID") not in (aud if isinstance(aud, list) else [aud]):
        raise OIDCError("The sign-in was meant for another application.")
    if int(c.get("exp", 0)) < time.time():
        raise OIDCError("The sign-in expired. Please try again.")
    if c.get("nonce") != nonce:
        raise OIDCError("The sign-in could not be matched to this browser. Please try again.")
    email = (c.get("email") or c.get("preferred_username") or "").lower()
    if provider == "google" and not c.get("email_verified"):
        raise OIDCError("Your Google email is not verified.")
    if not c.get("sub") or "@" not in email:
        raise OIDCError("The sign-in did not include an email address.")
    allowed = [d.strip().lower() for d in os.environ.get("TT_OIDC_ALLOWED_DOMAINS", "").split(",") if d.strip()]
    if allowed and email.rsplit("@", 1)[1] not in allowed:
        raise OIDCError("This email domain is not allowed to sign in here.")
    return {"sub": str(c["sub"]), "email": email}


def link(user_id: int, provider: str, ident: dict, actor: str) -> None:
    other = db.one("SELECT user_id FROM user_identities WHERE provider = ? AND subject = ?", (provider, ident["sub"]))
    if other and other["user_id"] != user_id:
        raise OIDCError(f"This {LABELS[provider]} account is already linked to another login.")
    if other is None:
        iid = db.execute("INSERT INTO user_identities(user_id, provider, subject, email, created_at) VALUES (?,?,?,?,?)",
                         (user_id, provider, ident["sub"], ident["email"], util.ts(util.now())))
        audit.log(actor, "identity_linked", "user", user_id, {"provider": provider, "email": ident["email"], "id": iid})


def user_for(provider: str, ident: dict) -> dict | None:
    row = db.one("SELECT u.* FROM user_identities i JOIN users u ON u.id = i.user_id"
                 " WHERE i.provider = ? AND i.subject = ? AND u.active = 1", (provider, ident["sub"]))
    return row


def unlink(user_id: int, identity_id: int, actor: str) -> None:
    row = db.one("SELECT * FROM user_identities WHERE id = ? AND user_id = ?", (identity_id, user_id))
    if row is None:
        raise LookupError("Linked account not found")
    db.execute("DELETE FROM user_identities WHERE id = ?", (identity_id,))
    audit.log(actor, "identity_unlinked", "user", user_id, {"provider": row["provider"], "email": row["email"]})
