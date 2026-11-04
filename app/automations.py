"""Automation rules. Every function takes `now` (naive IST) and is idempotent:
running it twice never sends the same message twice.

A patient without consent raises messaging.SendBlocked; the attempt is already stored
as 'blocked_no_consent', so here it is counted and the item is marked as handled.
Any other error propagates to the caller (the scheduler logs it to the audit log).
"""
from datetime import date, datetime, timedelta

from app import audit, config, db, messaging, metrics, util, wa_templates
from app.ai import insights

DUES_STAGES = {1: 3, 2: 10, 3: 21}  # stage -> minimum bill age in days


def _hospital() -> str:
    return db.get_setting("hospital_name", "Your Hospital")


def _branch_name(branch_id: str | None) -> str:
    if branch_id is None:
        return ""
    r = db.one("SELECT name FROM branches WHERE id = ?", (branch_id,))
    if r is None:
        raise LookupError(f"Branch {branch_id!r} not found")
    return r["name"]


def _when(starts_at: str) -> str:
    dt = util.parse(starts_at)
    return dt.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")


def _task(kind: str, title: str, branch_id: str | None, related_type: str, related_id: int, due_at: datetime | None, now: datetime) -> bool:
    """Create an Open task once per (kind, related item). Returns True if newly created."""
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO tasks(kind, title, branch_id, related_type, related_id, status, due_at, created_at)"
            " VALUES (?,?,?,?,?,'Open',?,?)",
            (kind, title, branch_id, related_type, related_id, util.ts(due_at) if due_at else None, util.ts(now)),
        )
        return cur.rowcount == 1


# ---------- appointments ----------

def _appt_rows(where: str, params: tuple) -> list[dict]:
    return db.query(
        "SELECT a.*, p.name AS patient_name, p.phone, d.name AS doctor_name, d.specialty"
        " FROM appointments a JOIN patients p ON p.id = a.patient_id JOIN doctors d ON d.id = a.doctor_id"
        f" WHERE {where} ORDER BY a.starts_at", params)


def appointment_reminders(now: datetime) -> dict:
    out = {"reminder_24h": 0, "reminder_2h": 0, "blocked": 0}
    n, in2h, in24h = util.ts(now), util.ts(now + timedelta(hours=2)), util.ts(now + timedelta(hours=24))
    hosp = _hospital()

    for a in _appt_rows("a.status IN ('Booked','Confirmed') AND a.reminder_24h_sent_at IS NULL"
                        " AND a.starts_at > ? AND a.starts_at <= ?", (in2h, in24h)):
        body = (f"Reminder from {hosp}: {a['patient_name']}, you have an appointment with {a['doctor_name']}"
                f" on {_when(a['starts_at'])} at {_branch_name(a['branch_id'])}.\n"
                f"Booking ID: OPD-{a['id']}\n"
                "Reply 1 to confirm, 2 to reschedule, 3 to cancel.")
        tpl = wa_templates.params("tt_appt_reminder", [a["patient_name"], hosp, a["doctor_name"], _when(a["starts_at"]),
                                                        _branch_name(a["branch_id"]), f"OPD-{a['id']}"])
        out[_send_appt(a, "appt_reminder_24h", body, "reminder_24h_sent_at", now, tpl)] += 1

    for a in _appt_rows("a.status IN ('Booked','Confirmed') AND a.reminder_2h_sent_at IS NULL"
                        " AND a.starts_at > ? AND a.starts_at <= ?", (n, in2h)):
        body = (f"{a['patient_name']}, see you at {_when(a['starts_at'])} with {a['doctor_name']}"
                f" at {hosp}, {_branch_name(a['branch_id'])}. Booking ID: OPD-{a['id']}.\n"
                "Reply 1 to confirm, 2 to reschedule, 3 to cancel.")
        tpl = wa_templates.params("tt_appt_reminder", [a["patient_name"], hosp, a["doctor_name"], _when(a["starts_at"]),
                                                        _branch_name(a["branch_id"]), f"OPD-{a['id']}"])
        out[_send_appt(a, "appt_reminder_2h", body, "reminder_2h_sent_at", now, tpl)] += 1
    return out


