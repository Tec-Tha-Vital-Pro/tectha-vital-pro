"""Staff screens (server-rendered). Every page needs a login; every POST checks the CSRF token."""
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from fastapi.templating import Jinja2Templates

from app import audit, auth, config, db, metrics, patients, util
from app.auth import ADMIN, BILLING, CLINICAL, FRONT, STAFF

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
TEMPLATES.env.filters["inr"] = util.inr

LEAD_SOURCES = ["WhatsApp", "Phone call", "Website form", "Google", "Facebook ad", "Instagram ad", "Practo", "Walk-in", "Referral"]
LEAD_STATUSES = ["New", "Contacted", "Booked", "Converted", "Lost"]
APPT_STATUSES = ["Booked", "Confirmed", "Visited", "NoShow", "Cancelled"]
CLAIM_STAGES = [("PreAuthRequested", "Pre-auth requested"), ("PreAuthApproved", "Pre-auth approved"),
                ("FinalSent", "Final bill sent"), ("Settled", "Settled"), ("Denied", "Denied")]
TASK_KINDS = {"missed_call": "Missed calls", "complaint": "Complaints", "claim_stuck": "Stuck claims",
              "unbilled": "Unbilled services", "followup_call": "Follow-up calls"}
PAY_MODES = ["UPI", "Card", "Cash", "Insurance"]

NAV = [
    ("/", "Dashboard", ADMIN),
    ("/leads", "Enquiries", FRONT),
    ("/appointments", "Appointments", CLINICAL),
    ("/patients", "Patients", CLINICAL),
    ("/billing", "Billing", BILLING),
    ("/claims", "Claims", BILLING),
    ("/tasks", "Tasks", STAFF - {"doctor"}),
    ("/messages", "Messages", FRONT),
    ("/import", "Import", ADMIN),
    ("/settings", "Settings", ADMIN),
    ("/audit", "Audit log", ADMIN),
]
HOME = {"admin": "/", "frontdesk": "/leads", "billing": "/billing", "doctor": "/appointments"}


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
        return wrapped


router = APIRouter(route_class=UIRoute)


# ---------------------------------------------------------------- helpers

def _branches() -> list[dict]:
    return db.query("SELECT id, name FROM branches ORDER BY id")


def _hospital() -> str:
    return db.get_setting("hospital_name", "Your Hospital")


def render(request: Request, name: str, user: dict | None, status_code: int = 200, **ctx) -> HTMLResponse:
    nav = [(href, label) for href, label, roles in NAV if user and user["role"] in roles]
    base = {
        "user": user, "nav": nav, "path": request.url.path, "hospital": _hospital(),
        "branches": _branches(), "msg": request.query_params.get("msg"), "err": request.query_params.get("err"),
        "csrf": user["csrf"] if user else "",
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


# ---------------------------------------------------------------- login

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", None, next=request.query_params.get("next", ""))


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("")):
    u = auth.authenticate(username, password)
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
    audit.log(auth.actor(user), "logout", "user", user["id"])
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- dashboard

