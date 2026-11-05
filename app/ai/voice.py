"""Voice assistant: one spoken turn in, one reply out.

The browser turns speech into text and reads the reply aloud (Web Speech API); this module only ever
sees text. Audio is never stored. Rules, in order:
  1. Emergency words → immediate 108 reply and an URGENT staff task (no AI involved).
  2. AI on → the same receptionist as WhatsApp (real doctors and free slots only, no medical advice).
  3. AI off → a short deterministic menu: book, timings, fees, bill balance.
A number typed on the public demo page is not proven to be the caller's, so that session never sees a
patient record or bill and never books under the number: it gets a call-back task instead.
"""
import json
import re
import secrets
from datetime import datetime, timedelta

from app import audit, db, patients, util
from app.ai import client as ai
from app.ai import receptionist

LANGS = ("en-IN", "hi-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN")
CONSENT_TEXT = ("Your browser turns your voice into text (Chrome and Edge use Google's or Microsoft's speech service "
                "for this). Tec Tha Vital receives only the text, never the recording, keeps the conversation as text "
                "in the hospital's records, and uses it only to answer you and help with bookings.")
MAX_TEXT = 500

# Replies the menu speaks. Hindi is offered for the key lines; other languages are answered in English
# until the hospital's translators review those strings.
TEXT = {
    "en": {
        "hello": "Hello! I can book an appointment, tell you OPD timings and doctors' fees, or your bill balance. What would you like?",
        "emergency": "If this is an emergency, call 108 now or go to the nearest Emergency department. Our team is being alerted.",
        "timings": "Appointments are from 9 am to 1 pm and from 4 pm to 7 pm. Say 'book' to book one.",
        "fees": "Consultation fees: {fees}. Say 'book' to book one.",
        "choose_doctor": "Which doctor? {doctors}. Say the number.",
        "choose_slot": "Free times with {doctor}: {slots}. Say 1, 2 or 3.",
        "no_slots": "Sorry, {doctor} has no free time in the next 7 days. Our team will call you to help.",
        "booked": "Booked: {doctor}, {when}, {branch}. Booking ID OPD-{id}, token {token}.",
        "taken": "Sorry, that time was just taken. {again}",
        "not_understood": "Sorry, I didn't catch that. You can say: book, timings, fees, or bill.",
        "bill_none": "You have no pending bills. Thank you!",
        "bill_due": "Your pending balance is {amount}. You can pay from the Bills tab in the app.",
        "bill_login": "For your privacy I can't read bills here. Please log in to the patient app to see them.",
        "callback": "Thank you. Our team will call you on this number to confirm the booking.",
        "pick_number": "Please say a number from the list.",
    },
    "hi": {
        "hello": "नमस्ते! मैं अपॉइंटमेंट बुक कर सकता हूँ, ओपीडी का समय और डॉक्टर की फ़ीस बता सकता हूँ, या आपका बकाया बिल। आप क्या चाहेंगे?",
        "emergency": "अगर यह इमरजेंसी है, तो अभी 108 पर कॉल करें या नज़दीकी इमरजेंसी विभाग जाएँ। हमारी टीम को सूचना दी जा रही है।",
        "timings": "अपॉइंटमेंट सुबह 9 से दोपहर 1 बजे और शाम 4 से 7 बजे तक हैं। बुक करने के लिए 'बुक' बोलें।",
        "fees": "परामर्श फ़ीस: {fees}। बुक करने के लिए 'बुक' बोलें।",
        "choose_doctor": "कौन से डॉक्टर? {doctors}। नंबर बोलें।",
        "choose_slot": "{doctor} के साथ खाली समय: {slots}। 1, 2 या 3 बोलें।",
        "no_slots": "माफ़ कीजिए, {doctor} के पास अगले 7 दिन में समय नहीं है। हमारी टीम आपको कॉल करेगी।",
        "booked": "बुक हो गया: {doctor}, {when}, {branch}। बुकिंग आईडी OPD-{id}, टोकन {token}।",
        "taken": "माफ़ कीजिए, यह समय अभी किसी और ने ले लिया। {again}",
        "not_understood": "माफ़ कीजिए, मैं समझ नहीं पाया। आप बोल सकते हैं: बुक, समय, फ़ीस, या बिल।",
        "bill_none": "आपका कोई बकाया बिल नहीं है। धन्यवाद!",
        "bill_due": "आपका बकाया {amount} है। ऐप के बिल टैब से भुगतान कर सकते हैं।",
        "bill_login": "आपकी निजता के लिए मैं यहाँ बिल नहीं बता सकता। कृपया पेशेंट ऐप में लॉग इन करें।",
        "callback": "धन्यवाद। हमारी टीम बुकिंग पक्की करने के लिए इसी नंबर पर कॉल करेगी।",
        "pick_number": "कृपया सूची में से एक नंबर बोलें।",
    },
}