def _send_appt(a: dict, template: str, body: str, column: str, now: datetime, tpl: tuple) -> str:
    key = "reminder_24h" if template.endswith("24h") else "reminder_2h"
    try:
        messaging.send(a["phone"], template, body, patient_id=a["patient_id"], related_type="appointment",
                       related_id=a["id"], wa_template=tpl)
    except messaging.SendBlocked:
        key = "blocked"
    db.execute(f"UPDATE appointments SET {column} = ? WHERE id = ?", (util.ts(now), a["id"]))
    return key


def feedback_requests(now: datetime) -> dict:
    out = {"sent": 0, "blocked": 0}
    rows = _appt_rows("a.status = 'Visited' AND a.feedback_sent_at IS NULL AND a.starts_at >= ? AND a.starts_at <= ?",
                      (util.ts(now - timedelta(hours=48)), util.ts(now - timedelta(hours=2))))
    for a in rows:
        body = (f"Thank you for visiting {_hospital()}, {a['patient_name']}. "
                f"How was your visit with {a['doctor_name']}? Please reply with a number from 1 (poor) to 5 (excellent).")
        try:
            messaging.send(a["phone"], "feedback_request", body, patient_id=a["patient_id"], related_type="appointment",
                           related_id=a["id"],
                           wa_template=wa_templates.params("tt_feedback_request", [_hospital(), a["patient_name"], a["doctor_name"]]))
            out["sent"] += 1
        except messaging.SendBlocked:
            out["blocked"] += 1
        db.execute("UPDATE appointments SET feedback_sent_at = ? WHERE id = ?", (util.ts(now), a["id"]))
    return out


# ---------- dues ----------

def _last_stage(bill_id: int) -> int:
    return db.scalar("SELECT COALESCE(MAX(stage), 0) FROM dues_reminders WHERE bill_id = ?", (bill_id,))


def send_dues_reminder(bill_id: int, now: datetime) -> int:
    """Send the next dues reminder for one bill now. Returns the message id.

    Raises ValueError if the bill has no balance, LookupError if it does not exist,
    messaging.SendBlocked if the patient has not consented (the stage is still recorded).
    """
    b = db.one("SELECT b.*, p.name AS patient_name, p.phone FROM bills b JOIN patients p ON p.id = b.patient_id WHERE b.id = ?", (bill_id,))
    if b is None:
        raise LookupError(f"Bill {bill_id} not found")
    balance = b["total"] - b["paid"]
    if balance <= 0:
        raise ValueError(f"Bill {b['bill_no']} has no balance due")
    # Only the amount and a secure link: itemised services would show health details on the lock screen.
    link = f"{config.settings.payment_link_base}/{b['bill_no']}"
    body = "\n".join([
        f"Dear {b['patient_name']}, this is a reminder from {_hospital()}, {_branch_name(b['branch_id'])}.",
        f"Bill {b['bill_no']} has a balance due of {util.inr(balance)}.",
        f"Pay securely by UPI or card: {link}",
        "Please ignore this message if you have already paid.",
    ])
    stage = _last_stage(bill_id) + 1
    try:
        tpl = wa_templates.params("tt_dues_reminder", [b["patient_name"], b["bill_no"], f"{_hospital()}, {_branch_name(b['branch_id'])}",
                                                        util.inr(balance), link])
        mid = messaging.send(b["phone"], "dues_reminder", body, patient_id=b["patient_id"], related_type="bill",
                             related_id=bill_id, wa_template=tpl)
    except messaging.SendBlocked:
        db.execute("INSERT INTO dues_reminders(bill_id, stage, sent_at) VALUES (?,?,?)", (bill_id, stage, util.ts(now)))
        raise
    db.execute("INSERT INTO dues_reminders(bill_id, stage, sent_at) VALUES (?,?,?)", (bill_id, stage, util.ts(now)))
    return mid


