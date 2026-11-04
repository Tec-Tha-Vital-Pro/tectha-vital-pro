"""Staff account and sign-in screens: the second login step, Google/Microsoft sign-in, the My account
page (password, two-step login, linked sign-ins, other devices) and the admin's two-step policy."""
import hmac
import secrets
from datetime import timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import audit, auth, config, db, oidc, security, twofactor
from app.auth import ADMIN, STAFF
from app.routes import ui
from app.routes.ui import back, render

router = APIRouter(route_class=ui.UIRoute)

PENDING_COOKIE = "tt_2fa"           # password checked, code not yet entered (5 minutes)
PENDING_MAX_AGE = 300
OIDC_COOKIE = "tt_oidc"             # a Google/Microsoft sign-in in progress (10 minutes)
OIDC_MAX_AGE = 600
CODE_MAX_FAILURES = 5
CODE_WINDOW = timedelta(minutes=15)


def _signer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.settings.session_secret, salt=salt)


def _cookie(resp, request: Request, name: str, value: str, max_age: int) -> None:
    resp.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax", secure=security.is_https(request),
                    path="/")


# ---------------------------------------------------------------- second step

def start_second_step(request: Request, u: dict, next: str) -> RedirectResponse:
    resp = RedirectResponse("/login/2fa", status_code=303)
    token = _signer("tt-2fa").dumps({"u": u["id"], "v": u["session_version"], "n": next, "c": secrets.token_urlsafe(16)})
    _cookie(resp, request, PENDING_COOKIE, token, PENDING_MAX_AGE)
    return resp


