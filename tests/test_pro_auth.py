"""Pro login: new roles, two-step login (TOTP + recovery codes), 2FA policy, idle timeout, Google/Microsoft."""
import base64
import json
import re
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app import auth, db, oidc, twofactor
from app.routes import account, ui
from app.routes import command  # noqa: F401  (registers base.html globals)
from tests.flash_util import flash

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
PW = "secret-pass-1"


def make_app():
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.add_middleware(auth.SessionRefresh)
    app.include_router(ui.router)
    app.include_router(account.router)
    return app


@pytest.fixture()
def client(fresh_db):
    return TestClient(make_app())


def _csrf(html):
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "no csrf"
    return m.group(1)


def _login(client, username="admin", role="admin", create=True):
    if create:
        auth.create_user(username, username.title(), PW, role)
    return client.post("/login", data={"username": username, "password": PW}, follow_redirects=False)


def _enrol(client):
    """Turn on two-step login for the logged-in user; returns (secret, recovery codes)."""
    page = client.get("/account/2fa")
    client.post("/account/2fa/start", data={"csrf": _csrf(page.text)})
    page = client.get("/account/2fa")
    secret = re.search(r"<code>([A-Z2-7]+)</code>", page.text).group(1)
    r = client.post("/account/2fa/confirm", data={"csrf": _csrf(page.text), "code": twofactor.totp(secret)})
    assert r.status_code == 200 and "recovery codes" in r.text
    codes = re.findall(r"<code>([0-9a-f]{6}-[0-9a-f]{6})</code>", r.text)
    return secret, codes


def test_totp_matches_rfc6238_vector():
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert twofactor.totp(secret, at=59) == "287082"
    assert twofactor.totp(secret, at=1111111109) == "081804"


@pytest.mark.parametrize("role,home", [("nurse", "/appointments"), ("lab", "/tasks"), ("pharmacy", "/tasks")])
def test_new_roles_log_in_to_their_home(client, role, home):
    r = _login(client, f"u{role}", role)
    assert r.status_code == 303 and r.headers["location"] == home
    assert client.get("/account").status_code == 200
    assert client.get("/settings").status_code == 403


def test_old_users_table_gains_new_roles(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,"
                 " password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','owner','frontdesk','billing','doctor')),"
                 " branch_id TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO users(username, full_name, password_hash, role, created_at) VALUES ('a','A','x','admin','2026-01-01')")
    conn.commit()
    conn.close()
    db.set_path(str(path))
    db.init_db()
    db.execute("INSERT INTO users(username, full_name, password_hash, role, created_at) VALUES ('n','N','x','nurse','2026-01-01')")
    assert db.scalar("SELECT COUNT(*) FROM users") == 2
    assert db.scalar("SELECT totp_enabled FROM users WHERE username='a'") == 0


