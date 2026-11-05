"""AI WhatsApp receptionist.

The model only understands and drafts; this code decides and acts. Every booking is validated
against real free slots, every reply passes deterministic safety checks, and every failure
becomes a staff task instead of a silent fallback.
"""
import json
import re
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from app import audit, db, messaging, patients, util
from app.ai import client as ai
from app.ai import prompts

SLOT_FMT = "%Y-%m-%d %H:%M"
SLOT_TIMES = [f"{h:02d}:{m:02d}" for h in list(range(9, 13)) + list(range(16, 19)) for m in (0, 30)]
EXCLUDED_TEMPLATES = ("patient_otp", "owner_daily_report")   # never shown to the model
MAX_REPLY_CHARS = 1000

Intent = Literal["book_appointment", "reschedule", "cancel", "ask_info", "billing_question",
                 "report_question", "feedback", "emergency", "complaint", "other"]


class ReceptionistOutput(BaseModel):
    intent: Intent
    language: str = Field(description="en, hi, ta, te, kn, ml, mr, bn, gu, or hi-Latn for Hinglish")
    reply: str
    branch_id: str | None
    doctor_id: int | None
    slot: str | None = Field(description="Exactly one free slot from hospital_context, 'YYYY-MM-DD HH:MM', or null")
    patient_name: str | None = Field(description="Name the patient gave for a new booking, else null")
    patient_confirmed: bool
    needs_human: bool
    urgency: Literal["normal", "urgent", "emergency"]


# Deterministic guard: dosage-like text means the reply strayed into medical advice.
_MEDICAL = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|ml|g)\b|\b(tablets?|capsules?|syrup|dose|dosage)\b|times a day|twice a day",
                      re.IGNORECASE)
SAFE_MEDICAL_REPLY = ("I'm sorry, I can't give medical advice on WhatsApp. A doctor can help you properly. "
                      "Shall I book an appointment for you?")
EMERGENCY_LINE = "If this is an emergency, please call 108 or come to our Emergency department now."


# ---------- context ----------

def free_slots(now: datetime, days: int = 7) -> dict[int, list[str]]:
    """Free 30-minute slots per doctor for the next `days` days, at least 1 hour from now."""
    end = now + timedelta(days=days)
    taken = {(r["doctor_id"], r["starts_at"][:16]) for r in db.query(
        "SELECT doctor_id, starts_at FROM appointments WHERE status IN ('Booked','Confirmed') AND starts_at BETWEEN ? AND ?",
        (util.ts(now), util.ts(end)))}
    earliest = now + timedelta(hours=1)
    out: dict[int, list[str]] = {}
    for d in db.query("SELECT id FROM doctors ORDER BY id"):
        slots = []
        for i in range(days + 1):
            day = (now + timedelta(days=i)).date()
            for t in SLOT_TIMES:
                s = f"{day.isoformat()} {t}"
                if datetime.strptime(s, SLOT_FMT) >= earliest and (d["id"], s) not in taken:
                    slots.append(s)
        out[d["id"]] = slots
    return out