def _chart(rows: list[dict], branches: list[dict]) -> dict:
    W, H, pl, pr, pt, pb = 640, 260, 64, 10, 14, 30
    iw, ih = W - pl - pr, H - pt - pb
    peak = max([r[b["id"]] for r in rows for b in branches] + [0])
    step = _nice_step(peak / 4 if peak else 1000)
    top = step * max(1, -(-peak // step)) if peak else step * 4
    grid = []
    v = 0
    while v <= top:
        y = pt + ih - (v / top) * ih
        grid.append({"y": round(y, 1), "label": util.inr(v)})
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
    if user and user["role"] != "admin":
        return RedirectResponse(HOME[user["role"]], status_code=303)
    user = auth.require(request, ADMIN)
    br = _scope(user, branch)
    today = util.now().date()
    yday = today - timedelta(days=1)
    k_today, k_yday = metrics.kpis(today, br), metrics.kpis(yday, br)
    shown = [b for b in _branches() if not br or b["id"] == br]
    chart = _chart(metrics.collections_by_day(today, 7), shown)
    fun = metrics.funnel(today.replace(day=1), today, br)
    steps = [("Enquiries", fun["enquiries"]), ("Booked", fun["booked"]), ("Visited", fun["visited"]), ("Paid", fun["paid"])]
    report = db.one("SELECT body, created_at, status FROM messages WHERE template='owner_daily_report' ORDER BY id DESC LIMIT 1")
    return render(request, "dashboard.html", user, branch=br, today=today, yday=yday, k_today=k_today, k_yday=k_yday,
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
    lead = db.one("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if lead is None:
        return back("/leads", err="That enquiry no longer exists.")
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
    a = db.one("SELECT * FROM appointments WHERE id = ?", (appt_id,))
    if a is None:
        return back("/appointments", err="That appointment no longer exists.")
    if status not in APPT_STATUSES:
        return back("/appointments", err="Unknown status.")
    if user["branch_id"] and a["branch_id"] != user["branch_id"]:
        raise auth.Forbidden()
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
    appts = db.query("SELECT a.*, d.name AS doctor, b.name AS branch_name FROM appointments a JOIN doctors d ON d.id=a.doctor_id"
                     " JOIN branches b ON b.id=a.branch_id WHERE a.patient_id = ? ORDER BY a.starts_at DESC", (patient_id,))
    bills = db.query("SELECT bl.*, b.name AS branch_name FROM bills bl JOIN branches b ON b.id=bl.branch_id"
                     " WHERE bl.patient_id = ? ORDER BY bl.created_at DESC", (patient_id,))
    msgs = db.query("SELECT * FROM messages WHERE patient_id = ? ORDER BY id DESC LIMIT 50", (patient_id,))
    fb = db.query("SELECT * FROM feedback WHERE patient_id = ? ORDER BY created_at DESC", (patient_id,))
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
    user = auth.require(request, BILLING)
    from app import billing
    br = _scope(user, branch)
    dues = billing.dues(branch=br)
    f, p = _branch_sql("o.branch_id", br)
    unbilled = db.query(
        "SELECT o.*, pt.name, pt.uid, b.name AS branch_name FROM orders o JOIN patients pt ON pt.id=o.patient_id"
        f" JOIN branches b ON b.id=o.branch_id WHERE o.bill_id IS NULL{f} ORDER BY o.created_at", p)
    return render(request, "billing.html", user, dues=dues, unbilled=unbilled, f_branch=br or "", modes=PAY_MODES,
                  total_due=sum(d["balance"] for d in dues), total_unbilled=sum(o["amount"] for o in unbilled))


@router.post("/billing/{bill_id}/remind")
async def billing_remind(request: Request, bill_id: int):
    user = await auth.require_post(request, BILLING)
    from app import automations, messaging
    try:
        automations.send_dues_reminder(bill_id, util.now())
    except messaging.SendBlocked:
        return back("/billing", err="Not sent: this patient has not given consent for messages.")
    audit.log(auth.actor(user), "manual_reminder", "bill", bill_id)
    return back("/billing", msg="Payment reminder sent on WhatsApp.")


@router.post("/billing/{bill_id}/payment")
async def billing_payment(request: Request, bill_id: int, amount: int = Form(...), mode: str = Form(...)):
    user = await auth.require_post(request, BILLING)
    from app import billing
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
    try:
        bill_id = billing.add_order_to_bill(order_id, actor=auth.actor(user))
    except (ValueError, LookupError) as e:
        return back("/billing", err=str(e))
    no = db.scalar("SELECT bill_no FROM bills WHERE id = ?", (bill_id,))
    return back("/billing", msg=f"Added to bill {no}.")


# ---------------------------------------------------------------- claims

@router.get("/claims", response_class=HTMLResponse)
def claims_page(request: Request, branch: str = ""):
    user = auth.require(request, BILLING)
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
    return render(request, "claims.html", user, cols=cols, stages=CLAIM_STAGES, f_branch=br or "")


@router.post("/claims/{claim_id}/stage")
async def claim_stage(request: Request, claim_id: int, stage: str = Form(...)):
    user = await auth.require_post(request, BILLING)
    from app import billing
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
    user = auth.require(request, STAFF - {"doctor"})
    br = _scope(user, branch)
    f, p = _branch_sql("t.branch_id", br)
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
    user = await auth.require_post(request, STAFF - {"doctor"})
    t = db.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if t is None:
        return back("/tasks", err="That task no longer exists.")
    db.execute("UPDATE tasks SET status='Done' WHERE id = ?", (task_id,))
    audit.log(auth.actor(user), "done", "task", task_id, {"kind": t["kind"]})
    return back("/tasks", msg="Task marked done.")


# ---------------------------------------------------------------- messages

@router.get("/messages", response_class=HTMLResponse)
def messages_page(request: Request, phone: str = ""):
    user = auth.require(request, FRONT)
    digits = "".join(c for c in phone if c.isdigit())
    sql = "SELECT m.*, p.name, p.uid FROM messages m LEFT JOIN patients p ON p.id=m.patient_id"
    params: tuple = ()
    if digits:
        sql += " WHERE m.to_phone LIKE ?"
        params = (f"%{digits}%",)
    rows = db.query(sql + " ORDER BY m.id DESC LIMIT 200", params)
    return render(request, "messages.html", user, rows=rows, phone=phone,
                  simulator=config.settings.whatsapp_mode == "simulator")


# ---------------------------------------------------------------- settings

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = auth.require(request, ADMIN)
    users = db.query("SELECT u.*, b.name AS branch_name FROM users u LEFT JOIN branches b ON b.id=u.branch_id ORDER BY u.username")
    return render(request, "settings.html", user, users=users, roles=auth.ROLES, mode=config.settings.whatsapp_mode,
                  run=request.query_params.get("run"))


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
    summary = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in counts.items())
    return back("/settings", msg=f"Automations ran. {summary}")


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


# ---------------------------------------------------------------- import

@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    user = auth.require(request, ADMIN)
    return render(request, "import.html", user, result=None)


@router.post("/import", response_class=HTMLResponse)
async def import_run(request: Request, kind: str = Form(...), file: UploadFile = File(...)):
    user = await auth.require_post(request, ADMIN)
    from app.integrations import csv_import
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return render(request, "import.html", user, result=None,
                      import_error="The file is not UTF-8 text. Save it from Excel as 'CSV UTF-8' and upload again.")
    if kind == "patients":
        result = csv_import.import_patients(text, auth.actor(user))
    elif kind == "bills":
        result = csv_import.import_bills(text, auth.actor(user))
    else:
        return render(request, "import.html", user, result=None, import_error="Choose what the file contains.")
    return render(request, "import.html", user, result=result, kind=kind, filename=file.filename)


# ---------------------------------------------------------------- audit

@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    user = auth.require(request, ADMIN)
    rows = db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")
    return render(request, "audit.html", user, rows=rows)