def test_two_step_login_flow_and_replay(client):
    _login(client)
    secret, codes = _enrol(client)
    assert len(codes) == 10
    assert db.scalar("SELECT COUNT(*) FROM user_recovery_codes WHERE code_hash LIKE '%-%'") == 0   # only hashes stored
    client.cookies.clear()
    r = _login(client, create=False)
    assert r.headers["location"] == "/login/2fa"
    page = client.get("/login/2fa")
    assert client.get("/settings", follow_redirects=False).status_code == 303   # not logged in yet
    bad = client.post("/login/2fa", data={"csrf": _csrf(page.text), "code": "000000"})
    assert bad.status_code == 401
    # A code already used during enrolment can't be replayed.
    db.execute("UPDATE users SET totp_last_step = ? WHERE username='admin'", (int(time.time() // 30) + 1,))
    assert client.post("/login/2fa", data={"csrf": _csrf(page.text), "code": twofactor.totp(secret)}).status_code == 401
    ok = client.post("/login/2fa", data={"csrf": _csrf(page.text), "code": codes[0]}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/"
    assert client.get("/settings").status_code == 200
    assert twofactor.use_recovery_code(db.scalar("SELECT id FROM users WHERE username='admin'"), codes[0]) is False


def test_two_step_codes_are_throttled(client):
    _login(client)
    _enrol(client)
    client.cookies.clear()
    _login(client, create=False)
    page = client.get("/login/2fa")
    for _ in range(account.CODE_MAX_FAILURES):
        client.post("/login/2fa", data={"csrf": _csrf(page.text), "code": "111111"})
    assert client.post("/login/2fa", data={"csrf": _csrf(page.text), "code": "111111"}).status_code == 429


def test_policy_forces_setup_before_other_screens(client):
    _login(client)
    page = client.get("/account")
    client.post("/account/security-policy", data={"csrf": _csrf(page.text), "role_billing": "1"})
    assert auth.two_factor_required_roles() == {"billing"}
    client.cookies.clear()
    r = _login(client, "cash", "billing")
    r = client.get("/billing", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/account/2fa")
    assert client.get("/account").status_code == 200
    _enrol(client)
    assert client.get("/billing").status_code == 200


def test_idle_session_expires(client, monkeypatch):
    _login(client)
    assert client.get("/settings").status_code == 200
    real = time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + (auth.IDLE_MINUTES + 1) * 60)
    assert client.get("/settings", follow_redirects=False).status_code == 303


def test_active_session_is_refreshed(client, monkeypatch):
    _login(client)
    real = time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + (auth.IDLE_MINUTES - 2) * 60)
    r = client.get("/settings")
    assert r.status_code == 200 and auth.COOKIE in r.headers.get("set-cookie", "")
    monkeypatch.setattr(auth.time, "time", lambda: real() + (2 * auth.IDLE_MINUTES - 4) * 60)
    assert client.get("/settings").status_code == 200      # still signed in: the idle clock moved forward


def test_password_change_and_sign_out_others(client):
    _login(client)
    other = TestClient(make_app())
    _login(other, create=False)
    page = client.get("/account")
    r = client.post("/account/password", data={"csrf": _csrf(page.text), "current": PW, "new": "new-pass-123",
                                               "confirm": "new-pass-123"}, follow_redirects=False)
    assert "Password changed" in flash(r.headers["location"])
    assert client.get("/account").status_code == 200                       # this device stays in
    assert other.get("/account", follow_redirects=False).status_code == 303   # the other device is out


def _fake_oidc(monkeypatch, sub="g-123", email="admin@hospital.in", nonce_ok=True):
    monkeypatch.setenv("TT_OIDC_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("TT_OIDC_GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setenv("TT_PUBLIC_URL", "https://vital.example")
    meta = {"authorization_endpoint": "https://accounts.example/auth", "token_endpoint": "https://accounts.example/token",
            "issuer": "https://accounts.google.com"}
    monkeypatch.setattr(oidc, "fetch_discovery", lambda p: meta)
    state = {}

    def exchange(provider, code, verifier):
        payload = {"iss": "https://accounts.google.com", "aud": "cid", "exp": time.time() + 300, "sub": sub,
                   "email": email, "email_verified": True, "nonce": state["nonce"] if nonce_ok else "x"}
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return {"id_token": f"h.{body}.s", "issuer": meta["issuer"]}
    monkeypatch.setattr(oidc, "exchange_code", exchange)
    return state


def _oidc_round(client, state, link=False):
    r = client.get("/login/oidc/google" + ("?link=1" if link else ""), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://accounts.example/auth")
    q = dict(p.split("=", 1) for p in r.headers["location"].split("?", 1)[1].split("&"))
    state["nonce"] = q["nonce"]
    assert q["code_challenge_method"] == "S256"
    return client.get(f"/login/oidc/google/callback?code=abc&state={q['state']}", follow_redirects=False)


def test_google_sign_in_only_after_linking(client, monkeypatch):
    state = _fake_oidc(monkeypatch)
    auth.create_user("admin", "Admin", PW, "admin")
    r = _oidc_round(client, state)
    assert "No staff login is linked" in flash(r.headers["location"], "err")
    assert db.scalar("SELECT COUNT(*) FROM users") == 1                    # never auto-created
    _login(client, create=False)
    r = _oidc_round(client, state, link=True)
    assert "linked" in flash(r.headers["location"])
    client.cookies.clear()
    r = _oidc_round(client, state)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert client.get("/settings").status_code == 200


def test_google_wrong_nonce_rejected(client, monkeypatch):
    state = _fake_oidc(monkeypatch, nonce_ok=False)
    r = _oidc_round(client, state)
    assert "could not be matched" in flash(r.headers["location"], "err")


def test_sso_buttons_only_when_configured(client, monkeypatch):
    assert "Sign in with Google" not in client.get("/login").text
    _fake_oidc(monkeypatch)
    assert "Sign in with Google" in client.get("/login").text
