"""Patient app (mobile PWA) at /my. Login by mobile number + one-time code sent on WhatsApp.

Separate from staff logins: its own cookie, salt and CSRF token. Business rules are reused
from app.billing / app.patients / app.messaging; nothing here bypasses consent or audit.
"""
import hashlib
import hmac
import json
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import audit, billing, config, db, messaging, patients, security, util
from app import diagnostics

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
TEMPLATES.env.filters["inr"] = util.inr
TEMPLATES.env.globals["product"] = config.PRODUCT_NAME
TEMPLATES.env.globals["tagline"] = config.PRODUCT_TAGLINE

LANG_COOKIE = "tt_lang"
# Key patient-app strings in English and Hindi (M12). Hindi to be reviewed by a native speaker before
# the pilot; never machine-translated. Strings not listed stay in English.
STRINGS = {
    "en": {
        "voice_link": "Speak to us", "tab_home": "Home", "tab_book": "Book", "tab_bills": "Bills", "tab_reports": "Reports", "tab_profile": "Profile",
        "tagline": "Book visits, see reports and pay bills from your phone.",
        "mobile_number": "Mobile number", "get_code": "Get code on WhatsApp",
        "use_number": "Use the number you gave at the hospital.",
        "code_label": "6-digit code from WhatsApp", "log_in": "Log in", "other_number": "Use a different number",
        "not_found_h": "We could not find this number",
        "not_found_p": "Only registered patients can log in. Message us on WhatsApp or visit the front desk, and we will register you.",
        "try_other": "Try another number",
        "yes_there": "Yes, I'll be there", "change_time": "Ask to change time", "cancel_visit": "Cancel visit",
        "confirm": "Confirm", "confirmed": "Confirmed", "please_confirm": "Please confirm",
        "book_visit": "Book a visit", "book_appt": "Book an appointment", "my_visits": "My visits",
        "to_pay": "to pay", "all_paid": "All paid", "paid": "Paid", "pay": "Pay {amount}", "total": "Total {amount}",
        "help_title": "Need help?", "help_wa": "Message us on WhatsApp", "help_call": "Call the front desk",
        "help_none": "Ask at the front desk. The team replies on WhatsApp between 8 am and 9 pm.",
        "cancel_title": "Cancel this visit?", "cancel_q": "Cancel your visit with {doctor} on {when}?",
        "cancel_note": "If you cancel, the time goes to another patient. You can book again any time.",
        "yes_cancel": "Yes, cancel", "keep_visit": "Keep my visit",
        "language": "Language", "log_out": "Log out",
    },
    "hi": {
        "voice_link": "बोलकर पूछें", "tab_home": "होम", "tab_book": "बुक करें", "tab_bills": "बिल", "tab_reports": "रिपोर्ट", "tab_profile": "प्रोफ़ाइल",
        "tagline": "अपने फ़ोन से डॉक्टर से मिलने का समय लें, रिपोर्ट देखें और बिल भरें।",
        "mobile_number": "मोबाइल नंबर", "get_code": "WhatsApp पर कोड पाएं",
        "use_number": "वही नंबर डालें जो आपने अस्पताल में दिया था।",
        "code_label": "WhatsApp पर आया 6 अंकों का कोड", "log_in": "लॉग इन करें", "other_number": "दूसरा नंबर डालें",
        "not_found_h": "यह नंबर हमारे पास नहीं मिला",
        "not_found_p": "केवल पंजीकृत मरीज़ लॉग इन कर सकते हैं। WhatsApp पर संदेश भेजें या फ्रंट डेस्क पर आएँ, हम आपका पंजीकरण कर देंगे।",
        "try_other": "दूसरा नंबर आज़माएँ",
        "yes_there": "हाँ, मैं आऊँगा/आऊँगी", "change_time": "समय बदलने के लिए कहें", "cancel_visit": "मुलाक़ात रद्द करें",
        "confirm": "पक्का करें", "confirmed": "पक्का", "please_confirm": "कृपया पक्का करें",
        "book_visit": "डॉक्टर से मिलने का समय लें", "book_appt": "डॉक्टर से मिलने का समय लें", "my_visits": "मेरी मुलाक़ातें",
        "to_pay": "भुगतान बाकी", "all_paid": "सब भुगतान हो गया", "paid": "भुगतान हो गया", "pay": "{amount} भुगतान करें",
        "total": "कुल {amount}",
        "help_title": "मदद चाहिए?", "help_wa": "WhatsApp पर संदेश भेजें", "help_call": "फ्रंट डेस्क को कॉल करें",
        "help_none": "फ्रंट डेस्क पर पूछें। टीम सुबह 8 से रात 9 बजे तक WhatsApp पर जवाब देती है।",
        "cancel_title": "यह मुलाक़ात रद्द करें?", "cancel_q": "{when} को {doctor} के साथ आपकी मुलाक़ात रद्द करें?",
        "cancel_note": "रद्द करने पर यह समय किसी और मरीज़ को मिल जाएगा। आप कभी भी फिर से बुक कर सकते हैं।",
        "yes_cancel": "हाँ, रद्द करें", "keep_visit": "मेरी मुलाक़ात रहने दें",
        "language": "भाषा", "log_out": "लॉग आउट",
    },
}


