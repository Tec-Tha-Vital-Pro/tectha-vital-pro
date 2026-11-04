import dataclasses
import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, db, patients, util
from app.routes import webhooks


@pytest.fixture()
def client(fresh_db):
    app = FastAPI()
    app.include_router(webhooks.router, prefix="/webhooks")
    return TestClient(app)


KEY = {"X-API-Key": "test-key"}
SECRET = "s3cret"


def _signed(client, payload):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/whatsapp", content=raw,
                       headers={"X-Hub-Signature-256": sig, "content-type": "application/json"})


def _settings(monkeypatch, **kw):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, **kw))


def _sim(client, phone, text):
    r = client.post("/webhooks/simulate-inbound", json={"phone": phone, "text": text}, headers=KEY)
    assert r.status_code == 200, r.text
    return r.json()


def _last_out():
    return db.one("SELECT * FROM messages WHERE direction = 'out' ORDER BY id DESC LIMIT 1")


def test_verify(client):
    ok = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "tectha-verify", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert bad.status_code == 403


def _meta_payload(phone, text):
    return {"entry": [{"changes": [{"value": {"messages": [{"from": phone, "type": "text", "text": {"body": text}}]}}]}]}


def test_signature_required_when_secret_set(client, monkeypatch):
    _settings(monkeypatch, whatsapp_app_secret="s3cret")
    raw = json.dumps(_meta_payload("919812345678", "Hi")).encode()
    r = client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": "sha256=deadbeef", "content-type": "application/json"})
    assert r.status_code == 401
    sig = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    r = client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": sig, "content-type": "application/json"})
    assert r.status_code == 200
    assert r.json()["processed"][0]["action"] == "lead_created"


def test_meta_unsupported_type_reported(client, monkeypatch):
    _settings(monkeypatch, whatsapp_app_secret=SECRET)
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "919812345678", "type": "image"}]}}]}]}
    r = _signed(client, payload)
    assert r.json()["processed"][0]["action"] == "unsupported_type"


def test_unknown_phone_creates_lead_and_welcome(client):
    res = _sim(client, "98123 45678", "Need a knee doctor")
    assert res["action"] == "lead_created"
    lead = db.one("SELECT * FROM leads WHERE id = ?", (res["lead_id"],))
    assert lead["source"] == "WhatsApp" and lead["need"] == "Need a knee doctor" and lead["first_reply_seconds"] == 0
    out = _last_out()
    assert out["template"] == "welcome_reply" and "Branch A" in out["body"]
    assert _sim(client, "9812345678", "Hello?")["action"] == "lead_existing"
    assert db.scalar("SELECT COUNT(*) FROM leads") == 1


def _visited_with_feedback_request(client):
    p = patients.find_or_create("Asha", "9876500001", consent=True)
    now = util.now()
    aid = db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, created_at) VALUES (?,?,?,?,?,?)",
                     (p["id"], 1, "B", util.ts(now - timedelta(hours=4)), "Visited", util.ts(now)))
    from app import automations
    automations.feedback_requests(now)
    return p, aid


def test_feedback_low_score_creates_complaint(client):
    p, aid = _visited_with_feedback_request(client)
    res = _sim(client, p["phone"], "2")
    assert res["action"] == "feedback_low"
    fb = db.one("SELECT * FROM feedback WHERE id = ?", (res["feedback_id"],))
    assert fb["score"] == 2 and fb["escalated"] == 1 and fb["appointment_id"] == aid
    task = db.one("SELECT * FROM tasks WHERE kind = 'complaint'")
    assert task["status"] == "Open" and task["branch_id"] == "B"


def test_feedback_high_score_sends_review_link(client):
    p, _ = _visited_with_feedback_request(client)
    res = _sim(client, p["phone"], "5")
    assert res["action"] == "feedback_high"
    assert config.settings.review_link in _last_out()["body"]
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE kind = 'complaint'") == 0


def _reminded(client):
    p = patients.find_or_create("Ravi", "9876500002", consent=True)
    now = util.now()
    aid = db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, created_at) VALUES (?,?,?,?,?,?)",
                     (p["id"], 1, "B", util.ts(now + timedelta(hours=10)), "Booked", util.ts(now)))
    from app import automations
    automations.appointment_reminders(now)
    return p, aid