WORDS = {
    "book": ("book", "appointment", "appoint", "doctor", "बुक", "अपॉइंटमेंट", "डॉक्टर", "முன்பதிவு", "டாக்டர்", "அப்பாயிண்ட்",
             "బుక్", "అపాయింట్", "డాక్టర్", "ಬುಕ್", "ಅಪಾಯಿಂಟ್", "ವೈದ್ಯ", "ഡോക്ടർ", "ബുക്ക്", "അപ്പോയിന്റ്", "भेट"),
    "timings": ("time", "timing", "hours", "open", "समय", "टाइम", "நேரம்", "సమయం", "ಸಮಯ", "സമയം", "वेळ"),
    "fees": ("fee", "fees", "charge", "cost", "price", "फ़ीस", "फीस", "शुल्क", "கட்டணம்", "ఫీజు", "ಶುಲ್ಕ", "ಫೀ", "ഫീസ്", "फी"),
    "bill": ("bill", "balance", "due", "pending", "बिल", "बकाया", "பில்", "బిల్", "ಬಿಲ್", "ബിൽ"),
}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "first": 1, "second": 2, "third": 3,
                "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6}


class VoiceError(Exception):
    """Shown to the caller as is."""


def _t(lang: str, key: str, **kw) -> str:
    table = TEXT["hi"] if lang.startswith("hi") else TEXT["en"]
    return table[key].format(**kw)


def _lang(lang: str | None) -> str:
    return lang if lang in LANGS else "en-IN"


# ---------------------------------------------------------------- sessions

def start(*, patient: dict | None, phone: str | None, lang: str, consent: bool, actor: str) -> dict:
    if not consent:
        raise VoiceError("Please agree to voice processing first.")
    if patient is None:
        if not phone:
            raise VoiceError("Enter your mobile number to start.")
        try:
            phone = util.normalize_phone(phone)
        except ValueError:
            raise VoiceError("Enter a 10-digit mobile number, for example 98765 43210.")
    else:
        phone = patient["phone"]
    ts = util.ts(util.now())
    token = secrets.token_urlsafe(24)
    sid = db.execute("INSERT INTO voice_sessions(token, patient_id, phone, lang, consent_at, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?,?)", (token, patient["id"] if patient else None, phone, _lang(lang), ts, ts, ts))
    audit.log(actor, "voice_consent", "voice_session", sid, {"verified": patient is not None, "lang": _lang(lang)})
    return {"token": token, "greeting": _t(_lang(lang), "hello")}


def session(token: str, patient: dict | None) -> dict:
    s = db.one("SELECT * FROM voice_sessions WHERE token = ?", (token or "",))
    if s is None or not s["consent_at"]:
        raise VoiceError("This conversation has ended. Start again.")
    if (s["patient_id"] or None) != (patient["id"] if patient else None):
        raise VoiceError("This conversation belongs to another login. Start again.")
    return s


def _save(s: dict, direction: str, text: str, lang: str) -> None:
    db.execute("INSERT INTO voice_turns(session_id, direction, text, lang, created_at) VALUES (?,?,?,?,?)",
               (s["id"], direction, text, lang, util.ts(util.now())))


def _history(s: dict) -> list[dict]:
    rows = db.query("SELECT direction, text AS body, created_at FROM voice_turns WHERE session_id = ? ORDER BY id DESC LIMIT 11",
                    (s["id"],))
    return list(reversed(rows))


# ---------------------------------------------------------------- one turn

def turn(s: dict, text: str, lang: str, now: datetime, client=None) -> dict:
    lang = _lang(lang)
    text = " ".join((text or "").split())[:MAX_TEXT]
    if not text:
        raise VoiceError("I didn't hear anything. Tap the microphone and speak, or type instead.")
    verified = s["patient_id"] is not None
    _save(s, "in", text, lang)
    from app.routes import webhooks          # the same fixed emergency word list as WhatsApp
    if webhooks._looks_like_emergency(text):
        receptionist._task("followup_call", f"URGENT: possible emergency on the voice assistant from +{s['phone']}: {text[:60]}",
                           None, "voice", s["id"], now, now)
        audit.log("voice", "emergency_detected", "voice_session", s["id"])
        result = {"reply": _t(lang, "emergency"), "action": "emergency"}
    elif ai.enabled() or client is not None:
        r = receptionist.respond(s["phone"], text, now, client=client, channel="voice", verified=verified,
                                 history=_history(s))
        result = {"reply": r.get("reply") or _t(lang, "not_understood"), "action": r["action"]}
        if r["action"] == "ai_error":
            result["reply"] = _t(lang, "callback")
    else:
        result = _menu(s, text, lang, now, verified)
    _save(s, "out", result["reply"], lang)
    db.execute("UPDATE voice_sessions SET lang = ?, updated_at = ? WHERE id = ?", (lang, util.ts(now), s["id"]))
    audit.log("voice", "voice_turn", "voice_session", s["id"], {"action": result["action"]})
    return result


def _intent(text: str) -> str | None:
    low = text.lower()
    for intent, words in WORDS.items():
        if any(w in low for w in words):
            return intent
    return None


def _number(text: str) -> int | None:
    m = re.search(r"\b(\d)\b", text)
    if m:
        return int(m.group(1))
    low = text.lower()
    for w, n in NUMBER_WORDS.items():
        if re.search(rf"(^|\s){re.escape(w)}($|\s)", low):
            return n
    return None