def build_context(phone: str, now: datetime) -> dict:
    phone = util.normalize_phone(phone)
    doctors = db.query("SELECT d.id, d.name, d.specialty, d.branch_id, b.name AS branch, d.fee FROM doctors d"
                       " JOIN branches b ON b.id = d.branch_id ORDER BY d.id")
    slots = free_slots(now)
    p = db.one("SELECT * FROM patients WHERE phone = ?", (phone,))
    record = {}
    if p:
        nxt = db.one("SELECT a.id, a.starts_at, d.name AS doctor, b.name AS branch FROM appointments a"
                     " JOIN doctors d ON d.id = a.doctor_id JOIN branches b ON b.id = a.branch_id"
                     " WHERE a.patient_id = ? AND a.status IN ('Booked','Confirmed') AND a.starts_at >= ?"
                     " ORDER BY a.starts_at LIMIT 1", (p["id"], util.ts(now)))
        balance = db.scalar("SELECT COALESCE(SUM(total - paid), 0) FROM bills WHERE patient_id = ? AND total > paid", (p["id"],))
        record = {
            "first_name": p["name"].split()[0],
            "patient_id": p["uid"],
            "upcoming_appointment": (f"OPD-{nxt['id']} with {nxt['doctor']} on {nxt['starts_at'][:16]} at {nxt['branch']}"
                                     if nxt else None),
            "open_balance": util.inr(balance) if balance else "none",
        }
    marks = ",".join("?" * len(EXCLUDED_TEMPLATES))
    history = db.query(
        f"SELECT direction, body, created_at FROM messages WHERE to_phone = ? AND template NOT IN ({marks})"
        " AND status IN ('simulated','sent','received') ORDER BY id DESC LIMIT 11", (phone, *EXCLUDED_TEMPLATES))
    history = list(reversed(history))
    return {
        "phone": phone,
        "now": now,
        "hospital": {
            "name": db.get_setting("hospital_name", "Your Hospital"),
            "today": now.strftime("%A %Y-%m-%d %H:%M"),
            "branches": [{"id": b["id"], "name": b["name"]} for b in db.query("SELECT id, name FROM branches ORDER BY id")],
            "doctors": [{**d, "free_slots": _compact(slots[d["id"]])} for d in doctors],
            "emergency": "Call 108 or come to the Emergency department, open 24 hours",
        },
        "doctors": {d["id"]: d for d in doctors},
        "slots": slots,
        "patient": p,
        "record": record,
        "history": history,
    }


def _compact(slots: list[str]) -> dict[str, list[str]]:
    by_day: dict[str, list[str]] = {}
    for s in slots:
        by_day.setdefault(s[:10], []).append(s[11:])
    return by_day


def render_user_turn(ctx: dict, text: str) -> str:
    hist = list(ctx["history"])
    if hist and hist[-1]["direction"] == "in" and hist[-1]["body"] == text:
        hist = hist[:-1]   # the webhook already stored the newest message; it goes in <patient_message>
    convo = "\n".join(f"[{m['created_at'][11:16]}] {'Patient' if m['direction'] == 'in' else 'Hospital'}: {m['body']}"
                      for m in hist[-10:])
    return (
        "<hospital_context>\n" + json.dumps(ctx["hospital"], ensure_ascii=False) + "\n</hospital_context>\n"
        "Slots are listed per doctor as {date: [times]}; a slot value is 'date time', e.g. '2026-11-05 09:30'.\n"
        "<patient_record>\n" + json.dumps(ctx["record"] or {"status": "new number, not yet a patient"}, ensure_ascii=False)
        + "\n</patient_record>\n"
        "<conversation>\n" + (convo or "(no earlier messages)") + "\n</conversation>\n"
        "<patient_message>\n" + text + "\n</patient_message>"
    )


def ask_model(ctx: dict, text: str, client=None) -> ReceptionistOutput:
    return ai.structured(system=prompts.RECEPTIONIST_V1, user=render_user_turn(ctx, text),
                         output=ReceptionistOutput, effort="low", max_tokens=2048, client=client)


# ---------- validation ----------

def validate(out: ReceptionistOutput, ctx: dict) -> dict:
    """Return the booking target if the model's doctor and slot are real and free, else reasons."""
    problems = []
    doc = ctx["doctors"].get(out.doctor_id) if out.doctor_id is not None else None
    if out.doctor_id is not None and doc is None:
        problems.append(f"unknown doctor_id {out.doctor_id}")
    if out.slot is not None and doc is not None and out.slot not in ctx["slots"][doc["id"]]:
        problems.append(f"slot {out.slot!r} is not free for doctor {doc['id']}")
    if out.branch_id is not None and doc is not None and out.branch_id != doc["branch_id"]:
        problems.append(f"branch {out.branch_id} does not match the doctor's branch {doc['branch_id']}")
    return {"doctor": doc, "ok": not problems and doc is not None and out.slot is not None, "problems": problems}


