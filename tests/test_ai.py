"""AI receptionist and insights, with a fake Claude client (no network, no cost)."""
from datetime import datetime
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app import db, patients
from app.ai import client as ai
from app.ai import insights, receptionist
from app.routes import webhooks

NOW = datetime(2026, 11, 4, 10, 0, 0)
PHONE = "919812345678"


class FakeClient:
    """Mimics client.beta.messages.parse(...) and records the request."""

    def __init__(self, parsed=None, error=None, stop_reason="end_turn"):
        self.parsed, self.error, self.stop_reason, self.calls = parsed, error, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.parsed, stop_details=None, content=[])


def out(**kw):
    base = dict(intent="other", language="en", reply="Hello!", branch_id=None, doctor_id=None, slot=None,
                patient_name=None, patient_confirmed=False, needs_human=False, urgency="normal")
    base.update(kw)
    return receptionist.ReceptionistOutput(**base)


def _last_out():
    return db.one("SELECT * FROM messages WHERE direction = 'out' ORDER BY id DESC LIMIT 1")


def _tasks(kind=None):
    return db.query("SELECT * FROM tasks" + (" WHERE kind = ?" if kind else ""), (kind,) if kind else ())


def test_request_shape_caches_stable_prompt_and_uses_structured_output(fresh_db):
    fc = FakeClient(out(intent="ask_info", reply="We are open 9 am to 7 pm."))
    receptionist.respond(PHONE, "What are your timings?", NOW, client=fc)
    kw = fc.calls[0]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["output_format"] is receptionist.ReceptionistOutput
    assert kw["output_config"] == {"effort": "low"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    user = kw["messages"][0]["content"]
    assert "<patient_message>\nWhat are your timings?\n</patient_message>" in user
    assert "Dr. S. Menon" in user and "2026-11-04" in user


def test_booking_happy_path_books_real_appointment(fresh_db):
    p = patients.find_or_create("Ramesh Kumar", PHONE, consent=True)
    fc = FakeClient(out(intent="book_appointment", reply="Thank you, booking it now.", branch_id="B", doctor_id=1,
                        slot="2026-11-05 11:30", patient_confirmed=True))
    r = receptionist.respond(PHONE, "yes 11:30 tomorrow is fine", NOW, client=fc)
    a = db.one("SELECT * FROM appointments WHERE id = ?", (r["booked_appointment_id"],))
    assert a["patient_id"] == p["id"] and a["doctor_id"] == 1 and a["starts_at"] == "2026-11-05 11:30:00"
    assert a["source"] == "WhatsApp AI" and a["token_no"] == 1
    assert "✅ Booked" in _last_out()["body"] and f"OPD-{a['id']}" in _last_out()["body"]


def test_new_number_booking_needs_name_then_creates_patient(fresh_db):
    fc = FakeClient(out(intent="book_appointment", doctor_id=2, branch_id="A", slot="2026-11-05 09:00",
                        patient_confirmed=True, patient_name=None))
    r = receptionist.respond(PHONE, "book 9 am", NOW, client=fc)
    assert "booked_appointment_id" not in r and "full name" in _last_out()["body"]
    fc.parsed = out(intent="book_appointment", doctor_id=2, branch_id="A", slot="2026-11-05 09:00",
                    patient_confirmed=True, patient_name="Anita Desai")
    r = receptionist.respond(PHONE, "Anita Desai", NOW, client=fc)
    p = db.one("SELECT * FROM patients WHERE phone = ?", (PHONE,))
    assert p["name"] == "Anita Desai" and p["uid"].startswith("TT-")
    assert db.one("SELECT patient_id FROM appointments WHERE id = ?", (r["booked_appointment_id"],))["patient_id"] == p["id"]


@pytest.mark.parametrize("kw,problem", [
    (dict(doctor_id=99, slot="2026-11-05 11:30"), "unknown doctor_id"),
    (dict(doctor_id=1, slot="2026-11-05 14:00"), "not free"),          # outside OPD hours
    (dict(doctor_id=1, slot="2026-11-05 11:30", branch_id="A"), "does not match"),
])
def test_invalid_doctor_or_slot_is_rejected(fresh_db, kw, problem):
    patients.find_or_create("Ramesh Kumar", PHONE, consent=True)
    fc = FakeClient(out(intent="book_appointment", reply="Your appointment is booked!", patient_confirmed=True, **kw))
    r = receptionist.respond(PHONE, "book it", NOW, client=fc)
    assert db.scalar("SELECT COUNT(*) FROM appointments") == 0
    assert any(problem in x for x in r["booking_rejected"])
    assert "booked!" not in _last_out()["body"]                      # model's false claim is never sent


def test_taken_slot_is_not_double_booked(fresh_db):
    p = patients.find_or_create("Ramesh Kumar", PHONE, consent=True)
    db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, created_at)"
               " VALUES (?,1,'B','2026-11-05 11:30:00','Booked','2026-11-04 09:00:00')", (p["id"],))
    fc = FakeClient(out(intent="book_appointment", doctor_id=1, branch_id="B", slot="2026-11-05 11:30", patient_confirmed=True))
    receptionist.respond(PHONE, "11:30 please", NOW, client=fc)
    assert db.scalar("SELECT COUNT(*) FROM appointments") == 1
    assert "not available" in _last_out()["body"]