def _lang(request: Request) -> str:
    v = request.cookies.get(LANG_COOKIE, "en")
    return v if v in STRINGS else "en"


def _translator(lang: str):
    table, base = STRINGS[lang], STRINGS["en"]

    def t(key: str, **kw) -> str:
        return (table.get(key) or base[key]).format(**kw)
    return t


def _flash_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.settings.session_secret, salt="tt-patient-flash")


def read_flash(token: str | None) -> str | None:
    """Toasts show only text this server signed in the last 5 minutes (a crafted ?err= link shows nothing)."""
    if not token:
        return None
    try:
        v = _flash_signer().loads(token, max_age=300)
    except BadSignature:
        return None
    return v if isinstance(v, str) else None

COOKIE = "tt_patient"
PRE_COOKIE = "tt_pcsrf"           # double-submit CSRF token for the login forms (no session yet)
MAX_AGE = 7 * 24 * 3600          # a lost or shared phone stays logged in for a week at most (S-10)
OTP_TTL = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 5
OTP_MAX_PER_10_MIN = 3            # per mobile number
OTP_MAX_PER_IP_HOUR = 10          # per caller IP, known and unknown numbers alike (S-08)
OTP_MAX_GLOBAL_HOUR = 300         # whole hospital: caps WhatsApp cost if many IPs are used
SLOT_TIMES = [f"{h:02d}:{m:02d}" for h in range(9, 13) for m in (0, 30)] + \
             [f"{h:02d}:{m:02d}" for h in range(16, 19) for m in (0, 30)]


class LoginRequired(Exception):
    pass


class CsrfFailed(Exception):
    pass