def dues_reminders(now: datetime) -> dict:
    out = {"sent": 0, "blocked": 0, "call_tasks": 0}
    for b in db.query("SELECT id, bill_no, branch_id, created_at FROM bills WHERE total > paid ORDER BY id"):
        age = (now - util.parse(b["created_at"])).days
        nxt = _last_stage(b["id"]) + 1
        if nxt not in DUES_STAGES or age < DUES_STAGES[nxt]:
            continue
        try:
            send_dues_reminder(b["id"], now)
            out["sent"] += 1
        except messaging.SendBlocked:
            out["blocked"] += 1
        if nxt == 3 and _task("followup_call", f"Call about pending dues on bill {b['bill_no']}", b["branch_id"],
                              "bill", b["id"], now + timedelta(days=1), now):
            out["call_tasks"] += 1
    return out


# ---------- follow-ups ----------

def followup_reminders(now: datetime) -> dict:
    out = {"sent": 0, "blocked": 0}
    today = now.date()
    rows = db.query(
        "SELECT f.*, p.name AS patient_name, p.phone FROM followups f JOIN patients p ON p.id = f.patient_id"
        " WHERE f.status = 'Due' AND f.reminded_at IS NULL AND f.due_date >= ? AND f.due_date <= ?",
        (today.isoformat(), (today + timedelta(days=3)).isoformat()))
    for f in rows:
        due = date.fromisoformat(f["due_date"]).strftime("%d %b").lstrip("0")
        body = (f"Dear {f['patient_name']}, your follow-up visit at {_hospital()}, {_branch_name(f['branch_id'])} is due on {due}. "
                "Reply here and we will book a convenient time for you.")
        try:
            messaging.send(f["phone"], "followup_reminder", body, patient_id=f["patient_id"], related_type="followup",
                           related_id=f["id"],
                           wa_template=wa_templates.params("tt_followup_reminder", [f["patient_name"], "follow-up visit",
                                                           f"{_hospital()}, {_branch_name(f['branch_id'])}", due]))
            db.execute("UPDATE followups SET status = 'Reminded', reminded_at = ? WHERE id = ?", (util.ts(now), f["id"]))
            out["sent"] += 1
        except messaging.SendBlocked:
            db.execute("UPDATE followups SET reminded_at = ? WHERE id = ?", (util.ts(now), f["id"]))
            out["blocked"] += 1
    return out


# ---------- detection ----------

def detect_unbilled(now: datetime) -> dict:
    created = 0
    rows = db.query(
        "SELECT o.*, p.name AS patient_name FROM orders o JOIN patients p ON p.id = o.patient_id"
        " WHERE o.bill_id IS NULL AND o.created_at < ?", (util.ts(now - timedelta(hours=2)),))
    for o in rows:
        title = f"Not billed: {o['dept']} - {o['description']} for {o['patient_name']} ({util.inr(o['amount'])})"
        created += _task("unbilled", title, o["branch_id"], "order", o["id"], now + timedelta(hours=4), now)
    return {"tasks_created": created}


def detect_stuck_claims(now: datetime) -> dict:
    created = 0
    rows = db.query(
        "SELECT c.*, p.name AS patient_name FROM claims c JOIN patients p ON p.id = c.patient_id"
        " WHERE (c.stage = 'PreAuthRequested' AND c.stage_changed_at < ?) OR (c.stage = 'FinalSent' AND c.stage_changed_at < ?)",
        (util.ts(now - timedelta(minutes=60)), util.ts(now - timedelta(minutes=180))))
    for c in rows:
        limit = "1-hour pre-authorisation" if c["stage"] == "PreAuthRequested" else "3-hour discharge approval"
        title = f"Claim past {limit} limit: {c['patient_name']}, {c['insurer']}, {util.inr(c['amount'])}"
        created += _task("claim_stuck", title, c["branch_id"], "claim", c["id"], now, now)
    return {"tasks_created": created}


# ---------- owner report ----------

