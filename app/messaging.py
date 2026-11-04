"""Outbound WhatsApp. Every send is consent-checked, stored and audited.

Simulator mode stores the message as 'simulated' (shown in the Messages screen) and
sends nothing. Live mode calls the WhatsApp Cloud API. Note: outside the 24-hour
customer-service window Meta only allows pre-approved templates; live free-text
sends use the approved template passed as `wa_template` (see app/wa_templates.py).
With no template, a send outside the window is stored as 'failed' with the reason,
never silently dropped.
"""
from datetime import timedelta
import httpx

from app import audit, config, db, util, wa_templates

GRAPH_URL = "https://graph.facebook.com/v21.0/{phone_id}/messages"


# Messages whose text is a secret (one-time login codes). In live mode the text is
# sent to the patient but never stored, so staff screens cannot show it.
SECRET_TEMPLATES = {"patient_otp"}


class SendBlocked(Exception):
    """Raised when a message may not be sent (no consent)."""


def send(to_phone: str, template: str, body: str, *, patient_id: int | None = None,
         related_type: str | None = None, related_id: int | None = None,
         require_consent: bool = True, actor: str = "automation",
         wa_template: tuple[str, list[str]] | None = None) -> int:
    """Send one WhatsApp text. Returns the message row id.

    Raises SendBlocked when the patient has not consented; the attempt is still stored
    as 'blocked_no_consent' so staff can see why nothing went out.
    """
    to_phone = util.normalize_phone(to_phone)
    created = util.ts(util.now())

    if require_consent:
        if patient_id is None:
            raise ValueError("require_consent=True needs a patient_id")
        p = db.one("SELECT consent_messages FROM patients WHERE id = ?", (patient_id,))
        if p is None:
            raise LookupError(f"Patient {patient_id} not found")
        if not p["consent_messages"]:
            mid = _store(patient_id, to_phone, template, body, "blocked_no_consent", "Patient has not given consent", related_type, related_id, created)
            audit.log(actor, "message_blocked", "message", mid, {"template": template, "reason": "no consent"})
            raise SendBlocked(f"Patient {patient_id} has not consented to messages")

    s = config.settings
    if s.whatsapp_mode == "simulator":
        status = "simulated"
        mid = _store(patient_id, to_phone, template, body, status, None, related_type, related_id, created)
    else:
        if _in_service_window(to_phone):
            status, error = _send_live(to_phone, {"type": "text", "text": {"body": body}})
        elif wa_template is not None:
            name, values = wa_template
            status, error = _send_live(to_phone, {"type": "template", "template": {
                "name": name, "language": {"code": wa_templates.TEMPLATES[name]["language"]},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": v} for v in values]}]}})
        else:
            status, error = "failed", (f"Outside WhatsApp's 24-hour window and no approved template for '{template}'. "
                                       "Reply after the patient messages, or add a template.")
        stored = "Login code sent (hidden for security)" if template in SECRET_TEMPLATES else body
        mid = _store(patient_id, to_phone, template, stored, status, error, related_type, related_id, created)
    outcome = "simulated" if s.whatsapp_mode == "simulator" else ("sent" if status == "sent" else "failed")
    audit.log(actor, "message_" + outcome, "message", mid, {"template": template, "to": to_phone})
    return mid


def record_inbound(from_phone: str, body: str, patient_id: int | None) -> int:
    mid = _store(patient_id, util.normalize_phone(from_phone), "inbound", body, "received", None, None, None, util.ts(util.now()))
    audit.log("webhook", "message_received", "message", mid)
    return mid


def _in_service_window(phone: str) -> bool:
    """True if the patient messaged us in the last 24 hours (free text allowed)."""
    since = util.ts(util.now() - timedelta(hours=24))
    return db.scalar("SELECT 1 FROM messages WHERE to_phone = ? AND direction = 'in' AND created_at >= ? LIMIT 1",
                     (phone, since)) is not None


def _send_live(to_phone: str, message: dict) -> tuple[str, str | None]:
    s = config.settings
    try:
        r = httpx.post(
            GRAPH_URL.format(phone_id=s.whatsapp_phone_id),
            headers={"Authorization": f"Bearer {s.whatsapp_token}"},
            json={"messaging_product": "whatsapp", "to": to_phone, **message},
            timeout=15,
        )
    except httpx.HTTPError as e:
        return "failed", f"Could not reach WhatsApp: {e}"
    if r.status_code >= 400:
        return "failed", f"HTTP {r.status_code}: {r.text[:500]}"
    return "sent", None


def _store(patient_id, to_phone, template, body, status, error, related_type, related_id, created) -> int:
    direction = "in" if status == "received" else "out"
    return db.execute(
        "INSERT INTO messages(patient_id, to_phone, direction, template, body, status, error, related_type, related_id, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (patient_id, to_phone, direction, template, body, status, error, related_type, related_id, created),
    )
