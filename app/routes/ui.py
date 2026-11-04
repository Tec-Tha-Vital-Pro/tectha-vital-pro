"""Staff screens (server-rendered). Every page needs a login; every POST checks the CSRF token."""
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from fastapi.templating import Jinja2Templates

from app import audit, auth, config, db, metrics, patients, security, util
from app.auth import ADMIN, BILLING, BILLING_VIEW, CLINICAL, FRONT, OWNER_VIEW, STAFF

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
TEMPLATES.env.filters["inr"] = util.inr
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def inr_short(v: int | float) -> str:
    """Axis-friendly rupees: ₹950, ₹12k, ₹1.5L, ₹2.1Cr."""
    v = float(v)
    if v >= 1e7:
        return f"₹{v / 1e7:.1f}".rstrip("0").rstrip(".") + "Cr"
    if v >= 1e5:
        return f"₹{v / 1e5:.1f}".rstrip("0").rstrip(".") + "L"
    if v >= 1e3:
        return f"₹{v / 1e3:.0f}k"
    return f"₹{v:.0f}"


TEMPLATES.env.filters["inr_short"] = inr_short

LEAD_SOURCES = ["WhatsApp", "Phone call", "Website form", "Google", "Facebook ad", "Instagram ad", "Practo", "Walk-in", "Referral"]
LEAD_STATUSES = ["New", "Contacted", "Booked", "Converted", "Lost"]
APPT_STATUSES = ["Booked", "Confirmed", "Visited", "NoShow", "Cancelled"]
CLAIM_STAGES = [("PreAuthRequested", "Pre-auth requested"), ("PreAuthApproved", "Pre-auth approved"),
                ("FinalSent", "Final bill sent"), ("Settled", "Settled"), ("Denied", "Denied")]
TASK_KINDS = {"missed_call": "Missed calls", "complaint": "Complaints", "claim_stuck": "Stuck claims",
              "unbilled": "Unbilled services", "followup_call": "Follow-up calls"}
PAY_MODES = ["UPI", "Card", "Cash", "Insurance"]

TASK_ROLES = STAFF - {"doctor", "owner"}

# (href, label, roles, group, icon)
NAV = [
    ("/", "Dashboard", OWNER_VIEW, "Overview", "dashboard"),
    ("/tasks", "Tasks", STAFF - {"doctor", "owner"}, "Overview", "tasks"),
    ("/leads", "Enquiries", FRONT, "Patients & front desk", "inbox"),
    ("/appointments", "Appointments", CLINICAL, "Patients & front desk", "calendar"),
    ("/patients", "Patients", CLINICAL, "Patients & front desk", "users"),
    ("/messages", "Messages", FRONT, "Patients & front desk", "chat"),
    ("/billing", "Billing", BILLING_VIEW, "Money", "rupee"),
    ("/claims", "Claims", BILLING_VIEW, "Money", "shield"),
    ("/import", "Import", ADMIN, "Admin", "upload"),
    ("/settings", "Settings", ADMIN, "Admin", "settings"),
    ("/audit", "Audit log", ADMIN, "Admin", "audit"),
]
# Bottom tab bar on phones: the most used screens per role (the rest go under "More").
TABS = {
    "admin": ["/", "/leads", "/billing", "/messages"],
    "owner": ["/", "/billing", "/claims"],
    "frontdesk": ["/leads", "/appointments", "/messages", "/tasks"],
    "billing": ["/billing", "/claims", "/tasks"],
    "doctor": ["/appointments", "/patients"],
}
BRANCH_AWARE = {"/", "/leads", "/appointments", "/billing", "/claims", "/tasks"}
HOME = {"admin": "/", "owner": "/", "frontdesk": "/leads", "billing": "/billing", "doctor": "/appointments"}


