"""Patient app (/my): OTP login, booking, bills, consent, feedback, CSRF."""
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app import billing, db, patients, util
from app.routes import patient_app

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
PHONE = "9876543210"
FULL = "919876543210"


@pytest.fixture()
def client(fresh_db):
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(patient_app.router, prefix="/my")
    return TestClient(app)


@pytest.fixture()
def patient(fresh_db):
    return patients.find_or_create("Ramesh Kumar", PHONE, consent=True)


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "no csrf token on page"
    return m.group(1)


def _last_code() -> str:
    body = db.scalar("SELECT body FROM messages WHERE template='patient_otp' ORDER BY id DESC LIMIT 1")
    return body[:6]


def _ask_code(client, phone=PHONE):
    r = client.get("/my/login")
    return client.post("/my/login/phone", data={"csrf": _csrf(r.text), "phone": phone})


def _login(client, phone=PHONE):
    r = _ask_code(client, phone)
    assert r.status_code == 200, r.text
    r = client.post("/my/login/verify", data={"csrf": _csrf(r.text), "phone": util.normalize_phone(phone), "code": _last_code()},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/"
    return client


def test_login_required_redirects(client):
    r = client.get("/my/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/login"


def test_otp_login_success_and_code_not_shown(client, patient):
    r = _ask_code(client)
    code = _last_code()
    assert code not in r.text
    assert "staff Messages screen" in r.text
    assert db.scalar("SELECT require_consent FROM (SELECT 1 AS require_consent)") == 1  # sanity
    _login(client)
    home = client.get("/my/")
    assert home.status_code == 200 and "Ramesh" in home.text
    assert db.one("SELECT * FROM audit_log WHERE action='patient_login'")


def _strip_tokens(html: str) -> str:
    html = re.sub(r'name="csrf" value="[^"]+"', "", html)
    return re.sub(r'name="phone" value="\d+"|\+91 ••••• \d+', "", html)


def test_unknown_phone_gets_same_page_as_known_and_no_otp(client, patient):
    """S-08: the login must not reveal whether a number belongs to a patient."""
    known = _ask_code(client, PHONE)
    unknown = _ask_code(client, "9123456780")
    assert known.status_code == unknown.status_code == 200
    assert "If this number is registered" in unknown.text
    assert _strip_tokens(known.text) == _strip_tokens(unknown.text)
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE template='patient_otp' AND to_phone='919123456780'") == 0
    # A guessed code for the unknown number gets the same "not right" answer as for a real patient.
    r = client.post("/my/login/verify", data={"csrf": _csrf(unknown.text), "phone": "919123456780", "code": "123456"})
    assert r.status_code == 400 and "not right" in r.text


def test_otp_sends_capped_per_ip(client, fresh_db):
    """S-08: one caller can't trigger WhatsApp codes to many numbers."""
    for i in range(patient_app.OTP_MAX_PER_IP_HOUR):
        patients.find_or_create(f"P{i}", f"98765000{i:02d}", consent=True)
        assert _ask_code(client, f"98765000{i:02d}").status_code == 200
    r = _ask_code(client, "9876500099")
    assert r.status_code == 429 and "wait an hour" in r.text
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE template='patient_otp'") == patient_app.OTP_MAX_PER_IP_HOUR
    assert db.one("SELECT * FROM audit_log WHERE action='otp_throttled'")


def test_patient_logout_ends_session_server_side(client, patient):
    """S-10: a copied patient cookie stops working after logout."""
    _login(client)
    cookie = client.cookies.get(patient_app.COOKIE)
    home = client.get("/my/profile")
    client.post("/my/logout", data={"csrf": _csrf(home.text)})
    client.cookies.clear()
    client.cookies.set(patient_app.COOKIE, cookie)
    assert client.cookies.get(patient_app.COOKIE) == cookie
    r = client.get("/my/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/login"


def test_patient_cookie_secure_on_https_or_trusted_proxy(client, patient, monkeypatch):
    """S-09: Secure flag on HTTPS; X-Forwarded-Proto counts only with TT_BEHIND_PROXY=1."""
    r = client.get("/my/login", headers={"X-Forwarded-Proto": "https"})
    assert "secure" not in r.headers["set-cookie"].lower()
    monkeypatch.setenv("TT_BEHIND_PROXY", "1")
    r = client.get("/my/login", headers={"X-Forwarded-Proto": "https"})
    assert "secure" in r.headers["set-cookie"].lower()


def test_wrong_code_and_attempt_limit(client, patient):
    r = _ask_code(client)
    token = _csrf(r.text)
    for i in range(4):
        r = client.post("/my/login/verify", data={"csrf": token, "phone": FULL, "code": "000000" if _last_code() != "000000" else "111111"})
        assert r.status_code == 400 and "not right" in r.text
    r = client.post("/my/login/verify", data={"csrf": token, "phone": FULL, "code": "000000" if _last_code() != "000000" else "111111"})
    assert "Too many wrong tries" in r.text
    # even the right code no longer works
    r = client.post("/my/login/verify", data={"csrf": token, "phone": FULL, "code": _last_code()}, follow_redirects=False)
    assert r.status_code == 400


def test_expired_code(client, patient):
    r = _ask_code(client)
    token = _csrf(r.text)
    db.execute("UPDATE patient_otps SET expires_at = ?", (util.ts(util.now() - timedelta(minutes=1)),))
    r = client.post("/my/login/verify", data={"csrf": token, "phone": FULL, "code": _last_code()}, follow_redirects=False)
    assert r.status_code == 400 and "expired" in r.text


def test_rate_limit(client, patient):
    for _ in range(3):
        assert _ask_code(client).status_code == 200
    r = _ask_code(client)
    assert r.status_code == 429 and "wait 10 minutes" in r.text


def test_login_csrf_rejected(client, patient):
    client.get("/my/login")
    r = client.post("/my/login/phone", data={"csrf": "wrong", "phone": PHONE})
    assert r.status_code == 403


def test_booking_and_taken_slot(client, patient):
    _login(client)
    doc = db.one("SELECT * FROM doctors WHERE branch_id='B'")
    day = (util.now().date() + timedelta(days=1)).isoformat()
    page = client.get(f"/my/book?branch=B&doctor={doc['id']}&day={day}")
    assert 'value="10:00"' in page.text
    token = _csrf(page.text)
    r = client.post("/my/book", data={"csrf": token, "doctor_id": doc["id"], "day": day, "slot": "10:00"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/my/?msg=Booked")
    a = db.one("SELECT * FROM appointments WHERE patient_id=?", (patient["id"],))
    assert a["source"] == "Patient app" and a["status"] == "Booked" and a["starts_at"].endswith("10:00:00") and a["token_no"] == 1
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE template='appt_confirmation'") == 1
    page = client.get(f"/my/book?branch=B&doctor={doc['id']}&day={day}")
    assert 'value="10:00"' not in page.text
    r = client.post("/my/book", data={"csrf": token, "doctor_id": doc["id"], "day": day, "slot": "10:00"}, follow_redirects=False)
    assert "just%20taken" in r.headers["location"] or "just+taken" in r.headers["location"]
    assert db.scalar("SELECT COUNT(*) FROM appointments") == 1


def test_booking_without_consent_still_books(client, patient):
    _login(client)
    patients.set_consent(patient["id"], False)
    doc = db.one("SELECT * FROM doctors WHERE branch_id='A'")
    day = (util.now().date() + timedelta(days=2)).isoformat()
    token = _csrf(client.get("/my/profile").text)
    r = client.post("/my/book", data={"csrf": token, "doctor_id": doc["id"], "day": day, "slot": "16:00"})
    assert "messages are turned off" in r.text
    assert db.scalar("SELECT COUNT(*) FROM appointments") == 1


def test_appointment_confirm_cancel_reschedule(client, patient):
    _login(client)
    doc = db.one("SELECT * FROM doctors LIMIT 1")
    when = util.ts(util.now() + timedelta(days=1))
    aid = db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, token_no, created_at) VALUES (?,?,?,?, 'Booked', 3, ?)",
                     (patient["id"], doc["id"], doc["branch_id"], when, util.ts(util.now())))
    token = _csrf(client.get("/my/").text)
    client.post(f"/my/appointments/{aid}/action", data={"csrf": token, "action": "confirm"})
    assert db.scalar("SELECT status FROM appointments WHERE id=?", (aid,)) == "Confirmed"
    client.post(f"/my/appointments/{aid}/action", data={"csrf": token, "action": "reschedule"})
    assert db.one("SELECT * FROM tasks WHERE kind='followup_call' AND related_id=?", (aid,))
    client.post(f"/my/appointments/{aid}/action", data={"csrf": token, "action": "cancel"})
    assert db.scalar("SELECT status FROM appointments WHERE id=?", (aid,)) == "Cancelled"


def test_pay_records_payment(client, patient):
    _login(client)
    bid = billing.create_bill(patient["id"], "A", [("Consultation", 600), ("X-ray", 850)])
    page = client.get(f"/my/bills/{bid}/pay")
    assert "DEMO" in page.text and "₹1,450" in page.text
    client.post(f"/my/bills/{bid}/pay", data={"csrf": _csrf(page.text), "mode": "UPI"})
    b = db.one("SELECT * FROM bills WHERE id=?", (bid,))
    assert b["paid"] == 1450
    pay = db.one("SELECT * FROM payments WHERE bill_id=?", (bid,))
    assert pay["mode"] == "UPI"
    assert db.one("SELECT * FROM audit_log WHERE actor=? AND entity='payment'", (f"patient:{patient['uid']}",)) or \
        db.one("SELECT * FROM audit_log WHERE actor=?", (f"patient:{patient['uid']}",))


def test_cannot_see_other_patients_bill(client, patient):
    _login(client)
    other = patients.find_or_create("Someone Else", "9811111111", consent=True)
    bid = billing.create_bill(other["id"], "A", [("Consultation", 500)])
    assert client.get(f"/my/bills/{bid}").status_code == 404


def test_consent_toggle_audited(client, patient):
    _login(client)
    page = client.get("/my/profile")
    client.post("/my/profile/consent", data={"csrf": _csrf(page.text), "consent": "0"})
    assert db.scalar("SELECT consent_messages FROM patients WHERE id=?", (patient["id"],)) == 0
    assert db.one("SELECT * FROM audit_log WHERE action='consent_withdrawn' AND actor=?", (f"patient:{patient['uid']}",))


def test_feedback_low_creates_complaint_high_shows_review(client, patient):
    _login(client)
    doc = db.one("SELECT * FROM doctors LIMIT 1")
    past = util.ts(util.now() - timedelta(days=1))
    a1 = db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, created_at) VALUES (?,?,?,?, 'Visited', ?)",
                    (patient["id"], doc["id"], doc["branch_id"], past, past))
    a2 = db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, created_at) VALUES (?,?,?,?, 'Visited', ?)",
                    (patient["id"], doc["id"], doc["branch_id"], past, past))
    token = _csrf(client.get(f"/my/feedback/{a1}").text)
    r = client.post(f"/my/feedback/{a1}", data={"csrf": token, "score": "2", "comment": "Long wait"})
    assert "manager will call" in r.text
    f = db.one("SELECT * FROM feedback WHERE appointment_id=?", (a1,))
    assert f["escalated"] == 1
    assert db.one("SELECT * FROM tasks WHERE kind='complaint' AND related_id=?", (f["id"],))
    r = client.post(f"/my/feedback/{a2}", data={"csrf": token, "score": "5"})
    assert "Google review" in r.text