def test_reminder_reply_1_confirms(client):
    p, aid = _reminded(client)
    res = _sim(client, p["phone"], "1")
    assert res == {"action": "appointment_confirmed", "appointment_id": aid}
    assert db.one("SELECT status FROM appointments WHERE id = ?", (aid,))["status"] == "Confirmed"
    assert _last_out()["template"] == "appt_confirmed"


def test_reminder_reply_2_and_3(client):
    p, aid = _reminded(client)
    assert _sim(client, p["phone"], "2")["action"] == "reschedule_requested"
    assert db.one("SELECT * FROM tasks WHERE kind = 'followup_call'")["related_id"] == aid
    p2, aid2 = _reminded(client)
    assert _sim(client, p2["phone"], "3")["action"] == "appointment_cancelled"
    assert db.one("SELECT status FROM appointments WHERE id = ?", (aid2,))["status"] == "Cancelled"


def test_other_text_creates_staff_task(client):
    p = patients.find_or_create("Meena", "9876500003", consent=True)
    res = _sim(client, p["phone"], "Is the lab open on Sunday?")
    assert res["action"] == "staff_followup"
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE kind = 'followup_call'") == 1


def test_stop_withdraws_consent(client):
    p = patients.find_or_create("Meena", "9876500004", consent=True)
    assert _sim(client, p["phone"], "stop")["action"] == "consent_withdrawn"
    assert patients.get(p["id"])["consent_messages"] == 0


def test_simulator_form_redirects_and_live_mode_404(client, monkeypatch):
    r = client.post("/webhooks/simulate-inbound", data={"phone": "9812345670", "text": "Hi"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"   # not logged in: no fake patient messages
    assert client.post("/webhooks/simulate-inbound", json={"phone": "9812345670", "text": "Hi"}).status_code == 401
    _settings(monkeypatch, whatsapp_mode="live")
    assert client.post("/webhooks/simulate-inbound", json={"phone": "9812345670", "text": "Hi"}, headers=KEY).status_code == 404


def test_simulator_rejects_bad_phone(client):
    assert client.post("/webhooks/simulate-inbound", json={"phone": "123", "text": "Hi"}, headers=KEY).status_code == 400


def test_missed_call_api_key(client, monkeypatch):
    body = {"phone": "9812345679", "branch_id": "A"}
    assert client.post("/webhooks/missed-call", json=body).status_code == 401
    r = client.post("/webhooks/missed-call", json=body, headers={"X-API-Key": config.settings.api_key})
    assert r.status_code == 200
    task = db.one("SELECT * FROM tasks WHERE id = ?", (r.json()["task_id"],))
    assert task["kind"] == "missed_call" and task["branch_id"] == "A" and task["status"] == "Open"
    lead = db.one("SELECT * FROM leads WHERE id = ?", (r.json()["lead_id"],))
    assert lead["source"] == "Phone call" and lead["name"] == "Unknown caller"
    assert client.post("/webhooks/missed-call", json={"phone": "9812345679", "branch_id": "Z"},
                       headers={"X-API-Key": config.settings.api_key}).status_code == 400
    _settings(monkeypatch, api_key="")
    assert client.post("/webhooks/missed-call", json=body, headers={"X-API-Key": "x"}).status_code == 503


def test_unsigned_meta_webhook_refused_without_secret(client):
    assert client.post("/webhooks/whatsapp", json={"entry": []}).status_code == 503


def test_meta_retry_of_same_message_is_handled_once(fresh_db, monkeypatch):
    _settings(monkeypatch, whatsapp_app_secret=SECRET)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes import webhooks
    app = FastAPI(); app.include_router(webhooks.router, prefix="/webhooks")
    c = TestClient(app)
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "wamid.TEST1", "from": "919811122233", "type": "text", "text": {"body": "Hi, need a doctor"}}]}}]}]}
    first = _signed(c, body).json()["processed"][0]
    second = _signed(c, body).json()["processed"][0]
    assert first["action"] != "duplicate_ignored"
    assert second["action"] == "duplicate_ignored"
    assert fresh_db.scalar("SELECT COUNT(*) FROM leads WHERE phone='919811122233'") == 1


def test_emergency_words_get_immediate_108_reply(client):
    res = _sim(client, "9812345671", "Papa ko seene mein dard ho raha hai")
    assert res["action"] == "emergency"
    assert "108" in db.scalar("SELECT body FROM messages WHERE template='emergency_reply'")
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE title LIKE 'URGENT%'") == 1