class UIRoute(APIRoute):
    """Turns auth exceptions raised anywhere in a handler into the right page."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except auth.LoginRequired:
                nxt = request.url.path
                return RedirectResponse("/login" + (f"?next={quote(nxt)}" if nxt != "/" else ""), status_code=303)
            except auth.Forbidden:
                return _error(request, 403, "You don't have access to this screen",
                              "Ask an admin to change your role if you need it.")
            except auth.CsrfFailed:
                return _error(request, 403, "This form has expired",
                              "Go back, reload the page and submit again.")
            except auth.NotFound as e:
                return _error(request, 404, f"We could not find that {e.what}",
                              "It may have been removed, or it is not part of your branch. Go back and reload the list.")
        return wrapped


router = APIRouter(route_class=UIRoute)


# ---------------------------------------------------------------- helpers

def _branches() -> list[dict]:
    return db.query("SELECT id, name FROM branches ORDER BY id")


def _hospital() -> str:
    return db.get_setting("hospital_name", "Your Hospital")


def _active(href: str, path: str) -> bool:
    return path == "/" if href == "/" else path.startswith(href)


def render(request: Request, name: str, user: dict | None, status_code: int = 200, **ctx) -> HTMLResponse:
    path = request.url.path
    items = [{"href": h, "label": lbl, "group": g, "icon": ic, "active": _active(h, path)}
             for h, lbl, roles, g, ic in NAV if user and user["role"] in roles]
    groups: list[dict] = []
    for it in items:
        if not groups or groups[-1]["name"] != it["group"]:
            groups.append({"name": it["group"], "items": []})
        groups[-1]["items"].append(it)
    tab_hrefs = TABS.get(user["role"], []) if user else []
    tabs = [it for h in tab_hrefs for it in items if it["href"] == h]
    more = [it for it in items if it["href"] not in tab_hrefs]
    initials = "".join(w[0] for w in (user["full_name"].split()[:2] if user else [])).upper() or "?"
    base = {
        "user": user, "nav": [(it["href"], it["label"]) for it in items], "nav_groups": groups,
        "tabs": tabs, "more": more, "more_active": any(it["active"] for it in more),
        "path": path, "hospital": _hospital(), "initials": initials,
        "branches": _branches(), "msg": request.query_params.get("msg"), "err": request.query_params.get("err"),
        "csrf": user["csrf"] if user else "",
        "branch_aware": bool(user and not user["branch_id"] and path in BRANCH_AWARE),
        "cur_branch": request.query_params.get("branch", ""),
        "can_search": bool(user and user["role"] in CLINICAL),
        "query": dict(request.query_params),
    }
    base.update(ctx)
    return TEMPLATES.TemplateResponse(request, name, base, status_code=status_code)


def _error(request: Request, code: int, title: str, detail: str) -> HTMLResponse:
    return render(request, "error.html", auth.current_user(request), status_code=code, title=title, detail=detail, code=code)


def back(path: str, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    q = []
    if msg:
        q.append("msg=" + quote(msg))
    if err:
        q.append("err=" + quote(err))
    sep = "&" if "?" in path else "?"
    return RedirectResponse(path + (sep + "&".join(q) if q else ""), status_code=303)


def _scope(user: dict, requested: str | None) -> str | None:
    """A branch-bound user only ever sees their branch."""
    if user["branch_id"]:
        return user["branch_id"]
    return requested if requested in {b["id"] for b in _branches()} else None


def _branch_sql(col: str, branch: str | None) -> tuple[str, tuple]:
    return (f" AND {col} = ?", (branch,)) if branch else ("", ())


# Tables whose rows belong to one branch, and the word used in the "not found" page.
_BRANCH_TABLES = {"leads": "enquiry", "appointments": "appointment", "bills": "bill", "orders": "service order",
                  "claims": "claim", "tasks": "task"}
# Tasks with no branch (an emergency or a WhatsApp reply nobody has routed yet) are a shared queue:
# every branch must see them so an emergency is never hidden. Other records with no branch belong
# to unbound (all-branch) staff only.
_SHARED_WHEN_NO_BRANCH = {"tasks"}


def _own(user: dict, table: str, row_id: int) -> dict:
    """Load one branch record for this user, or raise NotFound (404).

    A branch-bound user gets the same 404 for another branch's record as for a missing one,
    so ids from the other branch can't be probed. Use this in every route that takes an id.
    """
    what = _BRANCH_TABLES[table]
    row = db.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    if row is None:
        raise auth.NotFound(what)
    mine = user["branch_id"]
    if mine and row["branch_id"] != mine and not (row["branch_id"] is None and table in _SHARED_WHEN_NO_BRANCH):
        raise auth.NotFound(what)
    return row


def _active_in_branch_sql() -> str:
    """Patients with any record at a branch (one ? per subquery, all the same branch id)."""
    return ("SELECT patient_id FROM appointments WHERE branch_id = ? UNION SELECT patient_id FROM bills WHERE branch_id = ?"
            " UNION SELECT patient_id FROM orders WHERE branch_id = ? UNION SELECT patient_id FROM claims WHERE branch_id = ?"
            " UNION SELECT patient_id FROM followups WHERE branch_id = ?")


# Message types only admins may read: the owner's revenue report and patient login codes.
ADMIN_ONLY_TEMPLATES = ("owner_daily_report", "patient_otp")


def _message_scope(user: dict, alias: str = "m") -> tuple[str, tuple]:
    """SQL filter for the messages a user may read (S-13).

    Branch-bound staff see conversations of patients with activity in their branch, and of their
    branch's enquiries. Only admins see the owner report and login-code messages.
    """
    sql, params = "", []
    if user["role"] != "admin":
        sql += f" AND {alias}.template NOT IN ({','.join('?' * len(ADMIN_ONLY_TEMPLATES))})"
        params += ADMIN_ONLY_TEMPLATES
    br = user["branch_id"]
    if br:
        sql += (f" AND ({alias}.patient_id IN ({_active_in_branch_sql()})"
                f" OR {alias}.to_phone IN (SELECT phone FROM leads WHERE branch_id = ?))")
        params += [br] * 6
    return sql, tuple(params)


# ---------------------------------------------------------------- login

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", None, next=request.query_params.get("next", ""))


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("")):
    try:
        u = auth.authenticate(username, password, ip=security.client_ip(request))
    except auth.TooManyAttempts:
        return render(request, "login.html", None, status_code=429, next=next, username=username,
                      login_error="Too many wrong tries. Please wait 15 minutes and try again, "
                                  "or ask an admin to reset your password.")
    if u is None:
        return render(request, "login.html", None, status_code=401, next=next, username=username,
                      login_error="Wrong username or password.")
    dest = next if next.startswith("/") and not next.startswith("//") else HOME[u["role"]]
    resp = RedirectResponse(dest, status_code=303)
    auth.set_session_cookie(resp, request, u["id"])
    return resp


@router.post("/logout")
async def logout(request: Request):
    user = await auth.require_post(request, STAFF)
    auth.end_sessions(user["id"])  # a copied cookie stops working too, not just this browser's
    audit.log(auth.actor(user), "logout", "user", user["id"])
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- dashboard

def _chart(rows: list[dict], branches: list[dict]) -> dict:
    W, H, pl, pr, pt, pb = 640, 260, 52, 10, 14, 30
    iw, ih = W - pl - pr, H - pt - pb
    peak = max([r[b["id"]] for r in rows for b in branches] + [0])
    step = _nice_step(peak / 4 if peak else 1000)
    top = step * max(1, -(-peak // step)) if peak else step * 4
    grid = []
    v = 0
    while v <= top:
        y = pt + ih - (v / top) * ih
        grid.append({"y": round(y, 1), "label": inr_short(v)})
        v += step
    colors = ["var(--s1)", "var(--s2)", "var(--s3)"]
    n = max(1, len(branches))
    gw = iw / len(rows)
    bw = min(28, (gw - 12) / n)
    bars, labels = [], []
    for i, r in enumerate(rows):
        gx = pl + i * gw + (gw - bw * n) / 2
        for j, b in enumerate(branches):
            val = r[b["id"]]
            h = (val / top) * ih
            bars.append({"x": round(gx + j * bw + 1, 1), "y": round(pt + ih - h, 1), "w": round(bw - 2, 1),
                         "h": round(h, 1), "color": colors[j % 3], "title": f"{b['name']} {r['day']}: {util.inr(val)}"})
        d = datetime.strptime(r["day"], "%Y-%m-%d")
        labels.append({"x": round(pl + i * gw + gw / 2, 1), "text": d.strftime("%a %d")})
    legend = [{"name": b["name"], "color": colors[j % 3]} for j, b in enumerate(branches)]
    return {"W": W, "H": H, "pl": pl, "right": W - pr, "base": H - 10, "grid": grid, "bars": bars,
            "labels": labels, "legend": legend, "empty": peak == 0}


def _nice_step(raw: float) -> int:
    for s in (500, 1000, 2000, 5000, 10000, 20000, 25000, 50000, 100000, 200000, 250000, 500000, 1000000, 2000000, 5000000):
        if s >= raw:
            return s
    return 10000000


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, branch: str | None = None):
    user = auth.current_user(request)
    if user and user["role"] not in OWNER_VIEW:
        return RedirectResponse(HOME[user["role"]], status_code=303)
    user = auth.require(request, OWNER_VIEW)
    br = _scope(user, branch)
    today = util.now().date()
    yday = today - timedelta(days=1)
    k_today, k_yday = metrics.kpis(today, br), metrics.kpis(yday, br)
    k_prev = metrics.kpis(yday - timedelta(days=1), br)
    shown = [b for b in _branches() if not br or b["id"] == br]
    chart = _chart(metrics.collections_by_day(today, 7), shown)
    fun = metrics.funnel(today.replace(day=1), today, br)
    steps = [("Enquiries", fun["enquiries"]), ("Booked", fun["booked"]), ("Visited", fun["visited"]), ("Paid", fun["paid"])]
    report = db.one("SELECT body, created_at, status FROM messages WHERE template='owner_daily_report' ORDER BY id DESC LIMIT 1")
    return render(request, "dashboard.html", user, branch=br, today=today, yday=yday, k_today=k_today, k_yday=k_yday,
                  k_prev=k_prev, prev_day=yday - timedelta(days=1),
                  chart=chart, steps=steps, fun=fun, speed=metrics.reply_speed(today, br),
                  attention=metrics.attention(br), report=report)


# ---------------------------------------------------------------- leads

@router.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request, source: str = "", status: str = "", branch: str = ""):
    user = auth.require(request, FRONT)
    br = _scope(user, branch)
    sql = ("SELECT l.*, b.name AS branch_name FROM leads l LEFT JOIN branches b ON b.id=l.branch_id WHERE 1=1")
    params: list = []
    if source in LEAD_SOURCES:
        sql += " AND l.source = ?"
        params.append(source)
    if status in LEAD_STATUSES:
        sql += " AND l.status = ?"
        params.append(status)
    if br:
        sql += " AND l.branch_id = ?"
        params.append(br)
    rows = db.query(sql + " ORDER BY l.created_at DESC LIMIT 300", tuple(params))
    return render(request, "leads.html", user, rows=rows, sources=LEAD_SOURCES, statuses=LEAD_STATUSES,
                  f_source=source, f_status=status, f_branch=br or "")


@router.post("/leads")
async def lead_add(request: Request, name: str = Form(...), phone: str = Form(...), need: str = Form(""),
                   source: str = Form(...), branch_id: str = Form("")):
    user = await auth.require_post(request, FRONT)
    try:
        phone_n = util.normalize_phone(phone)
    except ValueError as e:
        return back("/leads", err=str(e))
    if source not in LEAD_SOURCES:
        return back("/leads", err="Choose a valid source.")
    br = user["branch_id"] or (branch_id if branch_id in {b["id"] for b in _branches()} else None)
    now = util.ts(util.now())
    lid = db.execute("INSERT INTO leads(name, phone, need, source, branch_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                     (name.strip(), phone_n, need.strip(), source, br, now, now))
    audit.log(auth.actor(user), "create", "lead", lid, {"source": source})
    return back("/leads", msg=f"Enquiry from {name.strip()} added.")


@router.post("/leads/{lead_id}/status")
async def lead_status(request: Request, lead_id: int, status: str = Form(...)):
    user = await auth.require_post(request, FRONT)
    lead = _own(user, "leads", lead_id)
    if status not in LEAD_STATUSES:
        return back("/leads", err="Unknown status.")
    now = util.now()
    first = lead["first_reply_seconds"]
    if first is None and status != "New":
        first = int((now - util.parse(lead["created_at"])).total_seconds())
    db.execute("UPDATE leads SET status = ?, first_reply_seconds = ?, updated_at = ? WHERE id = ?",
               (status, first, util.ts(now), lead_id))
    audit.log(auth.actor(user), "status", "lead", lead_id, {"from": lead["status"], "to": status})
    return back("/leads", msg=f"{lead['name']}: {status}.")


# ---------------------------------------------------------------- appointments

@router.get("/appointments", response_class=HTMLResponse)
def appointments_page(request: Request, day: str = "", branch: str = ""):
    user = auth.require(request, CLINICAL)
    try:
        d = date.fromisoformat(day) if day else util.now().date()
    except ValueError:
        d = util.now().date()
    br = _scope(user, branch)
    f, p = _branch_sql("a.branch_id", br)
    rows = db.query(
        "SELECT a.*, pt.name, pt.phone, pt.uid, pt.id AS pid, dr.name AS doctor, dr.specialty, b.name AS branch_name"
        " FROM appointments a JOIN patients pt ON pt.id=a.patient_id JOIN doctors dr ON dr.id=a.doctor_id"
        f" JOIN branches b ON b.id=a.branch_id WHERE date(a.starts_at) = ?{f} ORDER BY a.starts_at, a.token_no",
        (d.isoformat(), *p))
    fd, pd = _branch_sql("branch_id", br)
    doctors = db.query(f"SELECT d.*, b.name AS branch_name FROM doctors d JOIN branches b ON b.id=d.branch_id WHERE 1=1{fd.replace('branch_id','d.branch_id')} ORDER BY d.name", pd)
    default_time = (util.now() + timedelta(hours=1)).replace(minute=0).strftime("%Y-%m-%dT%H:%M")
    return render(request, "appointments.html", user, rows=rows, day=d, doctors=doctors, f_branch=br or "",
                  prev=(d - timedelta(days=1)).isoformat(), next_day=(d + timedelta(days=1)).isoformat(),
                  default_time=default_time)


@router.post("/appointments/book")
async def appointment_book(request: Request, name: str = Form(...), phone: str = Form(...), doctor_id: int = Form(...),
                           starts_at: str = Form(...), consent: str = Form("")):
    user = await auth.require_post(request, CLINICAL)
    doc = db.one("SELECT * FROM doctors WHERE id = ?", (doctor_id,))
    if doc is None:
        return back("/appointments", err="Choose a doctor.")
    if user["branch_id"] and doc["branch_id"] != user["branch_id"]:
        raise auth.Forbidden()
    try:
        when = datetime.strptime(starts_at, "%Y-%m-%dT%H:%M")
    except ValueError:
        return back("/appointments", err="Pick a valid date and time.")
    try:
        p = patients.find_or_create(name, phone, consent=True if consent == "1" else None, actor=auth.actor(user))
    except ValueError as e:
        return back("/appointments", err=str(e))
    token = (db.scalar("SELECT COALESCE(MAX(token_no),0) FROM appointments WHERE branch_id = ? AND date(starts_at) = ?",
                       (doc["branch_id"], when.date().isoformat())) or 0) + 1
    aid = db.execute(
        "INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, token_no, source, created_at)"
        " VALUES (?,?,?,?, 'Booked', ?, 'Front desk', ?)",
        (p["id"], doc["id"], doc["branch_id"], util.ts(when), token, util.ts(util.now())))
    db.execute("UPDATE leads SET status='Booked', patient_id=?, updated_at=? WHERE phone=? AND status IN ('New','Contacted')",
               (p["id"], util.ts(util.now()), p["phone"]))
    audit.log(auth.actor(user), "create", "appointment", aid, {"patient": p["uid"], "token": token})
    return back(f"/appointments?day={when.date().isoformat()}",
                msg=f"Booked {p['name']} ({p['uid']}) with {doc['name']}, token {token}.")


@router.post("/appointments/{appt_id}/status")
async def appointment_status(request: Request, appt_id: int, status: str = Form(...)):
    user = await auth.require_post(request, CLINICAL)
    a = _own(user, "appointments", appt_id)
    if status not in APPT_STATUSES:
        return back("/appointments", err="Unknown status.")
    db.execute("UPDATE appointments SET status = ? WHERE id = ?", (status, appt_id))
    audit.log(auth.actor(user), "status", "appointment", appt_id, {"from": a["status"], "to": status})
    return back(f"/appointments?day={a['starts_at'][:10]}", msg=f"Token {a['token_no']}: {status}.")


# ---------------------------------------------------------------- patients

@router.get("/patients", response_class=HTMLResponse)
def patients_page(request: Request, q: str = ""):
    user = auth.require(request, CLINICAL)
    q = q.strip()
    if q:
        like = f"%{q}%"
        digits = "".join(c for c in q if c.isdigit())
        rows = db.query(
            "SELECT * FROM patients WHERE name LIKE ? OR uid LIKE ? OR (? <> '' AND phone LIKE ?) ORDER BY name LIMIT 100",
            (like, like, digits, f"%{digits}%"))
    else:
        rows = db.query("SELECT * FROM patients ORDER BY id DESC LIMIT 50")
    return render(request, "patients.html", user, rows=rows, q=q)


@router.get("/patients/{patient_id}", response_class=HTMLResponse)
def patient_page(request: Request, patient_id: int):
    user = auth.require(request, CLINICAL)
    p = db.one("SELECT * FROM patients WHERE id = ?", (patient_id,))
    if p is None:
        return _error(request, 404, "Patient not found", "Search again from the Patients screen.")
    # Name, TT-ID and phone are shared across branches (one patient ID); visits, bills, messages and
    # feedback are branch-private for branch-bound staff (S-12).
    br = user["branch_id"]
    fa, pa = _branch_sql("a.branch_id", br)
    appts = db.query("SELECT a.*, d.name AS doctor, b.name AS branch_name FROM appointments a JOIN doctors d ON d.id=a.doctor_id"
                     f" JOIN branches b ON b.id=a.branch_id WHERE a.patient_id = ?{fa} ORDER BY a.starts_at DESC", (patient_id, *pa))
    fb_, pb = _branch_sql("bl.branch_id", br)
    bills = db.query("SELECT bl.*, b.name AS branch_name FROM bills bl JOIN branches b ON b.id=bl.branch_id"
                     f" WHERE bl.patient_id = ?{fb_} ORDER BY bl.created_at DESC", (patient_id, *pb))
    fm, pm = _message_scope(user)
    msgs = db.query(f"SELECT * FROM messages m WHERE m.patient_id = ?{fm} ORDER BY m.id DESC LIMIT 50", (patient_id, *pm))
    if br:
        fb = db.query("SELECT f.* FROM feedback f JOIN appointments a ON a.id = f.appointment_id"
                      " WHERE f.patient_id = ? AND a.branch_id = ? ORDER BY f.created_at DESC", (patient_id, br))
    else:
        fb = db.query("SELECT * FROM feedback WHERE patient_id = ? ORDER BY created_at DESC", (patient_id,))
    audit.log(auth.actor(user), "view", "patient", patient_id)
    return render(request, "patient.html", user, p=p, appts=appts, bills=bills, msgs=msgs, feedback=fb)


@router.post("/patients/{patient_id}/consent")
async def patient_consent(request: Request, patient_id: int, consent: str = Form(...)):
    user = await auth.require_post(request, CLINICAL)
    if db.one("SELECT id FROM patients WHERE id = ?", (patient_id,)) is None:
        return back("/patients", err="Patient not found.")
    patients.set_consent(patient_id, consent == "1", actor=auth.actor(user))
    return back(f"/patients/{patient_id}", msg="Consent given: messages allowed." if consent == "1"
                else "Consent withdrawn: no more messages will be sent.")


# ---------------------------------------------------------------- billing

@router.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request, branch: str = ""):
    user = auth.require(request, BILLING_VIEW)
    from app import billing
    br = _scope(user, branch)
    dues = billing.dues(branch=br)
    f, p = _branch_sql("o.branch_id", br)
    unbilled = db.query(
        "SELECT o.*, pt.name, pt.uid, b.name AS branch_name FROM orders o JOIN patients pt ON pt.id=o.patient_id"
        f" JOIN branches b ON b.id=o.branch_id WHERE o.bill_id IS NULL{f} ORDER BY o.created_at", p)
    return render(request, "billing.html", user, dues=dues, unbilled=unbilled, f_branch=br or "", modes=PAY_MODES,
                  readonly=user["role"] not in BILLING,
                  total_due=sum(d["balance"] for d in dues), total_unbilled=sum(o["amount"] for o in unbilled))


@router.post("/billing/{bill_id}/remind")
async def billing_remind(request: Request, bill_id: int):
    user = await auth.require_post(request, BILLING)
    from app import automations, messaging
    bill = _own(user, "bills", bill_id)
    if bill["total"] <= bill["paid"]:
        return back("/billing", err=f"Bill {bill['bill_no']} is already fully paid, so no reminder was sent.")
    try:
        automations.send_dues_reminder(bill_id, util.now())
    except messaging.SendBlocked:
        return back("/billing", err="Not sent: this patient has not given consent for messages.")
    except (ValueError, LookupError):
        # Paid or removed by someone else a moment ago.
        return back("/billing", err=f"Bill {bill['bill_no']} has no balance due any more, so no reminder was sent.")
    audit.log(auth.actor(user), "manual_reminder", "bill", bill_id)
    return back("/billing", msg="Payment reminder sent on WhatsApp.")


@router.post("/billing/{bill_id}/payment")
async def billing_payment(request: Request, bill_id: int, amount: int = Form(...), mode: str = Form(...)):
    user = await auth.require_post(request, BILLING)
    from app import billing
    _own(user, "bills", bill_id)
    if amount <= 0 or mode not in PAY_MODES:
        return back("/billing", err="Enter an amount above zero and a payment mode.")
    try:
        billing.record_payment(bill_id, amount, mode, actor=auth.actor(user))
    except (ValueError, LookupError) as e:
        return back("/billing", err=str(e))
    return back("/billing", msg=f"Payment of {util.inr(amount)} recorded.")


@router.post("/billing/orders/{order_id}/add")
async def billing_add_order(request: Request, order_id: int):
    user = await auth.require_post(request, BILLING)
    from app import billing
    _own(user, "orders", order_id)
    try:
        bill_id = billing.add_order_to_bill(order_id, actor=auth.actor(user))
    except (ValueError, LookupError) as e:
        return back("/billing", err=str(e))
    no = db.scalar("SELECT bill_no FROM bills WHERE id = ?", (bill_id,))
    return back("/billing", msg=f"Added to bill {no}.")


# ---------------------------------------------------------------- claims

@router.get("/claims", response_class=HTMLResponse)
def claims_page(request: Request, branch: str = ""):
    user = auth.require(request, BILLING_VIEW)
    br = _scope(user, branch)
    f, p = _branch_sql("c.branch_id", br)
    rows = db.query(
        "SELECT c.*, pt.name, pt.uid, b.name AS branch_name,"
        " EXISTS (SELECT 1 FROM tasks t WHERE t.kind='claim_stuck' AND t.status='Open' AND t.related_type='claim' AND t.related_id=c.id) AS stuck"
        " FROM claims c JOIN patients pt ON pt.id=c.patient_id JOIN branches b ON b.id=c.branch_id"
        f" WHERE 1=1{f} ORDER BY c.stage_changed_at", p)
    now = util.now()
    for r in rows:
        mins = int((now - util.parse(r["stage_changed_at"])).total_seconds() // 60)
        r["waiting"] = f"{mins // 60} h {mins % 60:02d} m" if mins < 48 * 60 else f"{mins // 1440} days"
    cols = [{"key": k, "label": lbl, "cards": [r for r in rows if r["stage"] == k]} for k, lbl in CLAIM_STAGES]
    return render(request, "claims.html", user, cols=cols, stages=CLAIM_STAGES, f_branch=br or "",
                  readonly=user["role"] not in BILLING)


@router.post("/claims/{claim_id}/stage")
async def claim_stage(request: Request, claim_id: int, stage: str = Form(...)):
    user = await auth.require_post(request, BILLING)
    from app import billing
    _own(user, "claims", claim_id)
    if stage not in dict(CLAIM_STAGES):
        return back("/claims", err="Unknown stage.")
    try:
        billing.set_claim_stage(claim_id, stage, actor=auth.actor(user))
    except (ValueError, LookupError) as e:
        return back("/claims", err=str(e))
    return back("/claims", msg=f"Claim moved to {dict(CLAIM_STAGES)[stage]}.")


# ---------------------------------------------------------------- tasks

@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, branch: str = ""):
    user = auth.require(request, TASK_ROLES)
    br = _scope(user, branch)
    # Unrouted tasks (no branch, e.g. a possible emergency on WhatsApp) show at every branch.
    f, p = (" AND (t.branch_id = ? OR t.branch_id IS NULL)", (br,)) if br else ("", ())
    rows = db.query("SELECT t.*, b.name AS branch_name FROM tasks t LEFT JOIN branches b ON b.id=t.branch_id"
                    f" WHERE t.status='Open'{f} ORDER BY COALESCE(t.due_at, t.created_at)", p)
    now = util.ts(util.now())
    groups = []
    for kind, label in TASK_KINDS.items():
        items = [dict(r, overdue=bool(r["due_at"] and r["due_at"] < now)) for r in rows if r["kind"] == kind]
        if items:
            groups.append({"label": label, "tasks": items})
    return render(request, "tasks.html", user, groups=groups, f_branch=br or "", total=len(rows))


@router.post("/tasks/{task_id}/done")
async def task_done(request: Request, task_id: int):
    user = await auth.require_post(request, TASK_ROLES)
    t = _own(user, "tasks", task_id)
    db.execute("UPDATE tasks SET status='Done' WHERE id = ?", (task_id,))
    audit.log(auth.actor(user), "done", "task", task_id, {"kind": t["kind"]})
    return back("/tasks", msg="Task marked done.")


# ---------------------------------------------------------------- messages

@router.get("/messages", response_class=HTMLResponse)
def messages_page(request: Request, phone: str = "", q: str = ""):
    user = auth.require(request, FRONT)
    scope_sql, scope_params = _message_scope(user)
    rows = db.query("SELECT m.*, p.name, p.uid, p.id AS pid FROM messages m LEFT JOIN patients p ON p.id=m.patient_id"
                    f" WHERE 1=1{scope_sql} ORDER BY m.id DESC LIMIT 500", scope_params)
    owner = config.settings.owner_phone
    convs: dict[str, dict] = {}
    for m in rows:
        c = convs.get(m["to_phone"])
        if c is None:
            title = "Owner's daily report" if m["to_phone"] == owner and not m["name"] else (m["name"] or "+" + m["to_phone"])
            c = convs[m["to_phone"]] = {"phone": m["to_phone"], "title": title, "uid": m["uid"], "pid": m["pid"],
                                        "last": m, "count": 0, "unread_in": m["direction"] == "in"}
        c["count"] += 1
        if not c["uid"] and m["uid"]:
            c["uid"], c["pid"] = m["uid"], m["pid"]
    conv_list = list(convs.values())
    qd = "".join(ch for ch in q if ch.isdigit())
    if q.strip():
        ql = q.strip().lower()
        conv_list = [c for c in conv_list if ql in c["title"].lower() or (qd and qd in c["phone"])]
    digits = "".join(ch for ch in phone if ch.isdigit())
    selected = None
    if digits:
        selected = next((c for c in convs.values() if c["phone"].endswith(digits) or digits in c["phone"]), None)
    if selected is None and conv_list and not digits:
        selected = conv_list[0]
    thread = []
    if selected:
        thread = db.query(f"SELECT * FROM messages m WHERE m.to_phone = ?{scope_sql} ORDER BY m.id DESC LIMIT 200",
                          (selected["phone"], *scope_params))[::-1]
    return render(request, "messages.html", user, convs=conv_list, selected=selected, thread=thread, phone=phone, q=q,
                  simulator=config.settings.whatsapp_mode == "simulator")


# ---------------------------------------------------------------- settings

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = auth.require(request, ADMIN)
    users = db.query("SELECT u.*, b.name AS branch_name FROM users u LEFT JOIN branches b ON b.id=u.branch_id ORDER BY u.username")
    return render(request, "settings.html", user, users=users, roles=auth.ROLES, mode=config.settings.whatsapp_mode,
                  run=request.query_params.get("run"), me_id=user["id"])


@router.post("/settings/names")
async def settings_names(request: Request):
    user = await auth.require_post(request, ADMIN)
    form = await request.form()
    name = str(form.get("hospital_name", "")).strip()
    if not name:
        return back("/settings", err="Hospital name can't be empty.")
    db.set_setting("hospital_name", name)
    for b in _branches():
        new = str(form.get(f"branch_{b['id']}", "")).strip()
        if new and new != b["name"]:
            db.execute("UPDATE branches SET name = ? WHERE id = ?", (new, b["id"]))
    audit.log(auth.actor(user), "update", "settings", None, {"hospital_name": name})
    return back("/settings", msg="Names saved.")


@router.post("/settings/run-automations")
async def settings_run(request: Request):
    user = await auth.require_post(request, ADMIN)
    from app import automations
    counts = automations.run_all(util.now())
    audit.log(auth.actor(user), "run_automations", "settings", None, counts)
    return back("/settings", msg=f"Automations ran. {automations.summary(counts)}")


@router.post("/settings/users")
async def settings_add_user(request: Request, username: str = Form(...), full_name: str = Form(...),
                            password: str = Form(...), role: str = Form(...), branch_id: str = Form("")):
    user = await auth.require_post(request, ADMIN)
    if branch_id and branch_id not in {b["id"] for b in _branches()}:
        return back("/settings", err="Unknown branch.")
    try:
        auth.create_user(username, full_name, password, role, branch_id or None, actor=auth.actor(user))
    except ValueError as e:
        return back("/settings", err=str(e))
    return back("/settings", msg=f"User {username.strip().lower()} added.")


def _staff_login(user_id: int) -> dict:
    u = db.one("SELECT id, username, active FROM users WHERE id = ?", (user_id,))
    if u is None:
        raise auth.NotFound("staff login")
    return u


@router.post("/settings/users/{user_id}/active")
async def settings_user_active(request: Request, user_id: int, active: str = Form(...)):
    user = await auth.require_post(request, ADMIN)
    u = _staff_login(user_id)
    on = active == "1"
    if not on and u["id"] == user["id"]:
        return back("/settings", err="You can't deactivate your own login. Ask another admin.")
    auth.set_active(u["id"], on, actor=auth.actor(user))
    return back("/settings", msg=f"{u['username']} can log in again." if on
                else f"{u['username']} is deactivated and logged out everywhere.")


@router.post("/settings/users/{user_id}/password")
async def settings_user_password(request: Request, user_id: int, password: str = Form(...)):
    user = await auth.require_post(request, ADMIN)
    u = _staff_login(user_id)
    try:
        auth.set_password(u["id"], password, actor=auth.actor(user))
    except ValueError as e:
        return back("/settings", err=str(e))
    if u["id"] == user["id"]:
        resp = back("/login", msg="Password changed. Please log in again.")
        resp.delete_cookie(auth.COOKIE, path="/")
        return resp
    return back("/settings", msg=f"Password for {u['username']} changed. They must log in again.")


# ---------------------------------------------------------------- import

@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    user = auth.require(request, ADMIN)
    return render(request, "import.html", user, result=None)


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
TOO_BIG = "The file is larger than 5 MB. Split it into smaller files (for example one month each) and upload them one by one."


@router.post("/import", response_class=HTMLResponse)
async def import_run(request: Request):
    # Refuse an oversized upload before parsing it (S-14). Chunked uploads without a length are
    # still capped below when the file is read.
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared = 0
    if declared > MAX_UPLOAD_BYTES + 64 * 1024:
        user = auth.require(request, ADMIN)
        return render(request, "import.html", user, status_code=413, result=None, import_error=TOO_BIG)
    user = await auth.require_post(request, ADMIN)
    from app.integrations import csv_import
    form = await request.form()
    kind, file = str(form.get("kind", "")), form.get("file")
    if file is None or isinstance(file, str):
        return render(request, "import.html", user, status_code=400, result=None, import_error="Choose a CSV file to upload.")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return render(request, "import.html", user, status_code=413, result=None, import_error=TOO_BIG)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return render(request, "import.html", user, result=None,
                      import_error="The file is not UTF-8 text. Save it from Excel as 'CSV UTF-8' and upload again.")
    if kind not in ("patients", "bills"):
        return render(request, "import.html", user, result=None, import_error="Choose what the file contains.")
    if text.count("\n") > csv_import.MAX_ROWS + 1:
        return render(request, "import.html", user, status_code=413, result=None,
                      import_error=f"The file has more than {csv_import.MAX_ROWS:,} rows. Split it into smaller files.")
    try:
        if kind == "patients":
            result = csv_import.import_patients(text, auth.actor(user))
        else:
            result = csv_import.import_bills(text, auth.actor(user), only_branch=user["branch_id"])
    except ValueError as e:  # e.g. missing columns: nothing was imported
        return render(request, "import.html", user, status_code=400, result=None, import_error=str(e))
    return render(request, "import.html", user, result=result, kind=kind, filename=file.filename)


# ---------------------------------------------------------------- audit

@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    user = auth.require(request, ADMIN)
    rows = db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")
    return render(request, "audit.html", user, rows=rows)


# ---------------------------------------------------------------- installable app (PWA)

@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from the root so it can control every page; it only ever caches /static files.
    return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})