def _doctors() -> list[dict]:
    return db.query("SELECT d.id, d.name, d.specialty, d.fee, d.branch_id, b.name AS branch FROM doctors d"
                    " JOIN branches b ON b.id = d.branch_id ORDER BY d.id LIMIT 6")


def _when(slot: str) -> str:
    return datetime.strptime(slot, receptionist.SLOT_FMT).strftime("%a %d %b, %I:%M %p")


def _set_state(s: dict, state: dict) -> None:
    db.execute("UPDATE voice_sessions SET state = ? WHERE id = ?", (json.dumps(state), s["id"]))


def _menu(s: dict, text: str, lang: str, now: datetime, verified: bool) -> dict:
    state = json.loads(s["state"] or "{}")
    step = state.get("step", "idle")
    intent = _intent(text)
    n = _number(text)

    if step == "choose_doctor" and n is not None and intent is None:
        docs = _doctors()
        if not 1 <= n <= len(docs):
            return {"reply": _t(lang, "pick_number"), "action": "menu"}
        doc = docs[n - 1]
        slots = receptionist.free_slots(now).get(doc["id"], [])[:3]
        if not slots:
            _set_state(s, {})
            return {"reply": _t(lang, "no_slots", doctor=doc["name"]), "action": "menu"}
        _set_state(s, {"step": "choose_slot", "doctor_id": doc["id"], "slots": slots})
        listed = "; ".join(f"{i}. {_when(x)}" for i, x in enumerate(slots, 1))
        return {"reply": _t(lang, "choose_slot", doctor=doc["name"], slots=listed), "action": "menu"}

    if step == "choose_slot" and n is not None and intent is None:
        slots = state.get("slots", [])
        if not 1 <= n <= len(slots):
            return {"reply": _t(lang, "pick_number"), "action": "menu"}
        return _book(s, state["doctor_id"], slots[n - 1], lang, now)

    if intent == "book":
        if not verified:
            _set_state(s, {})
            receptionist._task("followup_call", f"Voice assistant booking request from +{s['phone']} (number not verified)",
                               None, "voice", s["id"], now + timedelta(minutes=30), now)
            return {"reply": _t(lang, "callback"), "action": "callback_task"}
        docs = _doctors()
        _set_state(s, {"step": "choose_doctor"})
        listed = "; ".join(f"{i}. {d['name']}, {d['specialty']}, {d['branch']}" for i, d in enumerate(docs, 1))
        return {"reply": _t(lang, "choose_doctor", doctors=listed), "action": "menu"}
    if intent == "timings":
        return {"reply": _t(lang, "timings"), "action": "menu"}
    if intent == "fees":
        fees = "; ".join(f"{d['name']} ({d['specialty']}) {util.inr(d['fee'])}" for d in _doctors())
        return {"reply": _t(lang, "fees", fees=fees), "action": "menu"}
    if intent == "bill":
        if not verified:
            return {"reply": _t(lang, "bill_login"), "action": "menu"}
        due = db.scalar("SELECT COALESCE(SUM(total - paid), 0) FROM bills WHERE patient_id = ? AND total > paid",
                        (s["patient_id"],)) or 0
        return {"reply": _t(lang, "bill_due", amount=util.inr(due)) if due else _t(lang, "bill_none"), "action": "menu"}
    return {"reply": _t(lang, "not_understood"), "action": "menu"}


def _book(s: dict, doctor_id: int, slot: str, lang: str, now: datetime) -> dict:
    doc = next((d for d in _doctors() if d["id"] == doctor_id), None)
    free = receptionist.free_slots(now).get(doctor_id, [])
    if doc is None or slot not in free:
        _set_state(s, {})
        again = _t(lang, "choose_slot", doctor=doc["name"], slots="; ".join(
            f"{i}. {_when(x)}" for i, x in enumerate(free[:3], 1))) if doc and free else ""
        if doc and free:
            _set_state(s, {"step": "choose_slot", "doctor_id": doctor_id, "slots": free[:3]})
        return {"reply": _t(lang, "taken", again=again), "action": "slot_taken"}
    p = patients.get(s["patient_id"])
    starts = datetime.strptime(slot, receptionist.SLOT_FMT)
    token = (db.scalar("SELECT COALESCE(MAX(token_no),0) FROM appointments WHERE branch_id = ? AND date(starts_at) = ?",
                       (doc["branch_id"], starts.date().isoformat())) or 0) + 1
    aid = db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, token_no, source, created_at)"
                     " VALUES (?,?,?,?,'Booked',?,'Voice assistant',?)",
                     (p["id"], doc["id"], doc["branch_id"], util.ts(starts), token, util.ts(now)))
    audit.log(f"patient:{p['uid']}", "create", "appointment", aid, {"via": "voice", "token": token})
    _set_state(s, {})
    return {"reply": _t(lang, "booked", doctor=doc["name"], when=_when(slot), branch=doc["branch"], id=aid, token=token),
            "action": "booked", "appointment_id": aid}
