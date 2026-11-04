"""UI: login, roles, CSRF and the main staff screens."""
import importlib.util
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app import auth, db, util
from app.routes import ui

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
HAS_BILLING = importlib.util.find_spec("app.billing") is not None


def make_app() -> FastAPI:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(ui.router)
    return app


@pytest.fixture()
def client(fresh_db):
    return TestClient(make_app())


def login(client, username="admin", password="secret-pass-1", role="admin", branch=None):
    auth.create_user(username, username.title(), password, role, branch)
    r = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


def csrf_of(client, path="/leads") -> str:
    html = client.get(path).text
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "page has no CSRF field"
    return m.group(1)


def test_password_hash_roundtrip():
    h = auth.hash_password("correct horse")
    assert h.startswith("pbkdf2_sha256$200000$")
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("wrong", h)


def test_login_required_redirects(client):
    r = client.get("/leads", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_wrong_password_is_rejected_and_audited(client):
    auth.create_user("admin", "Admin", "secret-pass-1", "admin")
    r = client.post("/login", data={"username": "admin", "password": "nope"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Wrong username or password" in r.text
    assert db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='login_failed'") == 1


def test_login_success_and_dashboard_renders(client):
    p = db.execute("INSERT INTO patients(uid,name,phone,consent_messages,created_at) VALUES ('TT-000001','Asha','919876543210',1,?)",
                   (util.ts(util.now()),))
    bill = db.execute("INSERT INTO bills(bill_no,patient_id,branch_id,total,paid,created_at) VALUES ('B-1',?,'A',5000,2000,?)",
                      (p, util.ts(util.now())))
    db.execute("INSERT INTO payments(bill_id,amount,mode,paid_at) VALUES (?,2000,'UPI',?)", (bill, util.ts(util.now())))
    login(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "Owner dashboard" in r.text
    assert "₹3,000" in r.text          # outstanding dues
    assert "<svg" in r.text            # collections chart
    assert db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='login_success'") == 1


def test_frontdesk_is_sent_to_leads_and_blocked_from_settings(client):
    login(client, "desk", role="frontdesk")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/leads"
    r = client.get("/settings")
    assert r.status_code == 403
    assert "have access to this screen" in r.text


def test_add_and_update_lead(client):
    login(client)
    token = csrf_of(client)
    r = client.post("/leads", data={"csrf": token, "name": "Ravi", "phone": "98765 11111", "need": "Fever",
                                     "source": "Walk-in", "branch_id": "A"}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    lead = db.one("SELECT * FROM leads")
    assert lead["phone"] == "919876511111" and lead["status"] == "New"
    r = client.post(f"/leads/{lead['id']}/status", data={"csrf": token, "status": "Contacted"}, follow_redirects=False)
    assert r.status_code == 303
    lead = db.one("SELECT * FROM leads")
    assert lead["status"] == "Contacted" and lead["first_reply_seconds"] is not None
    assert "Ravi" in client.get("/leads").text


def test_invalid_phone_shows_error(client):
    login(client)
    r = client.post("/leads", data={"csrf": csrf_of(client), "name": "X", "phone": "123", "source": "Walk-in"})
    assert r.status_code == 400 and "Enter a 10-digit mobile number" in r.text      # B1: plain words, under the field
    assert 'aria-invalid="true"' in r.text and 'value="123"' in r.text and "data-open-on-load" in r.text


def test_csrf_rejected(client):
    login(client)
    r = client.post("/leads", data={"csrf": "forged", "name": "Ravi", "phone": "9876511111", "source": "Walk-in"})
    assert r.status_code == 403
    assert db.scalar("SELECT COUNT(*) FROM leads") == 0


def test_booking_creates_patient_with_uid_and_token(client):
    login(client)
    token = csrf_of(client, "/appointments")
    doc = db.one("SELECT id FROM doctors WHERE branch_id='B'")
    for i in range(2):
        r = client.post("/appointments/book", data={"csrf": token, "name": "Meena", "phone": "9876500000",
                                                    "doctor_id": doc["id"], "starts_at": "2030-01-10T11:30", "consent": "1"},
                        follow_redirects=False)
        assert r.status_code == 303
    p = db.one("SELECT * FROM patients")
    assert p["uid"] == util.patient_uid(p["id"]) and p["consent_messages"] == 1
    assert db.scalar("SELECT COUNT(*) FROM patients") == 1          # same phone = same patient
    assert [a["token_no"] for a in db.query("SELECT token_no FROM appointments ORDER BY id")] == [1, 2]
    page = client.get("/appointments?day=2030-01-10").text
    assert "Meena" in page and p["uid"] in page


def test_consent_toggle_is_audited(client):
    login(client)
    pid = db.execute("INSERT INTO patients(uid,name,phone,consent_messages,created_at) VALUES ('TT-000009','Kiran','919812345678',0,?)",
                     (util.ts(util.now()),))
    token = csrf_of(client, f"/patients/{pid}")
    r = client.post(f"/patients/{pid}/consent", data={"csrf": token, "consent": "1"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.scalar("SELECT consent_messages FROM patients WHERE id=?", (pid,)) == 1
    assert db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='consent_given' AND entity_id=?", (pid,)) == 1


def test_patient_search(client):
    login(client)
    db.execute("INSERT INTO patients(uid,name,phone,created_at) VALUES ('TT-000005','Sunita Reddy','919800011122',?)",
               (util.ts(util.now()),))
    assert "Sunita Reddy" in client.get("/patients?q=sunita").text
    assert "Sunita Reddy" in client.get("/patients?q=98000").text
    assert "No patient matches" in client.get("/patients?q=zzz").text


def test_tasks_mark_done(client):
    login(client)
    tid = db.execute("INSERT INTO tasks(kind,title,branch_id,created_at) VALUES ('missed_call','Call back 98xxx','A',?)",
                     (util.ts(util.now()),))
    token = csrf_of(client, "/tasks")
    client.post(f"/tasks/{tid}/done", data={"csrf": token})
    assert db.scalar("SELECT status FROM tasks WHERE id=?", (tid,)) == "Done"


def test_settings_names_and_add_user(client):
    login(client)
    token = csrf_of(client, "/settings")
    client.post("/settings/names", data={"csrf": token, "hospital_name": "Sample Care", "branch_A": "Main Road", "branch_B": "Lake View"})
    assert db.get_setting("hospital_name", "") == "Sample Care"
    assert db.scalar("SELECT name FROM branches WHERE id='A'") == "Main Road"
    client.post("/settings/users", data={"csrf": token, "username": "Billing1", "full_name": "Bill Desk",
                                         "password": "longpass1", "role": "billing", "branch_id": "B"})
    u = db.one("SELECT * FROM users WHERE username='billing1'")
    assert u and u["role"] == "billing" and u["branch_id"] == "B"
    assert "Sample Care" in client.get("/settings").text


def test_messages_and_audit_pages(client):
    login(client)
    db.execute("INSERT INTO messages(to_phone,direction,template,body,status,created_at) VALUES ('919876543210','out','t','Hello <b>x</b>','simulated',?)",
               (util.ts(util.now()),))
    page = client.get("/messages").text
    assert "Hello &lt;b&gt;x&lt;/b&gt;" in page      # escaped
    assert "Simulate a patient message" in page
    assert client.get("/audit").status_code == 200


def test_branch_bound_user_only_sees_own_branch(client):
    now = util.ts(util.now())
    db.execute("INSERT INTO leads(name,phone,source,branch_id,created_at,updated_at) VALUES ('From A','919811111111','Walk-in','A',?,?)", (now, now))
    db.execute("INSERT INTO leads(name,phone,source,branch_id,created_at,updated_at) VALUES ('From B','919822222222','Walk-in','B',?,?)", (now, now))
    login(client, "deskb", role="frontdesk", branch="B")
    page = client.get("/leads?branch=A").text
    assert "From B" in page and "From A" not in page


@pytest.mark.skipif(not HAS_BILLING, reason="app.billing not built yet")
def test_billing_page_renders(client):
    login(client)
    assert client.get("/billing").status_code == 200
    assert client.get("/claims").status_code == 200


def test_logout(client):
    login(client)
    token = csrf_of(client)
    r = client.post("/logout", data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303
    client.cookies.clear()
    assert client.get("/leads", follow_redirects=False).status_code == 303