def safe_reply(out: ReceptionistOutput) -> tuple[str, list[str]]:
    reply, notes = out.reply.strip(), []
    if not reply:
        raise ai.AIError("Claude returned an empty reply")
    if _MEDICAL.search(reply):
        notes.append("medical_advice_blocked")
        reply = SAFE_MEDICAL_REPLY
    if (out.intent == "emergency" or out.urgency == "emergency") and "108" not in reply:
        notes.append("emergency_line_added")
        reply = reply + "\n\n" + EMERGENCY_LINE
    if len(reply) > MAX_REPLY_CHARS:
        notes.append("reply_trimmed")
        reply = reply[:MAX_REPLY_CHARS].rsplit(" ", 1)[0] + "…"
    return reply, notes


# ---------- actions ----------

def _task(kind, title, branch_id, related_type, related_id, due, now):
    db.execute("INSERT OR IGNORE INTO tasks(kind, title, branch_id, related_type, related_id, status, due_at, created_at)"
               " VALUES (?,?,?,?,?,'Open',?,?)", (kind, title, branch_id, related_type, related_id, util.ts(due), util.ts(now)))


def _book(ctx: dict, out: ReceptionistOutput, doc: dict, now: datetime) -> dict:
    p = ctx["patient"]
    if p is None:
        name = (out.patient_name or "").strip()
        if not name:
            return {"booked": False, "missing": "name"}
        p = patients.find_or_create(name, ctx["phone"], actor="ai")
    starts = datetime.strptime(out.slot, SLOT_FMT)
    if db.one("SELECT id FROM appointments WHERE doctor_id = ? AND starts_at = ? AND status IN ('Booked','Confirmed')",
              (doc["id"], util.ts(starts))):
        return {"booked": False, "missing": "slot_taken"}
    token = (db.scalar("SELECT COALESCE(MAX(token_no),0) FROM appointments WHERE branch_id = ? AND date(starts_at) = ?",
                       (doc["branch_id"], starts.date().isoformat())) or 0) + 1
    aid = db.execute(
        "INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, token_no, source, created_at)"
        " VALUES (?,?,?,?,'Booked',?,'WhatsApp AI',?)", (p["id"], doc["id"], doc["branch_id"], util.ts(starts), token, util.ts(now)))
    audit.log("ai", "create", "appointment", aid, {"patient": p["uid"], "token": token, "prompt": prompts.RECEPTIONIST_VERSION})
    lead = db.one("SELECT id FROM leads WHERE phone = ? AND status IN ('New','Contacted') ORDER BY id DESC LIMIT 1", (ctx["phone"],))
    if lead:
        db.execute("UPDATE leads SET status = 'Booked', patient_id = ?, branch_id = ?, updated_at = ? WHERE id = ?",
                   (p["id"], doc["branch_id"], util.ts(now), lead["id"]))
    return {"booked": True, "appointment_id": aid, "token": token, "patient_id": p["id"], "starts": starts}