class PatientRoute(APIRoute):
    """Turns LoginRequired into a redirect and CsrfFailed into a friendly 403 page."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except LoginRequired:
                return RedirectResponse("/my/login", status_code=303)
            except CsrfFailed:
                return _page(request, "patient/error.html", None, status_code=403, title="Please try again",
                             detail="This form expired. Go back, reload the page and try again.")

        return wrapped


router = APIRouter(route_class=PatientRoute)


# ---------- storage ----------

def init() -> None:
    with db.connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS patient_otps ("
            " id INTEGER PRIMARY KEY, phone TEXT NOT NULL, code_hash TEXT NOT NULL, expires_at TEXT NOT NULL,"
            " attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_potp_phone ON patient_otps(phone, created_at)")


_ready_for: str | None = None


def _ensure() -> None:
    """Create the OTP table once per database file (tests switch files)."""
    global _ready_for
    if _ready_for != db._db_path:
        init()
        _ready_for = db._db_path


# ---------- session ----------

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.settings.session_secret, salt="tt-patient-session")


def current_patient(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    p = db.one("SELECT * FROM patients WHERE id = ?", (data.get("p"),))
    if p is None or data.get("v") != p["session_version"]:
        return None  # logged out since this cookie was issued
    p["csrf"] = data["c"]
    return p


def _me(request: Request) -> dict:
    _ensure()
    p = current_patient(request)
    if p is None:
        raise LoginRequired()
    return p


async def _me_post(request: Request) -> tuple[dict, dict]:
    p = _me(request)
    form = await request.form()
    token = form.get("csrf", "")
    if not (isinstance(token, str) and hmac.compare_digest(token.encode(), p["csrf"].encode())):
        raise CsrfFailed()
    return p, form


def _actor(p: dict) -> str:
    return f"patient:{p['uid']}"


def demo_mode() -> bool:
    """Demo payments and sample report values exist only in simulator (demo) mode."""
    return config.settings.whatsapp_mode == "simulator"


def _hospital() -> str:
    return db.get_setting("hospital_name", "Your Hospital")


def _page(request: Request, name: str, p: dict | None, status_code: int = 200, **ctx) -> HTMLResponse:
    ctx.setdefault("msg", read_flash(request.query_params.get("msg")))
    ctx.setdefault("err", read_flash(request.query_params.get("err")))
    lang = _lang(request)
    ctx.update(request=request, me=p, hospital=_hospital(), csrf=p["csrf"] if p else ctx.get("csrf", ""),
               path=request.url.path, simulator=demo_mode(), demo=demo_mode(), lang=lang, t=_translator(lang),
               help_wa=db.get_setting("hospital_whatsapp", ""), help_call=db.get_setting("front_desk_phone", ""))
    return TEMPLATES.TemplateResponse(request, name, ctx, status_code=status_code)


def _go(path: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    from urllib.parse import urlencode
    q = {k: _flash_signer().dumps(v) for k, v in (("msg", msg), ("err", err)) if v}
    sep = "&" if "?" in path else "?"
    return RedirectResponse(path + (sep + urlencode(q) if q else ""), status_code=303)


def not_found_page(request: Request) -> HTMLResponse:
    """Used by the app-wide 404 handler for mistyped /my addresses."""
    return _page(request, "patient/error.html", current_patient(request), status_code=404, title="Page not found",
                 detail="Check the address, or go back to the home screen.")


def relative_phrase(starts_at: str, now: datetime) -> str:
    """'today at 11:30 am', 'tomorrow at 5 pm', 'on Friday 14 Nov at 10 am'."""
    w = util.parse(starts_at)
    t = w.strftime("%I:%M %p").lstrip("0").replace(":00", "").lower()
    days = (w.date() - now.date()).days
    if days == 0:
        return f"today at {t}"
    if days == 1:
        return f"tomorrow at {t}"
    if 1 < days < 7:
        return f"on {w.strftime('%A')} at {t}"
    return f"on {w.strftime('%a %d %b').replace(' 0', ' ')} at {t}"


def _fmt_when(s: str) -> str:
    w = util.parse(s)
    return f"{w.strftime('%a')} {w.day} {w.strftime('%b')} · {w.strftime('%I:%M').lstrip('0')} {w.strftime('%p').lower()}"


TEMPLATES.env.filters["when"] = _fmt_when
TEMPLATES.env.filters["day"] = lambda s: util.parse(s).strftime("%d %b %Y")


# ---------- login ----------

def _otp_hash(phone: str, code: str) -> str:
    return hmac.new(config.settings.session_secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _pre_token(request: Request) -> str:
    return request.cookies.get(PRE_COOKIE) or secrets.token_urlsafe(24)


def _check_pre(request: Request, form) -> None:
    cookie = request.cookies.get(PRE_COOKIE, "")
    token = form.get("csrf", "")
    if not (cookie and isinstance(token, str) and hmac.compare_digest(token.encode(), cookie.encode())):
        raise CsrfFailed()


def _login_page(request: Request, step: str, status_code: int = 200, **ctx) -> HTMLResponse:
    token = _pre_token(request)
    resp = _page(request, "patient/login.html", None, status_code=status_code, step=step, csrf=token, **ctx)
    resp.set_cookie(PRE_COOKIE, token, httponly=True, samesite="lax", secure=security.is_https(request), path="/my")
    return resp


@router.get("/login")
def login_page(request: Request):
    _ensure()
    if current_patient(request):
        return _go("/my/")
    return _login_page(request, "phone")


@router.post("/login/phone")
async def login_phone(request: Request):
    _ensure()
    form = await request.form()
    _check_pre(request, form)
    raw = str(form.get("phone", ""))
    try:
        phone = util.normalize_phone(raw)
    except ValueError:
        return _login_page(request, "phone", 400, phone=raw, field_err="Enter your 10-digit mobile number.")
    ip = security.client_ip(request)
    hour = timedelta(hours=1)
    if (security.hits("otp_send", ip, hour) >= OTP_MAX_PER_IP_HOUR
            or security.hits("otp_send", "*", hour) >= OTP_MAX_GLOBAL_HOUR):
        audit.log("patient-app", "otp_throttled", "patient", None, {"ip": ip})
        return _login_page(request, "phone", 429, phone=raw,
                           field_err="Too many codes asked for. Please wait an hour and try again, or ask at the front desk.")
    now = util.now()
    recent = db.scalar("SELECT COUNT(*) FROM patient_otps WHERE phone = ? AND created_at >= ?",
                       (phone, util.ts(now - timedelta(minutes=10))))
    if recent >= OTP_MAX_PER_10_MIN:
        return _login_page(request, "phone", 429, phone=raw,
                           field_err="Too many codes asked for. Please wait 10 minutes and try again.")
    security.record("otp_send", ip)
    security.record("otp_send", "*")
    # Known and unknown numbers get the same page, the same limits and the same "wrong code" answers,
    # so the login can't be used to test whether someone is a patient (S-08). For an unknown number
    # we store a code nobody knows and send nothing.
    p = db.one("SELECT * FROM patients WHERE phone = ?", (phone,))
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute("INSERT INTO patient_otps(phone, code_hash, expires_at, created_at) VALUES (?,?,?,?)",
               (phone, _otp_hash(phone, code) if p else secrets.token_hex(32), util.ts(now + OTP_TTL), util.ts(now)))
    if p is None:
        audit.log("patient-app", "login_unknown_phone", "patient", None, {"phone": phone[-4:]})
    else:
        messaging.send(phone, "patient_otp",
                       f"{code} is your {_hospital()} login code. It expires in 5 minutes. Do not share it with anyone.",
                       patient_id=p["id"], require_consent=False, actor="patient-app")
    return _login_page(request, "code", phone=phone, masked=f"+91 ••••• {phone[-5:]}")


@router.post("/login/verify")
async def login_verify(request: Request):
    _ensure()
    form = await request.form()
    _check_pre(request, form)
    phone = str(form.get("phone", ""))
    code = "".join(ch for ch in str(form.get("code", "")) if ch.isdigit())
    masked = f"+91 ••••• {phone[-5:]}"
    otp = db.one("SELECT * FROM patient_otps WHERE phone = ? AND used = 0 ORDER BY id DESC LIMIT 1", (phone,))
    now = util.now()
    if otp is None or util.parse(otp["expires_at"]) < now:
        return _login_page(request, "phone", 400, phone=phone[2:] if len(phone) == 12 else phone,
                           field_err="That code has expired. Ask for a new one.")
    if otp["attempts"] >= OTP_MAX_ATTEMPTS:
        return _login_page(request, "phone", 400, phone=phone[2:], field_err="Too many wrong tries. Ask for a new code.")
    if not hmac.compare_digest(otp["code_hash"], _otp_hash(phone, code)):
        db.execute("UPDATE patient_otps SET attempts = attempts + 1 WHERE id = ?", (otp["id"],))
        left = OTP_MAX_ATTEMPTS - otp["attempts"] - 1
        if left <= 0:
            return _login_page(request, "phone", 400, phone=phone[2:], field_err="Too many wrong tries. Ask for a new code.")
        return _login_page(request, "code", 400, phone=phone, masked=masked,
                           field_err=f"That code is not right. {left} {'try' if left == 1 else 'tries'} left.")
    db.execute("UPDATE patient_otps SET used = 1 WHERE id = ?", (otp["id"],))
    p = db.one("SELECT * FROM patients WHERE phone = ?", (phone,))
    if p is None:
        return _login_page(request, "phone", 400, phone=phone[2:], field_err="That code has expired. Ask for a new one.")
    audit.log(_actor(p), "patient_login", "patient", p["id"])
    resp = _go("/my/")
    token = _serializer().dumps({"p": p["id"], "v": p["session_version"], "c": secrets.token_urlsafe(24)})
    resp.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax",
                    secure=security.is_https(request), path="/")
    resp.delete_cookie(PRE_COOKIE, path="/my")
    return resp


@router.post("/logout")
async def logout(request: Request):
    p, _ = await _me_post(request)
    db.execute("UPDATE patients SET session_version = session_version + 1 WHERE id = ?", (p["id"],))
    audit.log(_actor(p), "patient_logout", "patient", p["id"])
    resp = _go("/my/login")
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ---------- data helpers ----------

def _appointments(pid: int, upcoming: bool, now: datetime, limit: int = 50) -> list[dict]:
    op, order = (">=", "ASC") if upcoming else ("<", "DESC")
    status = "AND a.status IN ('Booked','Confirmed')" if upcoming else ""
    return db.query(
        f"SELECT a.*, d.name AS doctor, d.specialty, b.name AS branch,"
        f" (SELECT COUNT(*) FROM feedback f WHERE f.appointment_id = a.id) AS rated"
        f" FROM appointments a JOIN doctors d ON d.id = a.doctor_id JOIN branches b ON b.id = a.branch_id"
        f" WHERE a.patient_id = ? AND a.starts_at {op} ? {status} ORDER BY a.starts_at {order} LIMIT ?",
        (pid, util.ts(now), limit))


def _bills(pid: int) -> list[dict]:
    # Unpaid bills first, so the amount to pay is never at the bottom of the list (M13).
    return db.query("SELECT bl.*, b.name AS branch, bl.total - bl.paid AS balance FROM bills bl"
                    " JOIN branches b ON b.id = bl.branch_id WHERE bl.patient_id = ?"
                    " ORDER BY (bl.total > bl.paid) DESC, bl.created_at DESC", (pid,))


def _own(sql: str, pid: int, rid: int, what: str) -> dict:
    row = db.one(sql, (rid,))
    if row is None or row["patient_id"] != pid:
        raise LookupError(what)
    return row


def _not_found(request: Request, p: dict, what: str) -> HTMLResponse:
    return _page(request, "patient/error.html", p, status_code=404, title="Not found",
                 detail=f"We could not find that {what}.")


# ---------- home ----------

@router.get("/")
def home(request: Request):
    p = _me(request)
    now = util.now()
    nxt = _appointments(p["id"], True, now, 1)
    dues = [b for b in _bills(p["id"]) if b["balance"] > 0]
    to_rate = db.one(
        "SELECT a.id, a.starts_at, d.name AS doctor FROM appointments a JOIN doctors d ON d.id = a.doctor_id"
        " WHERE a.patient_id = ? AND a.status = 'Visited' AND a.starts_at >= ?"
        " AND NOT EXISTS (SELECT 1 FROM feedback f WHERE f.appointment_id = a.id) ORDER BY a.starts_at DESC LIMIT 1",
        (p["id"], util.ts(now - timedelta(days=7))))
    hour = now.hour
    greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    if nxt:
        nxt[0]["phrase"] = relative_phrase(nxt[0]["starts_at"], now)
    return _page(request, "patient/home.html", p, nxt=nxt[0] if nxt else None, dues=dues,
                 due_total=sum(b["balance"] for b in dues), to_rate=to_rate, greet=greet,
                 is_today=bool(nxt) and nxt[0]["starts_at"][:10] == now.date().isoformat(),
                 first_name=p["name"].split()[0])


# ---------- appointments ----------

@router.get("/appointments")
def appointments(request: Request):
    p = _me(request)
    now = util.now()
    return _page(request, "patient/appointments.html", p, upcoming=_appointments(p["id"], True, now),
                 past=_appointments(p["id"], False, now, 20))


@router.get("/appointments/{appt_id}/cancel")
def appointment_cancel_confirm(request: Request, appt_id: int):
    """A cancel is never one tap: the patient sees what they are cancelling first (M3)."""
    p = _me(request)
    try:
        a = _own("SELECT a.*, d.name AS doctor, b.name AS branch FROM appointments a JOIN doctors d ON d.id = a.doctor_id"
                 " JOIN branches b ON b.id = a.branch_id WHERE a.id = ?", p["id"], appt_id, "appointment")
    except LookupError:
        return _not_found(request, p, "appointment")
    if a["status"] not in ("Booked", "Confirmed"):
        return _go("/my/appointments", err="This appointment can no longer be changed.")
    back = request.query_params.get("back", "/my/")
    return _page(request, "patient/cancel.html", p, a=a, back=back if back in ("/my/", "/my/appointments") else "/my/")


@router.get("/lang/{code}")
def set_language(request: Request, code: str):
    nxt = request.query_params.get("next", "/my/")
    if not (nxt.startswith("/my/") or nxt == "/my") or "//" in nxt:
        nxt = "/my/"
    resp = RedirectResponse(nxt, status_code=303)
    if code in STRINGS:
        resp.set_cookie(LANG_COOKIE, code, max_age=365 * 24 * 3600, httponly=True, samesite="lax", path="/my")
    return resp


@router.post("/appointments/{appt_id}/action")
async def appointment_action(request: Request, appt_id: int):
    p, form = await _me_post(request)
    action = form.get("action")
    try:
        a = _own("SELECT * FROM appointments WHERE id = ?", p["id"], appt_id, "appointment")
    except LookupError:
        return _not_found(request, p, "appointment")
    if a["status"] not in ("Booked", "Confirmed"):
        return _go("/my/appointments", err="This appointment can no longer be changed.")
    now = util.now()
    if action == "confirm":
        db.execute("UPDATE appointments SET status = 'Confirmed' WHERE id = ?", (appt_id,))
        audit.log(_actor(p), "appointment_confirmed", "appointment", appt_id)
        msg = "Thank you. Your appointment is confirmed."
    elif action == "cancel":
        db.execute("UPDATE appointments SET status = 'Cancelled' WHERE id = ?", (appt_id,))
        audit.log(_actor(p), "appointment_cancelled", "appointment", appt_id)
        msg = "Your appointment is cancelled."
    elif action == "reschedule":
        db.execute("INSERT OR IGNORE INTO tasks(kind, title, branch_id, related_type, related_id, status, due_at, created_at)"
                   " VALUES ('followup_call', ?, ?, 'appointment', ?, 'Open', ?, ?)",
                   (f"{p['name']} wants to reschedule OPD-{appt_id} (patient app)", a["branch_id"], appt_id,
                    util.ts(now + timedelta(minutes=30)), util.ts(now)))
        audit.log(_actor(p), "reschedule_requested", "appointment", appt_id)
        msg = "Our team will call you to pick a new time."
    else:
        return _go("/my/", err="Unknown action.")
    back = form.get("back", "/my/")
    return _go(back if back in ("/my/", "/my/appointments") else "/my/", msg=msg)


# ---------- booking ----------

def _free_slots(doctor_id: int, day: date, now: datetime) -> list[str]:
    taken = {r["starts_at"][11:16] for r in db.query(
        "SELECT starts_at FROM appointments WHERE doctor_id = ? AND date(starts_at) = ? AND status != 'Cancelled'",
        (doctor_id, day.isoformat()))}
    out = []
    for t in SLOT_TIMES:
        when = datetime.combine(day, datetime.strptime(t, "%H:%M").time())
        if t not in taken and when > now + timedelta(minutes=30):
            out.append(t)
    return out


@router.get("/book")
def book(request: Request, branch: str = "", doctor: int = 0, day: str = ""):
    p = _me(request)
    now = util.now()
    branches = db.query("SELECT * FROM branches ORDER BY id")
    ctx = {"branches": branches, "branch": None, "doctors": [], "doctor": None, "days": [], "day": None, "slots": []}
    b = next((x for x in branches if x["id"] == branch), None)
    if b:
        ctx["branch"] = b
        ctx["doctors"] = db.query("SELECT * FROM doctors WHERE branch_id = ? ORDER BY specialty, name", (b["id"],))
        d = next((x for x in ctx["doctors"] if x["id"] == doctor), None)
        if d:
            ctx["doctor"] = d
            ctx["days"] = [now.date() + timedelta(days=i) for i in range(7)]
            try:
                chosen = date.fromisoformat(day) if day else None
            except ValueError:
                chosen = None
            if chosen and chosen in ctx["days"]:
                ctx["day"] = chosen
                ctx["slots"] = _free_slots(d["id"], chosen, now)
    return _page(request, "patient/book.html", p, today=now.date(), **ctx)


@router.post("/book")
async def book_submit(request: Request):
    p, form = await _me_post(request)
    now = util.now()
    doc = db.one("SELECT * FROM doctors WHERE id = ?", (int(form.get("doctor_id", 0) or 0),))
    try:
        day = date.fromisoformat(str(form.get("day", "")))
    except ValueError:
        day = None
    slot = str(form.get("slot", ""))
    if doc is None or day is None or not (now.date() <= day <= now.date() + timedelta(days=6)):
        return _go("/my/book", err="Please choose a doctor and a date.")
    if slot not in _free_slots(doc["id"], day, now):
        return _go(f"/my/book?branch={doc['branch_id']}&doctor={doc['id']}&day={day.isoformat()}",
                   err="Sorry, that time was just taken. Please pick another.")
    when = datetime.combine(day, datetime.strptime(slot, "%H:%M").time())
    token = (db.scalar("SELECT COALESCE(MAX(token_no),0) FROM appointments WHERE branch_id = ? AND date(starts_at) = ?",
                       (doc["branch_id"], day.isoformat())) or 0) + 1
    aid = db.execute(
        "INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, token_no, source, created_at)"
        " VALUES (?,?,?,?, 'Booked', ?, 'Patient app', ?)",
        (p["id"], doc["id"], doc["branch_id"], util.ts(when), token, util.ts(now)))
    db.execute("UPDATE leads SET status='Booked', patient_id=?, updated_at=? WHERE phone=? AND status IN ('New','Contacted')",
               (p["id"], util.ts(now), p["phone"]))
    audit.log(_actor(p), "create", "appointment", aid, {"source": "Patient app", "token": token})
    branch = db.scalar("SELECT name FROM branches WHERE id = ?", (doc["branch_id"],))
    nice = when.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")
    note = "We have sent the details on WhatsApp."
    try:
        messaging.send(p["phone"], "appt_confirmation",
                       f"Booked ✅\n{doc['name']} ({doc['specialty']})\n{nice}\n{_hospital()}, {branch}\nBooking ID: OPD-{aid}",
                       patient_id=p["id"], related_type="appointment", related_id=aid, actor=_actor(p))
    except messaging.SendBlocked:
        note = "The confirmation will not be sent on WhatsApp because messages are turned off."
    return _go("/my/", msg=f"Booked with {doc['name']} on {nice}. {note}")


# ---------- bills ----------

@router.get("/bills")
def bills(request: Request):
    p = _me(request)
    rows = _bills(p["id"])
    return _page(request, "patient/bills.html", p, bills=rows, due_total=sum(b["balance"] for b in rows if b["balance"] > 0))


def _bill_ctx(p: dict, bill_id: int) -> dict:
    bill = _own("SELECT bl.*, bl.total - bl.paid AS balance FROM bills bl WHERE bl.id = ?", p["id"], bill_id, "bill")
    bill["branch"] = db.scalar("SELECT name FROM branches WHERE id = ?", (bill["branch_id"],))
    return {"bill": bill,
            "items": db.query("SELECT * FROM bill_items WHERE bill_id = ? ORDER BY id", (bill_id,)),
            "payments": db.query("SELECT * FROM payments WHERE bill_id = ? ORDER BY paid_at", (bill_id,))}


@router.get("/bills/{bill_id}")
def bill_detail(request: Request, bill_id: int):
    p = _me(request)
    try:
        return _page(request, "patient/bill.html", p, **_bill_ctx(p, bill_id))
    except LookupError:
        return _not_found(request, p, "bill")


@router.get("/bills/{bill_id}/pay")
def pay_page(request: Request, bill_id: int):
    p = _me(request)
    try:
        ctx = _bill_ctx(p, bill_id)
    except LookupError:
        return _not_found(request, p, "bill")
    if ctx["bill"]["balance"] <= 0:
        return _go(f"/my/bills/{bill_id}", msg="This bill is already paid.")
    return _page(request, "patient/pay.html", p, **ctx)


@router.post("/bills/{bill_id}/pay")
async def pay_submit(request: Request, bill_id: int):
    p, _ = await _me_post(request)
    try:
        ctx = _bill_ctx(p, bill_id)
    except LookupError:
        return _not_found(request, p, "bill")
    bal = ctx["bill"]["balance"]
    if bal <= 0:
        return _go(f"/my/bills/{bill_id}", msg="This bill is already paid.")
    if not demo_mode():
        return _go(f"/my/bills/{bill_id}", err="Online payment is not set up yet. Please pay at the billing counter.")
    billing.record_payment(bill_id, bal, "UPI", actor=_actor(p))
    return _go(f"/my/bills/{bill_id}", msg=f"Payment of {util.inr(bal)} received. Thank you.")


# ---------- reports ----------

REPORT_SQL = ("SELECT o.*, b.name AS branch FROM orders o JOIN branches b ON b.id = o.branch_id"
              " WHERE o.patient_id = ? AND (o.dept LIKE '%Lab%' OR o.dept LIKE '%Radiology%') ORDER BY o.created_at DESC")


@router.get("/reports")
def reports(request: Request):
    p = _me(request)
    return _page(request, "patient/reports.html", p, reports=db.query(REPORT_SQL, (p["id"],)))


SAMPLE_RESULTS = [("Haemoglobin", "13.8", "g/dL", "13.0 – 17.0"), ("WBC count", "7,200", "/µL", "4,000 – 11,000"),
                  ("Platelets", "2.6", "lakh/µL", "1.5 – 4.0"), ("SGPT (ALT)", "32", "U/L", "7 – 56"),
                  ("SGOT (AST)", "28", "U/L", "10 – 40"), ("Bilirubin, total", "0.8", "mg/dL", "0.3 – 1.2")]


@router.get("/reports/{order_id}")
def report_detail(request: Request, order_id: int):
    p = _me(request)
    try:
        o = _own("SELECT o.*, b.name AS branch FROM orders o JOIN branches b ON b.id = o.branch_id WHERE o.id = ?",
                 p["id"], order_id, "report")
    except LookupError:
        return _not_found(request, p, "report")
    lab = diagnostics.patient_results(order_id)   # Pro: real results, only once validated
    if lab is not None:
        state, rows = lab
        explainer = None
        if state == "validated":
            # Doctor-approved text about what the test measures; never about the patient's own value.
            from app.ai_features import explainers
            code = db.scalar("SELECT test_code FROM lab_orders WHERE order_id = ?", (order_id,))
            explainer = explainers.for_patient(code, _lang(request)) if code else None
        return _page(request, "patient/report.html", p, order=o, results=rows if state == "validated" else None,
                     validated=state == "validated", explainer=explainer)
    return _page(request, "patient/report.html", p, order=o, results=SAMPLE_RESULTS if demo_mode() else None)


# ---------- profile ----------

@router.get("/profile")
def profile(request: Request):
    p = _me(request)
    return _page(request, "patient/profile.html", p)


@router.post("/profile/consent")
async def profile_consent(request: Request):
    p, form = await _me_post(request)
    on = form.get("consent") == "1"
    patients.set_consent(p["id"], on, actor=_actor(p))
    return _go("/my/profile", msg="WhatsApp messages turned on." if on else "WhatsApp messages turned off.")


# ---------- feedback ----------

def _visited(p: dict, appt_id: int) -> dict:
    a = _own("SELECT a.*, d.name AS doctor FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE a.id = ?",
             p["id"], appt_id, "appointment")
    if a["status"] != "Visited":
        raise LookupError("appointment")
    return a


@router.get("/feedback/{appt_id}")
def feedback_page(request: Request, appt_id: int):
    p = _me(request)
    try:
        a = _visited(p, appt_id)
    except LookupError:
        return _not_found(request, p, "visit")
    done = db.one("SELECT * FROM feedback WHERE appointment_id = ?", (appt_id,))
    return _page(request, "patient/feedback.html", p, appt=a, done=done, review_link=config.settings.review_link)


@router.post("/feedback/{appt_id}")
async def feedback_submit(request: Request, appt_id: int):
    p, form = await _me_post(request)
    try:
        a = _visited(p, appt_id)
    except LookupError:
        return _not_found(request, p, "visit")
    if db.one("SELECT id FROM feedback WHERE appointment_id = ?", (appt_id,)):
        return _go(f"/my/feedback/{appt_id}")
    try:
        score = int(form.get("score", ""))
    except ValueError:
        score = 0
    if not 1 <= score <= 5:
        return _go(f"/my/feedback/{appt_id}", err="Please choose a rating from 1 to 5.")
    comment = str(form.get("comment", "")).strip()[:1000] or None
    now = util.now()
    low = score <= 3
    fid = db.execute("INSERT INTO feedback(patient_id, appointment_id, score, comment, escalated, created_at) VALUES (?,?,?,?,?,?)",
                     (p["id"], appt_id, score, comment, 1 if low else 0, util.ts(now)))
    if low:
        db.execute("INSERT OR IGNORE INTO tasks(kind, title, branch_id, related_type, related_id, status, due_at, created_at)"
                   " VALUES ('complaint', ?, ?, 'feedback', ?, 'Open', ?, ?)",
                   (f"{p['name']} rated {score}/5 (patient app)" + (f": {comment[:80]}" if comment else ""),
                    a["branch_id"], fid, util.ts(now + timedelta(hours=24)), util.ts(now)))
    audit.log(_actor(p), "feedback", "feedback", fid, {"score": score})
    return _go(f"/my/feedback/{appt_id}")


# ---------- PWA ----------

@router.get("/manifest.webmanifest")
def manifest():
    name = f"{_hospital()} · {config.PRODUCT_NAME}"
    body = {"name": name, "short_name": _hospital()[:12] or config.PRODUCT_NAME, "start_url": "/my/", "scope": "/my/", "display": "standalone",
            "background_color": "#f3f7f5", "theme_color": "#0b6e4f",
            "icons": [{"src": "/static/icons/patient-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/static/icons/patient-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "/static/icons/patient-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
    return Response(json.dumps(body), media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker():
    js = (Path(__file__).resolve().parent.parent / "static" / "patient-sw.js").read_text()
    return Response(js, media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/my/", "Cache-Control": "no-cache"})