def _pending(request: Request) -> dict | None:
    raw = request.cookies.get(PENDING_COOKIE)
    if not raw:
        return None
    try:
        data = _signer("tt-2fa").loads(raw, max_age=PENDING_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    u = db.one("SELECT * FROM users WHERE id = ? AND active = 1", (data.get("u"),))
    if u is None or u["session_version"] != data.get("v") or not u["totp_enabled"]:
        return None
    return {"user": u, "next": data.get("n", ""), "csrf": data["c"]}


@router.get("/login/2fa", response_class=HTMLResponse)
def second_step_page(request: Request):
    p = _pending(request)
    if p is None:
        return back("/login", err="Your login timed out. Please enter your password again.")
    return render(request, "login_2fa.html", None, pending_csrf=p["csrf"])


@router.post("/login/2fa")
def second_step(request: Request, code: str = Form(""), csrf: str = Form("")):
    p = _pending(request)
    if p is None:
        return back("/login", err="Your login timed out. Please enter your password again.")
    if not hmac.compare_digest(csrf.encode(), p["csrf"].encode()):
        raise auth.CsrfFailed()
    u = p["user"]
    key = str(u["id"])
    if security.hits("totp_failed", key, CODE_WINDOW) >= CODE_MAX_FAILURES:
        audit.log(f"user:{u['username']}", "login_2fa_throttled", "user", u["id"])
        return render(request, "login_2fa.html", None, status_code=429, pending_csrf=p["csrf"],
                      login_error="Too many wrong codes. Wait 15 minutes, or ask an admin to reset two-step login.")
    if not twofactor.verify(u["id"], code):
        security.record("totp_failed", key)
        audit.log(f"user:{u['username']}", "login_2fa_failed", "user", u["id"], {"ip": security.client_ip(request)})
        return render(request, "login_2fa.html", None, status_code=401, pending_csrf=p["csrf"],
                      login_error="That code didn't work. Use the newest code from the app, or a recovery code.")
    security.clear("totp_failed", key)
    audit.log(f"user:{u['username']}", "login_2fa_success", "user", u["id"], {"ip": security.client_ip(request)})
    resp = RedirectResponse(ui.safe_next(p["next"], u["role"]), status_code=303)
    resp.delete_cookie(PENDING_COOKIE, path="/")
    auth.set_session_cookie(resp, request, u["id"])
    return resp


# ---------------------------------------------------------------- Google / Microsoft

@router.get("/login/oidc/{provider}")
def oidc_begin(request: Request, provider: str, next: str = "", link: str = ""):
    if provider not in oidc.PROVIDERS or not oidc.enabled(provider):
        return back("/login", err="That sign-in option is not set up. Use your username and password.")
    link_user = None
    if link == "1":
        link_user = auth.require(request, STAFF)["id"]
    try:
        url, state = oidc.begin(provider)
    except oidc.OIDCError as e:
        return back("/account" if link_user else "/login", err=str(e))
    state.update(next=next, link=link_user)
    resp = RedirectResponse(url, status_code=303)
    _cookie(resp, request, OIDC_COOKIE, _signer("tt-oidc").dumps(state), OIDC_MAX_AGE)
    return resp


@router.get("/login/oidc/{provider}/callback")
def oidc_callback(request: Request, provider: str, code: str = "", state: str = "", error: str = ""):
    raw = request.cookies.get(OIDC_COOKIE)
    try:
        st = _signer("tt-oidc").loads(raw, max_age=OIDC_MAX_AGE) if raw else None
    except (BadSignature, SignatureExpired):
        st = None
    if not st or st.get("p") != provider or not hmac.compare_digest(state.encode(), st["s"].encode()):
        return back("/login", err="The sign-in could not be matched to this browser. Please try again.")
    dest_err = "/account" if st.get("link") else "/login"
    if error or not code:
        return _clear(back(dest_err, err=f"{oidc.LABELS[provider]} sign-in was cancelled."))
    try:
        ident = oidc.identity(provider, oidc.exchange_code(provider, code, st["v"]), st["n"])
    except oidc.OIDCError as e:
        audit.log("oidc", "oidc_failed", "user", st.get("link"), {"provider": provider, "error": str(e)})
        return _clear(back(dest_err, err=str(e)))
    if st.get("link"):
        me = auth.current_user(request)
        if me is None or me["id"] != st["link"]:
            return _clear(back("/login", err="Log in again, then link your account."))
        try:
            oidc.link(me["id"], provider, ident, actor=auth.actor(me))
        except oidc.OIDCError as e:
            return _clear(back("/account", err=str(e)))
        return _clear(back("/account", msg=f"{oidc.LABELS[provider]} account {ident['email']} linked. "
                                           f"You can now sign in with {oidc.LABELS[provider]}."))
    u = oidc.user_for(provider, ident)
    if u is None:
        audit.log("oidc", "oidc_no_linked_login", "user", None, {"provider": provider, "email": ident["email"]})
        return _clear(back("/login", err=f"No staff login is linked to {ident['email']}. Log in with your password and "
                                         f"link {oidc.LABELS[provider]} on the My account page."))
    audit.log(f"user:{u['username']}", "login_success", "user", u["id"], {"via": provider})
    return _clear(ui.finish_login(request, u, st.get("next", "")))


def _clear(resp):
    resp.delete_cookie(OIDC_COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- My account

def _account_ctx(user: dict) -> dict:
    u = db.one("SELECT * FROM users WHERE id = ?", (user["id"],))
    ctx = {
        "me": u,
        "role_label": auth.ROLE_LABELS.get(u["role"], u["role"]),
        "identities": db.query("SELECT * FROM user_identities WHERE user_id = ? ORDER BY id", (u["id"],)),
        "sso": [(p, oidc.LABELS[p]) for p in oidc.enabled_providers()],
        "codes_left": twofactor.recovery_codes_left(u["id"]),
        "required_roles": auth.two_factor_required_roles(),
        "must_set_up": auth.needs_two_factor_setup({**user, "totp_enabled": u["totp_enabled"]}),
        "idle_minutes": auth.IDLE_MINUTES,
        "role_labels": auth.ROLE_LABELS,
    }
    if u["role"] == "admin":
        ctx["twofa_users"] = db.query("SELECT id, username, full_name FROM users WHERE totp_enabled = 1 AND id != ?"
                                      " ORDER BY username", (u["id"],))
    return ctx


@router.get("/account", response_class=HTMLResponse)
def account_page(request: Request):
    user = auth.require(request, STAFF)
    return render(request, "account.html", user, **_account_ctx(user))


@router.post("/account/password")
async def account_password(request: Request, current: str = Form(""), new: str = Form(""), confirm: str = Form("")):
    user = await auth.require_post(request, STAFF)
    row = db.one("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
    if not auth.verify_password(current, row["password_hash"]):
        audit.log(auth.actor(user), "password_change_failed", "user", user["id"])
        return back("/account", err="Your current password is not right.")
    if new != confirm:
        return back("/account", err="The two new passwords don't match.")
    try:
        auth.set_password(user["id"], new, actor=auth.actor(user))   # ends every other session too
    except ValueError as e:
        return back("/account", err=str(e))
    resp = back("/account", msg="Password changed. Other devices have been signed out.")
    auth.set_session_cookie(resp, request, user["id"], csrf=user["csrf"], issued=user["issued"])
    return resp


@router.post("/account/sessions/end-others")
async def account_end_others(request: Request):
    user = await auth.require_post(request, STAFF)
    auth.end_sessions(user["id"])
    audit.log(auth.actor(user), "sessions_ended_elsewhere", "user", user["id"])
    resp = back("/account", msg="Signed out on every other device. This one stays signed in.")
    auth.set_session_cookie(resp, request, user["id"], csrf=user["csrf"], issued=user["issued"])
    return resp


@router.post("/account/identities/{identity_id}/remove")
async def account_unlink(request: Request, identity_id: int):
    user = await auth.require_post(request, STAFF)
    try:
        oidc.unlink(user["id"], identity_id, actor=auth.actor(user))
    except LookupError:
        raise auth.NotFound("linked account")
    return back("/account", msg="Linked sign-in removed.")


# ---------------------------------------------------------------- two-step login set-up

@router.get("/account/2fa", response_class=HTMLResponse)
def twofa_page(request: Request):
    user = auth.require(request, STAFF)
    u = db.one("SELECT username, totp_secret, totp_enabled FROM users WHERE id = ?", (user["id"],))
    pending = u["totp_secret"] if not u["totp_enabled"] else None
    uri = twofactor.provisioning_uri(pending, u["username"]) if pending else None
    return render(request, "account_2fa.html", user, enabled=bool(u["totp_enabled"]), secret=pending, uri=uri,
                  qr=twofactor.qr_svg_data_uri(uri) if uri else None, **_account_ctx(user))


@router.post("/account/2fa/start")
async def twofa_start(request: Request):
    user = await auth.require_post(request, STAFF)
    try:
        twofactor.start_enrolment(user["id"], actor=auth.actor(user))
    except ValueError as e:
        return back("/account/2fa", err=str(e))
    return back("/account/2fa", msg="Scan the code with your authenticator app, then type the 6-digit code.")


@router.post("/account/2fa/confirm", response_class=HTMLResponse)
async def twofa_confirm(request: Request, code: str = Form("")):
    user = await auth.require_post(request, STAFF)
    try:
        codes = twofactor.confirm_enrolment(user["id"], code, actor=auth.actor(user))
    except ValueError as e:
        return back("/account/2fa", err=str(e))
    return render(request, "account_codes.html", user, codes=codes, just_enabled=True)


@router.post("/account/2fa/recovery-codes", response_class=HTMLResponse)
async def twofa_new_codes(request: Request, code: str = Form("")):
    user = await auth.require_post(request, STAFF)
    if not twofactor.verify(user["id"], code):
        return back("/account", err="That code didn't work, so your recovery codes were not changed.")
    codes = twofactor.new_recovery_codes(user["id"], actor=auth.actor(user))
    return render(request, "account_codes.html", user, codes=codes, just_enabled=False)


@router.post("/account/2fa/disable")
async def twofa_disable(request: Request, password: str = Form(""), code: str = Form("")):
    user = await auth.require_post(request, STAFF)
    if user["role"] in auth.two_factor_required_roles():
        return back("/account", err="Your role must use two-step login, so it can't be turned off.")
    row = db.one("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
    if not auth.verify_password(password, row["password_hash"]) or not twofactor.verify(user["id"], code):
        audit.log(auth.actor(user), "totp_disable_failed", "user", user["id"])
        return back("/account", err="Password or code not right, so two-step login stays on.")
    twofactor.disable(user["id"], actor=auth.actor(user))
    return back("/account", msg="Two-step login is off for your account.")


# ---------------------------------------------------------------- admin: policy and lost phones

@router.post("/account/security-policy")
async def security_policy(request: Request):
    user = await auth.require_post(request, ADMIN)
    form = await request.form()
    roles = [r for r in auth.ROLES if form.get(f"role_{r}") == "1"]
    db.set_setting("require_2fa_roles", ",".join(roles))
    audit.log(auth.actor(user), "update", "settings", None, {"require_2fa_roles": roles})
    names = ", ".join(auth.ROLE_LABELS[r] for r in roles) or "no roles"
    return back("/account", msg=f"Two-step login is now required for: {names}.")


@router.post("/account/users/{user_id}/2fa-reset")
async def admin_reset_2fa(request: Request, user_id: int):
    user = await auth.require_post(request, ADMIN)
    target = db.one("SELECT id, username FROM users WHERE id = ?", (user_id,))
    if target is None or target["id"] == user["id"]:
        raise auth.NotFound("staff login")
    twofactor.disable(target["id"], actor=auth.actor(user))
    auth.end_sessions(target["id"])
    audit.log(auth.actor(user), "totp_reset_by_admin", "user", target["id"], {"username": target["username"]})
    return back("/account", msg=f"Two-step login reset for {target['username']}. They set it up again at their next login.")
