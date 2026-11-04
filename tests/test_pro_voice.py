"""Voice assistant: consent, CSRF, emergency rule, menu booking, demo privacy, AI path."""
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app import db, patients, util
from app.ai import receptionist, voice
from app.routes import patient_app, voice as voice_routes

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
PHONE = "9876543210"


@pytest.fixture()
def client(fresh_db):
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(patient_app.router, prefix="/my")
    app.include_router(voice_routes.router)
    return TestClient(app)


def _patient_login(client):
    p = patients.find_or_create("Ramesh Kumar", PHONE, consent=True)
    r = client.get("/my/login")
    r = client.post("/my/login/phone", data={"csrf": re.search(r'name="csrf" value="([^"]+)"', r.text).group(1), "phone": PHONE})
    code = db.scalar("SELECT body FROM messages WHERE template='patient_otp' ORDER BY id DESC LIMIT 1")[:6]
    client.post("/my/login/verify", data={"csrf": re.search(r'name="csrf" value="([^"]+)"', r.text).group(1),
                                          "phone": util.normalize_phone(PHONE), "code": code})
    page = client.get("/my/voice")
    assert page.status_code == 200
    return p, re.search(r'data-csrf="([^"]+)"', page.text).group(1)


def _start(client, csrf, mode="patient", **extra):
    return client.post("/voice/start", json={"mode": mode, "consent": True, "lang": "en-IN", **extra},
                       headers={"X-CSRF-Token": csrf})


def _say(client, csrf, token, text, mode="patient"):
    r = client.post("/voice/turn", json={"mode": mode, "token": token, "text": text, "lang": "en-IN"},
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    return r.json()


def test_consent_and_csrf_required(client):
    _, csrf = _patient_login(client)
    assert client.post("/voice/start", json={"mode": "patient", "consent": False}, headers={"X-CSRF-Token": csrf}).status_code == 400
    assert _start(client, "wrong").status_code == 403
    r = _start(client, csrf)
    assert r.status_code == 200 and r.json()["token"]
    assert db.one("SELECT * FROM audit_log WHERE action='voice_consent'")


def test_menu_books_a_real_free_slot(client):
    p, csrf = _patient_login(client)
    token = _start(client, csrf).json()["token"]
    assert "Which doctor" in _say(client, csrf, token, "I want to book an appointment")["reply"]
    assert "Free times" in _say(client, csrf, token, "1")["reply"]
    out = _say(client, csrf, token, "2")
    assert out["action"] == "booked" and "Booking ID OPD-" in out["reply"]
    appt = db.one("SELECT * FROM appointments WHERE patient_id = ?", (p["id"],))
    assert appt["source"] == "Voice assistant" and appt["status"] == "Booked"
    assert db.scalar("SELECT COUNT(*) FROM voice_turns") == 6               # text only, both directions
    assert "fees" in _say(client, csrf, token, "what are the fees").get("reply", "").lower()


def test_emergency_words_get_108_and_urgent_task(client):
    _, csrf = _patient_login(client)
    token = _start(client, csrf).json()["token"]
    out = _say(client, csrf, token, "my father has chest pain")
    assert out["action"] == "emergency" and "108" in out["reply"]
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE title LIKE 'URGENT%voice%'") == 1


def test_patient_hears_own_balance_but_demo_never_does(client):
    p, csrf = _patient_login(client)
    from app import billing
    billing.create_bill(p["id"], "A", [("Consultation", 500)], actor="test")
    token = _start(client, csrf).json()["token"]
    assert "₹500" in _say(client, csrf, token, "what is my bill balance")["reply"]
    # Public demo: someone types that same number. No balance, no booking under it.
    page = client.get("/voice/demo")
    demo_csrf = re.search(r'data-csrf="([^"]+)"', page.text).group(1)
    dt = _start(client, demo_csrf, mode="demo", phone=PHONE).json()["token"]
    out = _say(client, demo_csrf, dt, "bill balance", mode="demo")
    assert "₹" not in out["reply"] and "log in" in out["reply"].lower()
    out = _say(client, demo_csrf, dt, "book an appointment", mode="demo")
    assert out["action"] == "callback_task"
    assert db.scalar("SELECT COUNT(*) FROM appointments") == 0


def test_demo_page_only_in_demo_mode(client, monkeypatch):
    import dataclasses
    from app import config
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, whatsapp_mode="live"))
    assert client.get("/voice/demo").status_code == 404


class FakeClient:
    """Returns a canned receptionist answer without calling the API."""

    def __init__(self, out):
        self.out = out


def test_ai_path_speaks_reply_without_whatsapp(client, monkeypatch):
    _, csrf = _patient_login(client)
    token = _start(client, csrf).json()["token"]
    canned = receptionist.ReceptionistOutput(intent="ask_info", language="en", reply="OPD is open in the morning.",
                                             branch_id=None, doctor_id=None, slot=None, patient_name=None,
                                             patient_confirmed=False, needs_human=False, urgency="normal")
    monkeypatch.setattr(receptionist, "ask_model", lambda ctx, text, client=None: canned)
    monkeypatch.setattr(voice.ai, "enabled", lambda: True)
    before = db.scalar("SELECT COUNT(*) FROM messages")
    out = _say(client, csrf, token, "when is the OPD open")
    assert out["reply"] == "OPD is open in the morning." and out["action"] == "ai_reply"
    assert db.scalar("SELECT COUNT(*) FROM messages") == before            # nothing sent on WhatsApp