def respond(phone: str, text: str, now: datetime, client=None, *, inbound_id: int | None = None,
            channel: str = "whatsapp", verified: bool = True, history: list[dict] | None = None) -> dict:
    """Answer one patient message with AI and create staff tasks.

    channel "whatsapp": stores the inbound message and sends the reply on WhatsApp.
    channel "voice": the caller (voice assistant) stores the conversation and speaks result["reply"].
    verified=False (a number typed on a public page, not proven): the model sees no patient record and
    nothing is booked under that number; booking requests become a call-back task instead.
    """
    ctx = build_context(phone, now)
    if history is not None:
        ctx["history"] = history
    if not verified:
        ctx["patient"], ctx["record"] = None, {}
    p = ctx["patient"]
    pid = p["id"] if p else None
    where = "WhatsApp" if channel == "whatsapp" else "the voice assistant"
    if channel == "whatsapp" and inbound_id is None:   # called directly (not from the webhook): store it first
        inbound_id = messaging.record_inbound(ctx["phone"], text, pid)
    rel_id = inbound_id
    rel_type = "message" if channel == "whatsapp" else "voice"
    try:
        out = ask_model(ctx, text, client=client)
        reply, notes = safe_reply(out)
    except ai.AIError as e:
        audit.log("ai", "ai_error", "message", inbound_id, {"error": str(e), "prompt": prompts.RECEPTIONIST_VERSION})
        _task("followup_call", f"AI could not answer on {where} — reply manually to +{ctx['phone']}: {text[:60]}", None,
              rel_type, rel_id, now + timedelta(minutes=15), now)
        return {"action": "ai_error", "error": str(e)}

    result = {"action": "ai_reply", "intent": out.intent, "urgency": out.urgency, "language": out.language, "notes": notes}
    for n in notes:
        audit.log("ai", "ai_" + n, "message", inbound_id)

    if out.intent == "emergency" or out.urgency == "emergency":
        _task("followup_call", f"URGENT: possible emergency on {where} from +{ctx['phone']}: {text[:60]}", None,
              rel_type, rel_id, now, now)
        audit.log("ai", "emergency_flagged", "message", inbound_id, {"phone": ctx["phone"]})
        result["task"] = "urgent"
    elif out.intent == "complaint":
        _task("complaint", f"Complaint on {where} from +{ctx['phone']}: {text[:60]}", None, rel_type, rel_id,
              now + timedelta(hours=4), now)
        result["task"] = "complaint"
    elif out.intent == "book_appointment" and out.patient_confirmed and not verified:
        _task("followup_call", f"Booking request on {where} from +{ctx['phone']} (number not verified): {text[:60]}",
              None, rel_type, rel_id, now + timedelta(minutes=30), now)
        reply = "Thank you. Our team will call you on this number to confirm the booking."
        result["task"] = "followup_call"
    elif out.intent == "book_appointment" and out.patient_confirmed and (out.doctor_id is not None or out.slot is not None):
        v = validate(out, ctx)
        if v["ok"]:
            b = _book(ctx, out, v["doctor"], now)
            if b["booked"]:
                pid = b["patient_id"]
                when = b["starts"].strftime("%a %d %b, %I:%M %p")
                reply = (f"{reply}\n\n✅ Booked: {v['doctor']['name']}, {when}, {v['doctor']['branch']}. "
                         f"Booking ID OPD-{b['appointment_id']}, token {b['token']}.")
                result.update(booked_appointment_id=b["appointment_id"])
            elif b["missing"] == "name":
                reply = "Happy to book this for you. May I have the patient's full name?"
            else:
                reply = _slot_unavailable_reply(v["doctor"], ctx)
        else:
            audit.log("ai", "ai_booking_rejected", "message", inbound_id, {"problems": v["problems"]})
            reply = _slot_unavailable_reply(v["doctor"], ctx) if v["doctor"] else \
                "Sorry, I couldn't find that doctor. Our team will call you to help with the booking."
            if not v["doctor"]:
                _task("followup_call", f"Help +{ctx['phone']} book an appointment", None, rel_type, rel_id,
                      now + timedelta(minutes=30), now)
            result["booking_rejected"] = v["problems"]
    if out.needs_human or out.intent in ("reschedule", "cancel"):
        _task("followup_call", f"{where[0].upper() + where[1:]} needs staff ({out.intent}) from +{ctx['phone']}: {text[:60]}",
              None, rel_type, rel_id, now + timedelta(minutes=30), now)
        result.setdefault("task", "followup_call")

    result["reply"] = reply
    if channel == "whatsapp":
        mid = messaging.send(ctx["phone"], "ai_reply", reply, patient_id=pid, require_consent=False, actor="ai")
        result["message_id"] = mid
    return result


def _slot_unavailable_reply(doc: dict, ctx: dict) -> str:
    nxt = ctx["slots"].get(doc["id"], [])[:3]
    if not nxt:
        return f"Sorry, {doc['name']} has no free time in the next 7 days. Our team will call you to help."
    times = ", ".join(datetime.strptime(s, SLOT_FMT).strftime("%a %d %b %I:%M %p") for s in nxt)
    return f"Sorry, that time is not available. Free times with {doc['name']}: {times}. Which one suits you?"