def owner_report_text(now: datetime) -> str:
    y = now.date() - timedelta(days=1)
    lines = [f"Good morning! {_hospital()} report for {y.strftime('%a %d %b %Y')}", ""]
    scopes = [(None, "All branches")] + [(b["id"], b["name"]) for b in db.query("SELECT id, name FROM branches ORDER BY id")]
    for bid, name in scopes:
        k = metrics.kpis(y, bid)
        lines += [f"{name}:",
                  f"  OPD patients {k['opd']} (booked {k['booked']}), no-show {k['no_show_pct']}% (30 days)",
                  f"  Billed {util.inr(k['billed'])}, collected {util.inr(k['collected'])}",
                  f"  Outstanding dues {util.inr(k['dues'])}", ""]
    a = metrics.attention()
    lines += ["Needs attention:",
              f"  Insurance claims past time limit: {a['claims_stuck']}",
              f"  Services not yet billed: {util.inr(a['unbilled_amount'])}",
              f"  Missed calls not returned: {a['missed_calls_open']}",
              f"  Open complaints: {a['complaints_open']}"]
    insight = insights.owner_insight(now)  # None when AI is off
    if insight:
        lines += ["", insight]
    return "\n".join(lines)


def daily_owner_report(now: datetime) -> int | None:
    today = now.date().isoformat()
    if now.hour < 9 or db.get_setting("last_owner_report_date", "") == today:
        return None
    if not config.settings.owner_phone:
        audit.log("automation", "owner_report_skipped", "settings", None, "Set TT_OWNER_PHONE to receive the 9 am report")
        db.set_setting("last_owner_report_date", today)
        return None
    y = now.date() - timedelta(days=1)
    k, a = metrics.kpis(y), metrics.attention()
    attention = (f"{a['claims_stuck']} claims past limit, {util.inr(a['unbilled_amount'])} not billed, "
                 f"{a['missed_calls_open']} missed calls, {a['complaints_open']} complaints")
    tpl = wa_templates.params("tt_owner_daily_report", [_hospital(), y.strftime("%d %b %Y"), k["opd"], util.inr(k["billed"]),
                                                         util.inr(k["collected"]), util.inr(k["dues"]), attention])
    mid = messaging.send(config.settings.owner_phone, "owner_daily_report", owner_report_text(now),
                         patient_id=None, require_consent=False, wa_template=tpl)
    db.set_setting("last_owner_report_date", today)
    return mid


AUTOMATIONS = {
    "appointment_reminders": appointment_reminders,
    "feedback_requests": feedback_requests,
    "dues_reminders": dues_reminders,
    "followup_reminders": followup_reminders,
    "detect_unbilled": detect_unbilled,
    "detect_stuck_claims": detect_stuck_claims,
    "daily_owner_report": daily_owner_report,
}


def is_enabled(name: str) -> bool:
    """Each automation can be switched off on its own (settings key automation_<name> = 'off'),
    so a pilot can start with one automation at one branch."""
    if name not in AUTOMATIONS:
        raise KeyError(f"Unknown automation {name!r}")
    return db.get_setting(f"automation_{name}", "on") == "on"


def set_enabled(name: str, on: bool) -> None:
    if name not in AUTOMATIONS:
        raise KeyError(f"Unknown automation {name!r}")
    db.set_setting(f"automation_{name}", "on" if on else "off")


# Messages to patients go out only between 8 am and 9 pm IST.
PATIENT_MESSAGING = {"appointment_reminders", "feedback_requests", "dues_reminders", "followup_reminders"}
QUIET_START, QUIET_END = 21, 8


def in_quiet_hours(now: datetime) -> bool:
    return now.hour >= QUIET_START or now.hour < QUIET_END


def run_all(now: datetime) -> dict:
    out = {}
    for name, fn in AUTOMATIONS.items():
        if not is_enabled(name):
            out[name] = "off"
        elif name in PATIENT_MESSAGING and in_quiet_hours(now):
            out[name] = "quiet hours (9 pm to 8 am)"
        else:
            out[name] = fn(now)
    return out