def test_post_without_csrf_rejected(client, patient):
    _login(client)
    r = client.post("/my/profile/consent", data={"consent": "0"})
    assert r.status_code == 403
    assert db.scalar("SELECT consent_messages FROM patients WHERE id=?", (patient["id"],)) == 1


def test_pwa_files(client, fresh_db):
    m = client.get("/my/manifest.webmanifest").json()
    assert m["start_url"] == "/my/" and m["display"] == "standalone"
    sw = client.get("/my/sw.js")
    assert sw.headers["service-worker-allowed"] == "/my/"
    assert client.get("/static/icons/patient-192.png").status_code == 200


# ---------- demo vs live mode ----------

def _live(monkeypatch):
    import dataclasses
    from app import config
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, whatsapp_mode="live"))


def test_demo_mode_shows_demo_labels_and_sample_values(client, patient):
    _login(client)
    oid = billing.create_order(patient["id"], "A", "Lab", "CBC", 400)
    r = client.get(f"/my/reports/{oid}")
    assert "Demo · sample report" in r.text and "Haemoglobin" in r.text
    assert 'class="demo-badge"' in client.get("/my/").text


def test_live_mode_pay_records_nothing_and_report_has_no_values(client, patient, monkeypatch):
    _login(client)  # OTP is sent while still in simulator mode
    bid = billing.create_bill(patient["id"], "A", [("Consultation", 600)])
    oid = billing.create_order(patient["id"], "A", "Lab", "CBC", 400)
    token = _csrf(client.get("/my/profile").text)
    _live(monkeypatch)
    page = client.get(f"/my/bills/{bid}/pay")
    assert "Online payment is not set up yet" in page.text and "DEMO" not in page.text
    r = client.post(f"/my/bills/{bid}/pay", data={"csrf": token, "mode": "UPI"})
    assert "not set up yet" in r.text
    assert db.scalar("SELECT paid FROM bills WHERE id=?", (bid,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM payments") == 0
    rep = client.get(f"/my/reports/{oid}")
    assert "Collect your report at the lab" in rep.text
    assert "Haemoglobin" not in rep.text and "sample report" not in rep.text
    assert 'class="demo-badge"' not in client.get("/my/").text
