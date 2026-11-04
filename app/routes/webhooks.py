"""Incoming events: WhatsApp (Meta Cloud API), the demo simulator, and missed calls from telephony."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app import audit, config, db, messaging, patients, util
from app.ai import client as ai_client
from app.ai import receptionist

router = APIRouter()


# ---------- core handler ----------

def _reply(phone: str, template: str, body: str, patient_id: int | None) -> int:
    # The patient started this conversation, so replying does not need marketing consent.
    return messaging.send(phone, template, body, patient_id=patient_id, require_consent=False)


def _appt_text(appt_id: int) -> str:
    a = db.one("SELECT a.starts_at, d.name AS doctor, b.name AS branch FROM appointments a"
               " JOIN doctors d ON d.id = a.doctor_id JOIN branches b ON b.id = a.branch_id WHERE a.id = ?", (appt_id,))
    if a is None:
        raise LookupError(f"Appointment {appt_id} not found")
    when = util.parse(a["starts_at"]).strftime("%a %d %b, %I:%M %p")
    return f"{a['doctor']} on {when} at {a['branch']} (OPD-{appt_id})"


def _task(kind: str, title: str, branch_id, related_type: str, related_id: int, due: datetime, now: datetime) -> None:
    db.execute("INSERT OR IGNORE INTO tasks(kind, title, branch_id, related_type, related_id, status, due_at, created_at)"
               " VALUES (?,?,?,?,?,'Open',?,?)", (kind, title, branch_id, related_type, related_id, util.ts(due), util.ts(now)))


def handle_inbound(phone: str, text: str, now: datetime) -> dict:
    """Process one incoming WhatsApp message. Returns what was done (for logs and the simulator)."""
    phone = util.normalize_phone(phone)
    text = (text or "").strip()
    hosp = db.get_setting("hospital_name", "Your Hospital")
    p = db.one("SELECT * FROM patients WHERE phone = ?", (phone,))
    inbound_id = messaging.record_inbound(phone, text, p["id"] if p else None)

    if text.upper() == "STOP":
        if p:
            patients.set_consent(p["id"], False, actor="webhook")
        return {"action": "consent_withdrawn", "patient_id": p["id"] if p else None}

    if p is None:
        lead = db.one("SELECT * FROM leads WHERE phone = ? AND status IN ('New','Contacted') ORDER BY id DESC LIMIT 1", (phone,))
        if lead:
            if ai_client.enabled():
                return {**receptionist.respond(phone, text, now, inbound_id=inbound_id), "lead_id": lead["id"]}
            _reply(phone, "ack_reply", f"Thank you. Our {hosp} team has your message and will reply shortly.", None)
            return {"action": "lead_existing", "lead_id": lead["id"]}
        ts = util.ts(now)
        lead_id = db.execute(
            "INSERT INTO leads(name, phone, need, source, status, first_reply_seconds, created_at, updated_at)"
            " VALUES (?,?,?,?,'New',0,?,?)", ("WhatsApp enquiry", phone, text[:500], "WhatsApp", ts, ts))
        audit.log("webhook", "create", "lead", lead_id, {"source": "WhatsApp"})
        if ai_client.enabled():
            return {**receptionist.respond(phone, text, now, inbound_id=inbound_id), "lead_id": lead_id}
        branches = ", ".join(b["name"] for b in db.query("SELECT name FROM branches ORDER BY id"))
        _reply(phone, "welcome_reply",
               f"Hello! Thank you for contacting {hosp}.\nWe have branches at: {branches}.\n"
               "Please tell us your name, which branch suits you, and the doctor or problem you need help with.", None)
        return {"action": "lead_created", "lead_id": lead_id}

    last = db.one("SELECT * FROM messages WHERE to_phone = ? AND direction = 'out' AND status IN ('simulated','sent')"
                  " ORDER BY id DESC LIMIT 1", (phone,))
    tmpl = last["template"] if last else ""

    if tmpl == "feedback_request" and text in {"1", "2", "3", "4", "5"}:
        score = int(text)
        appt_id = last["related_id"] if last["related_type"] == "appointment" else None
        escalated = 1 if score <= 3 else 0
        fid = db.execute("INSERT INTO feedback(patient_id, appointment_id, score, escalated, created_at) VALUES (?,?,?,?,?)",
                         (p["id"], appt_id, score, escalated, util.ts(now)))
        audit.log("webhook", "create", "feedback", fid, {"score": score})
        if escalated:
            branch = db.scalar("SELECT branch_id FROM appointments WHERE id = ?", (appt_id,)) if appt_id else None
            _task("complaint", f"Low feedback score {score}/5 from {p['name']}", branch, "feedback", fid, now + timedelta(hours=24), now)
            _reply(phone, "feedback_ack_low", "We are sorry your visit was not good. Our branch manager will call you today.", p["id"])
            return {"action": "feedback_low", "feedback_id": fid, "score": score}
        _reply(phone, "feedback_review_link",
               f"Thank you! Would you share your experience on Google? It helps other patients: {config.settings.review_link}", p["id"])
        return {"action": "feedback_high", "feedback_id": fid, "score": score}

    if tmpl.startswith("appt_reminder_") and last["related_type"] == "appointment" and text in {"1", "2", "3"}:
        appt_id = last["related_id"]
        branch = db.scalar("SELECT branch_id FROM appointments WHERE id = ?", (appt_id,))
        if text == "1":
            db.execute("UPDATE appointments SET status = 'Confirmed' WHERE id = ?", (appt_id,))
            audit.log("webhook", "appointment_confirmed", "appointment", appt_id)
            _reply(phone, "appt_confirmed", f"Thank you, your appointment is confirmed: {_appt_text(appt_id)}.", p["id"])
            return {"action": "appointment_confirmed", "appointment_id": appt_id}
        if text == "2":
            _task("followup_call", f"{p['name']} wants to reschedule OPD-{appt_id}", branch, "appointment", appt_id, now + timedelta(minutes=30), now)
            _reply(phone, "appt_reschedule_ack", "No problem. Our team will call you shortly to choose a new time.", p["id"])
            return {"action": "reschedule_requested", "appointment_id": appt_id}
        db.execute("UPDATE appointments SET status = 'Cancelled' WHERE id = ?", (appt_id,))
        audit.log("webhook", "appointment_cancelled", "appointment", appt_id)
        _reply(phone, "appt_cancelled", f"Your appointment {_appt_text(appt_id)} is cancelled. Message us any time to book again.", p["id"])
        return {"action": "appointment_cancelled", "appointment_id": appt_id}

    if ai_client.enabled():
        return receptionist.respond(phone, text, now, inbound_id=inbound_id)
    _task("followup_call", f"Reply to WhatsApp from {p['name']}: {text[:80]}", None, "message", inbound_id, now + timedelta(minutes=30), now)
    _reply(phone, "ack_reply", f"Thank you, {p['name']}. Our {hosp} team will reply to you shortly.", p["id"])
    return {"action": "staff_followup", "message_id": inbound_id}


# ---------- Meta WhatsApp webhook ----------

@router.get("/whatsapp")
def verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == config.settings.whatsapp_verify_token:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "Verification token does not match TT_WHATSAPP_VERIFY_TOKEN")


def _extract_text(m: dict) -> str | None:
    t = m.get("type")
    if t == "text":
        return m["text"]["body"]
    if t == "interactive":
        i = m["interactive"]
        return (i.get("button_reply") or i.get("list_reply") or {}).get("title")
    if t == "button":
        return m["button"]["text"]
    return None


@router.post("/whatsapp")
async def receive(request: Request):
    raw = await request.body()
    secret = config.settings.whatsapp_app_secret
    if secret:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(401, "Invalid X-Hub-Signature-256")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Body is not valid JSON")
    results = []
    now = util.now()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []):
                if not _first_delivery(m.get("id"), now):
                    results.append({"from": m.get("from"), "action": "duplicate_ignored", "id": m.get("id")})
                    continue
                text = _extract_text(m)
                if text is None:
                    audit.log("webhook", "inbound_unsupported", "message", None, {"from": m.get("from"), "type": m.get("type")})
                    results.append({"from": m.get("from"), "action": "unsupported_type", "type": m.get("type")})
                    continue
                try:
                    results.append(handle_inbound(m["from"], text, now))
                except ValueError as e:
                    audit.log("webhook", "inbound_rejected", "message", None, {"from": m.get("from"), "error": str(e)})
                    results.append({"from": m.get("from"), "action": "rejected", "error": str(e)})
    return {"processed": results}


def _first_delivery(message_id: str | None, now: datetime) -> bool:
    """True the first time Meta delivers this message id; retries return False."""
    if not message_id:
        return True
    with db.connect() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO processed_webhooks(message_id, received_at) VALUES (?, ?)",
                           (message_id, util.ts(now)))
        return cur.rowcount == 1


# ---------- demo simulator ----------

@router.post("/simulate-inbound")
async def simulate_inbound(request: Request):
    if config.settings.whatsapp_mode != "simulator":
        raise HTTPException(404, "The simulator is only available in simulator mode")
    is_json = request.headers.get("content-type", "").startswith("application/json")
    data = await request.json() if is_json else dict(await request.form())
    phone, text = data.get("phone"), data.get("text")
    if not phone or not text:
        raise HTTPException(400, "Both 'phone' and 'text' are required")
    try:
        result = handle_inbound(str(phone), str(text), util.now())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if is_json:
        return JSONResponse(result)
    return RedirectResponse("/messages", status_code=303)


# ---------- missed calls (telephony provider webhook) ----------

@router.post("/missed-call")
async def missed_call(request: Request):
    key = config.settings.api_key
    if not key:
        raise HTTPException(503, "Set TT_API_KEY to accept missed-call events")
    if not hmac.compare_digest(request.headers.get("X-API-Key", ""), key):
        raise HTTPException(401, "Missing or wrong X-API-Key")
    data = await request.json()
    try:
        phone = util.normalize_phone(str(data.get("phone", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    branch_id = data.get("branch_id")
    if branch_id is not None and db.one("SELECT id FROM branches WHERE id = ?", (branch_id,)) is None:
        raise HTTPException(400, f"Unknown branch_id {branch_id!r}")
    now = util.now()
    p = db.one("SELECT id, name FROM patients WHERE phone = ?", (phone,))
    name = p["name"] if p else "Unknown caller"
    ts = util.ts(now)
    lead_id = db.execute(
        "INSERT INTO leads(name, phone, need, source, branch_id, status, patient_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?,'New',?,?,?)", (name, phone, "Missed call", "Phone call", branch_id, p["id"] if p else None, ts, ts))
    _task("missed_call", f"Return missed call: {name} (+{phone})", branch_id, "lead", lead_id, now + timedelta(minutes=15), now)
    task_id = db.scalar("SELECT id FROM tasks WHERE kind = 'missed_call' AND related_type = 'lead' AND related_id = ?", (lead_id,))
    audit.log("webhook", "missed_call", "lead", lead_id, {"phone": phone, "branch_id": branch_id})
    return {"lead_id": lead_id, "task_id": task_id}