def test_emergency_creates_urgent_task_and_108_line(fresh_db):
    fc = FakeClient(out(intent="emergency", urgency="emergency", reply="Please come now.", language="en"))
    r = receptionist.respond(PHONE, "my father has chest pain since morning", NOW, client=fc)
    t = _tasks("followup_call")
    assert r["task"] == "urgent" and t and t[0]["title"].startswith("URGENT")
    assert "108" in _last_out()["body"]


def test_medical_advice_in_reply_is_blocked(fresh_db):
    fc = FakeClient(out(intent="other", reply="You can take Dolo 650 mg twice a day."))
    r = receptionist.respond(PHONE, "can I take dolo 650 twice", NOW, client=fc)
    assert "medical_advice_blocked" in r["notes"]
    assert _last_out()["body"] == receptionist.SAFE_MEDICAL_REPLY


def test_complaint_and_needs_human_create_tasks(fresh_db):
    receptionist.respond(PHONE, "worst service", NOW, client=FakeClient(out(intent="complaint", needs_human=True)))
    assert _tasks("complaint")
    receptionist.respond(PHONE, "cancel my visit", NOW, client=FakeClient(out(intent="cancel")))
    assert any("cancel" in t["title"] for t in _tasks("followup_call"))


@pytest.mark.parametrize("err", [
    anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
    ai.AIError("boom"),
])
def test_api_error_creates_manual_task_and_sends_nothing(fresh_db, err):
    fc = FakeClient(error=err)
    r = receptionist.respond(PHONE, "hello", NOW, client=fc)
    assert r["action"] == "ai_error"
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE direction = 'out'") == 0
    assert any("AI could not answer" in t["title"] for t in _tasks("followup_call"))
    assert db.one("SELECT * FROM audit_log WHERE action = 'ai_error'")


def test_refusal_is_an_error_not_a_reply(fresh_db):
    fc = FakeClient(parsed=None, stop_reason="refusal")
    assert receptionist.respond(PHONE, "hello", NOW, client=fc)["action"] == "ai_error"


def test_otp_messages_never_reach_the_model(fresh_db):
    p = patients.find_or_create("Ramesh Kumar", PHONE, consent=True)
    db.execute("INSERT INTO messages(patient_id, to_phone, direction, template, body, status, created_at)"
               " VALUES (?,?,'out','patient_otp','Your code is 482913','simulated','2026-11-04 09:59:00')", (p["id"], PHONE))
    fc = FakeClient(out())
    receptionist.respond(PHONE, "what was my code", NOW, client=fc)
    assert "482913" not in fc.calls[0]["messages"][0]["content"]


def test_ai_off_webhook_behaves_as_before(fresh_db, monkeypatch):
    monkeypatch.delenv("TT_AI", raising=False)
    r = webhooks.handle_inbound(PHONE, "Hi, need a doctor", NOW)
    assert r["action"] == "lead_created" and _last_out()["template"] == "welcome_reply"


def test_ai_on_webhook_uses_receptionist(fresh_db, monkeypatch):
    monkeypatch.setenv("TT_AI", "on")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fc = FakeClient(out(intent="ask_info", reply="Hello! How can we help?"))
    monkeypatch.setattr(ai, "get_client", lambda: fc)
    r = webhooks.handle_inbound(PHONE, "Hi", NOW)
    assert r["action"] == "ai_reply" and r["lead_id"] and _last_out()["template"] == "ai_reply"
    # deterministic rules still win: STOP is handled without the model
    patients.find_or_create("Ramesh", PHONE, consent=True)
    calls = len(fc.calls)
    assert webhooks.handle_inbound(PHONE, "STOP", NOW)["action"] == "consent_withdrawn" and len(fc.calls) == calls


def test_ai_enabled_needs_key(monkeypatch):
    monkeypatch.setenv("TT_AI", "on")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert ai.enabled() is False


def test_insight_verification_drops_invented_numbers(fresh_db):
    data = insights.build_metrics(NOW)
    real = data["open_issues"]["services_not_yet_billed"]           # e.g. "₹0"
    fc = FakeClient(insights.Insights(
        insights=[f"Services not yet billed stand at {real}.",
                  "Collections rose 37% versus last week.",          # invented number
                  "Branch A was below its 7-day average."],
        action="Call the 12 patients with the oldest dues."))          # invented number
    text = insights.owner_insight(NOW, client=fc)
    assert real in text and "37%" not in text and "12 patients" not in text
    assert "Branch A was below" in text and "Suggested action" not in text
    assert db.one("SELECT * FROM audit_log WHERE action = 'ai_insight_dropped'")
    assert fc.calls[0]["output_config"] == {"effort": "medium"}


def test_insight_off_returns_none(fresh_db, monkeypatch):
    monkeypatch.delenv("TT_AI", raising=False)
    assert insights.owner_insight(NOW) is None
