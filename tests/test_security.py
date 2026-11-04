"""Security fixes from docs/SECURITY_REVIEW.md and docs/BUGS.md, one regression test (or more) per finding."""
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, automations, billing, db, main, patients, util
from tests.test_ui import csrf_of, login

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(fresh_db):
    return TestClient(main.app)


def _now() -> str:
    return util.ts(util.now())


@pytest.fixture()
def two_branches(fresh_db):
    """One patient at each branch with a bill, an order, a claim, a lead, a task and an appointment."""
    out = {}
    for br, phone in (("A", "9811111111"), ("B", "9822222222")):
        p = patients.find_or_create(f"Patient {br}", phone, consent=True)
        doc = db.scalar("SELECT id FROM doctors WHERE branch_id = ?", (br,))
        out[br] = {
            "patient": p["id"],
            "bill": billing.create_bill(p["id"], br, [(f"Consult {br}", 1000)]),
            "order": billing.create_order(p["id"], br, "Lab", f"CBC {br}", 400),
            "claim": billing.create_claim(p["id"], br, f"Insurer {br}", 50000),
            "lead": db.execute("INSERT INTO leads(name,phone,source,branch_id,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                               (f"Lead {br}", "91" + phone, "Walk-in", br, _now(), _now())),
            "task": db.execute("INSERT INTO tasks(kind,title,branch_id,created_at) VALUES ('missed_call',?,?,?)",
                               (f"Call back {br}", br, _now())),
            "appt": db.execute("INSERT INTO appointments(patient_id,doctor_id,branch_id,starts_at,status,token_no,created_at)"
                               " VALUES (?,?,?,?, 'Booked', 1, ?)", (p["id"], doc, br, "2030-01-10 10:00:00", _now())),
        }
        db.execute("INSERT INTO messages(patient_id,to_phone,direction,template,body,status,created_at)"
                   " VALUES (?,?,'out','dues_reminder',?,'simulated',?)", (p["id"], "91" + phone, f"Dues msg {br}", _now()))
        db.execute("INSERT INTO feedback(patient_id,appointment_id,score,comment,created_at) VALUES (?,?,5,?,?)",
                   (p["id"], out[br]["appt"], f"Feedback {br}", _now()))
    return out


# ---------------------------------------------------------------- S-02 / S-03 / BUG-003: branch isolation on actions

ACTIONS = [  # (role, path template, form, record key, check that nothing changed)
    ("billing", "/billing/{bill}/payment", {"amount": "100", "mode": "Cash"},
     lambda ids: db.scalar("SELECT paid FROM bills WHERE id=?", (ids["bill"],)) == 0),
    ("billing", "/billing/{bill}/remind", {},
     lambda ids: db.scalar("SELECT COUNT(*) FROM dues_reminders WHERE bill_id=?", (ids["bill"],)) == 0),
    ("billing", "/billing/orders/{order}/add", {},
     lambda ids: db.scalar("SELECT bill_id FROM orders WHERE id=?", (ids["order"],)) is None),
    ("billing", "/claims/{claim}/stage", {"stage": "Denied"},
     lambda ids: db.scalar("SELECT stage FROM claims WHERE id=?", (ids["claim"],)) == "PreAuthRequested"),
    ("frontdesk", "/leads/{lead}/status", {"status": "Lost"},
     lambda ids: db.scalar("SELECT status FROM leads WHERE id=?", (ids["lead"],)) == "New"),
    ("frontdesk", "/tasks/{task}/done", {},
     lambda ids: db.scalar("SELECT status FROM tasks WHERE id=?", (ids["task"],)) == "Open"),
    ("frontdesk", "/appointments/{appt}/status", {"status": "Cancelled"},
     lambda ids: db.scalar("SELECT status FROM appointments WHERE id=?", (ids["appt"],)) == "Booked"),
]


@pytest.mark.parametrize("role,path,form,unchanged", ACTIONS, ids=[a[1] for a in ACTIONS])
def test_branch_user_gets_404_on_other_branch_record(client, two_branches, role, path, form, unchanged):
    login(client, "userb", role=role, branch="B")
    token = csrf_of(client, "/tasks")
    r = client.post(path.format(**two_branches["A"]), data={"csrf": token, **form}, follow_redirects=False)
    assert r.status_code == 404
    assert "could not find" in r.text
    assert unchanged(two_branches["A"])
    # Same answer for an id that doesn't exist at all, so ids can't be probed.
    missing = client.post(re.sub(r"\{\w+\}", "99999", path), data={"csrf": token, **form}, follow_redirects=False)
    assert missing.status_code == 404


@pytest.mark.parametrize("role,path,form,unchanged", ACTIONS, ids=[a[1] for a in ACTIONS])
def test_branch_user_can_act_on_own_branch(client, two_branches, role, path, form, unchanged):
    login(client, "userb", role=role, branch="B")
    token = csrf_of(client, "/tasks")
    r = client.post(path.format(**two_branches["B"]), data={"csrf": token, **form}, follow_redirects=False)
    assert r.status_code == 303
    assert not unchanged(two_branches["B"])


def test_unrouted_task_is_shared_by_every_branch(client, fresh_db):
    tid = db.execute("INSERT INTO tasks(kind,title,branch_id,created_at) VALUES ('followup_call','URGENT: possible emergency',NULL,?)",
                     (_now(),))
    login(client, "deskb", role="frontdesk", branch="B")
    assert "URGENT: possible emergency" in client.get("/tasks").text
    client.post(f"/tasks/{tid}/done", data={"csrf": csrf_of(client, "/tasks")})
    assert db.scalar("SELECT status FROM tasks WHERE id=?", (tid,)) == "Done"


# ---------------------------------------------------------------- S-12: patient profile

def test_patient_profile_shows_only_own_branch_records(client, two_branches):
    # The branch-A patient also visited branch B: B staff see only the B visit, bill and feedback.
    pa = two_branches["A"]["patient"]
    doc_b = db.scalar("SELECT id FROM doctors WHERE branch_id='B'")
    appt_b = db.execute("INSERT INTO appointments(patient_id,doctor_id,branch_id,starts_at,status,token_no,created_at)"
                        " VALUES (?,?,'B','2030-02-01 11:00:00','Visited',7,?)", (pa, doc_b, _now()))
    bill_b = billing.create_bill(pa, "B", [("X-ray at B", 700)])
    db.execute("INSERT INTO feedback(patient_id,appointment_id,score,comment,created_at) VALUES (?,?,4,'Feedback at B',?)",
               (pa, appt_b, _now()))
    login(client, "docb", role="doctor", branch="B")
    page = client.get(f"/patients/{pa}").text
    assert "Patient A" in page                                   # demographics are shared
    assert db.scalar("SELECT bill_no FROM bills WHERE id=?", (bill_b,)) in page
    assert db.scalar("SELECT bill_no FROM bills WHERE id=?", (two_branches["A"]["bill"],)) not in page
    assert "Feedback at B" in page and "Feedback A" not in page
    assert db.one("SELECT * FROM audit_log WHERE action='view' AND entity='patient' AND entity_id=?", (pa,))


def test_unbound_user_sees_every_branch_on_profile(client, two_branches):
    pa = two_branches["A"]["patient"]
    billing.create_bill(pa, "B", [("X-ray at B", 700)])
    login(client)
    page = client.get(f"/patients/{pa}").text
    assert page.count("Patient A") >= 1 and "Dues msg A" in page and "Feedback A" in page


# ---------------------------------------------------------------- S-13 / BUG-004: messages

def test_messages_scoped_to_branch_and_owner_report_admin_only(client, two_branches, monkeypatch):
    db.execute("INSERT INTO messages(to_phone,direction,template,body,status,created_at)"
               " VALUES ('919800000001','out','owner_daily_report','Revenue report body','simulated',?)", (_now(),))
    db.execute("INSERT INTO messages(patient_id,to_phone,direction,template,body,status,created_at)"
               " VALUES (?,'919822222222','out','patient_otp','123456 is your code','simulated',?)",
               (two_branches["B"]["patient"], _now()))
    login(client, "deskb", role="frontdesk", branch="B")
    page = client.get("/messages").text
    assert "Patient B" in page and "Patient A" not in page
    assert "Revenue report body" not in page and "123456" not in page
    # Asking for the other branch's thread by phone shows nothing from it.
    page = client.get("/messages?phone=919811111111").text
    assert "Dues msg A" not in page

    admin = TestClient(main.app)
    login(admin, "boss")
    page = admin.get("/messages?phone=919800000001").text
    assert "Revenue report body" in page and "Patient A" in page


def test_lead_conversation_visible_to_its_branch(client, fresh_db):
    db.execute("INSERT INTO leads(name,phone,source,branch_id,created_at,updated_at) VALUES ('Enq B','919833333333','WhatsApp','B',?,?)",
               (_now(), _now()))
    db.execute("INSERT INTO messages(to_phone,direction,template,body,status,created_at)"
               " VALUES ('919833333333','in','inbound','Need ortho appointment','received',?)", (_now(),))
    login(client, "deskb", role="frontdesk", branch="B")
    assert "Need ortho appointment" in client.get("/messages").text
    other = TestClient(main.app)
    login(other, "deska", role="frontdesk", branch="A")
    assert "Need ortho appointment" not in other.get("/messages").text


# ---------------------------------------------------------------- S-07 / S-21: login throttling

def test_login_locked_after_five_failures_per_user_and_ip(client, fresh_db):
    auth.create_user("admin", "Admin", "secret-pass-1", "admin")
    for _ in range(auth.LOGIN_MAX_FAILURES):
        assert client.post("/login", data={"username": "admin", "password": "nope"}).status_code == 401
    r = client.post("/login", data={"username": "admin", "password": "secret-pass-1"}, follow_redirects=False)
    assert r.status_code == 429 and "wait 15 minutes" in r.text
    assert db.one("SELECT * FROM audit_log WHERE action='login_throttled'")
    # The window passes: the right password works again and clears the counter.
    db.execute("UPDATE rate_events SET created_at = '2000-01-01 00:00:00'")
    r = client.post("/login", data={"username": "admin", "password": "secret-pass-1"}, follow_redirects=False)
    assert r.status_code == 303


def test_login_failures_for_unknown_user_are_counted_too(client, fresh_db):
    for _ in range(auth.LOGIN_MAX_FAILURES):
        client.post("/login", data={"username": "ghost", "password": "x"})
    assert client.post("/login", data={"username": "ghost", "password": "x"}).status_code == 429


# ---------------------------------------------------------------- S-09: Secure cookie

def test_staff_cookie_secure_only_on_https(fresh_db, monkeypatch):
    auth.create_user("admin", "Admin", "secret-pass-1", "admin")
    plain = TestClient(main.app)
    r = plain.post("/login", data={"username": "admin", "password": "secret-pass-1"},
                   headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
    assert "secure" not in r.headers["set-cookie"].lower()      # header not trusted without TT_BEHIND_PROXY
    monkeypatch.setenv("TT_BEHIND_PROXY", "1")
    r = plain.post("/login", data={"username": "admin", "password": "secret-pass-1"},
                   headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
    assert "secure" in r.headers["set-cookie"].lower()
    monkeypatch.delenv("TT_BEHIND_PROXY")
    r = TestClient(main.app, base_url="https://testserver").post(
        "/login", data={"username": "admin", "password": "secret-pass-1"}, follow_redirects=False)
    assert "secure" in r.headers["set-cookie"].lower()


# ---------------------------------------------------------------- S-10: server-side session end

def _replay(cookie: str):
    c = TestClient(main.app)
    c.cookies.set(auth.COOKIE, cookie)
    return c.get("/leads", follow_redirects=False)


def test_logout_ends_copied_session(client, fresh_db):
    login(client)
    cookie = client.cookies.get(auth.COOKIE)
    assert _replay(cookie).status_code == 200
    client.post("/logout", data={"csrf": csrf_of(client)})
    assert _replay(cookie).status_code == 303


def test_password_reset_and_deactivate_from_settings_end_sessions(client, fresh_db):
    desk = TestClient(main.app)
    login(desk, "desk", role="frontdesk")
    cookie = desk.cookies.get(auth.COOKIE)
    login(client)
    uid = db.scalar("SELECT id FROM users WHERE username='desk'")
    token = csrf_of(client, "/settings")
    r = client.post(f"/settings/users/{uid}/password", data={"csrf": token, "password": "brand-new-pass"}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert _replay(cookie).status_code == 303
    assert auth.authenticate("desk", "brand-new-pass")
    assert db.one("SELECT * FROM audit_log WHERE action='password_reset' AND entity_id=?", (uid,))

    desk2 = TestClient(main.app)
    desk2.post("/login", data={"username": "desk", "password": "brand-new-pass"})
    cookie = desk2.cookies.get(auth.COOKIE)
    client.post(f"/settings/users/{uid}/active", data={"csrf": token, "active": "0"})
    assert _replay(cookie).status_code == 303
    r = TestClient(main.app).post("/login", data={"username": "desk", "password": "brand-new-pass"}, follow_redirects=False)
    assert r.status_code == 401
    assert db.one("SELECT * FROM audit_log WHERE action='deactivate' AND entity_id=?", (uid,))
    client.post(f"/settings/users/{uid}/active", data={"csrf": token, "active": "1"})
    assert auth.authenticate("desk", "brand-new-pass")


def test_user_admin_actions_are_admin_only_and_no_self_lockout(client, fresh_db):
    login(client)
    me = db.scalar("SELECT id FROM users WHERE username='admin'")
    r = client.post(f"/settings/users/{me}/active", data={"csrf": csrf_of(client, "/settings"), "active": "0"}, follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert db.scalar("SELECT active FROM users WHERE id=?", (me,)) == 1
    desk = TestClient(main.app)
    login(desk, "desk", role="frontdesk")
    r = desk.post(f"/settings/users/{me}/password", data={"csrf": csrf_of(desk), "password": "hijacked-pass"})
    assert r.status_code == 403
    assert not auth.authenticate("admin", "hijacked-pass")


def test_cli_reset_password_and_deactivate(fresh_db, tmp_path):
    auth.create_user("desk", "Desk", "old-pass-123", "frontdesk")
    env = {"TT_DB_PATH": db._db_path, "TT_NEW_PASSWORD": "new-pass-456", "TT_SCHEDULER": "off", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-m", "app.auth", "reset-password", "desk"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert auth.authenticate("desk", "new-pass-456")
    r = subprocess.run([sys.executable, "-m", "app.auth", "deactivate", "desk"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert auth.authenticate("desk", "new-pass-456") is None
    r = subprocess.run([sys.executable, "-m", "app.auth", "deactivate", "nobody"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 1


# ---------------------------------------------------------------- owner role

def test_owner_sees_dashboard_and_read_only_money_screens(client, two_branches):
    login(client, "owner", role="owner")
    assert client.get("/", follow_redirects=False).status_code == 200
    billing_page = client.get("/billing")
    assert billing_page.status_code == 200 and "Record payment" not in billing_page.text
    assert "Send reminder now" not in billing_page.text and "Add to bill" not in billing_page.text
    claims = client.get("/claims")
    assert claims.status_code == 200 and "/stage" not in claims.text
    for path in ("/settings", "/import", "/audit", "/messages", "/tasks"):
        assert client.get(path).status_code == 403, path
    token = re.search(r'name="csrf" value="([^"]+)"', billing_page.text).group(1)  # the logout form
    r = client.post(f"/billing/{two_branches['A']['bill']}/payment", data={"csrf": token, "amount": "100", "mode": "Cash"})
    assert r.status_code == 403
    assert db.scalar("SELECT paid FROM bills WHERE id=?", (two_branches["A"]["bill"],)) == 0
    r = client.post("/settings/users", data={"csrf": token, "username": "x", "full_name": "X", "password": "longpass1", "role": "admin"})
    assert r.status_code == 403


# ---------------------------------------------------------------- migration of an older database

OLD_USERS = """CREATE TABLE users (
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','frontdesk','billing','doctor')),
  branch_id TEXT REFERENCES branches(id), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE patients (id INTEGER PRIMARY KEY, uid TEXT UNIQUE, name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE,
  age INTEGER, gender TEXT, abha_id TEXT, language TEXT NOT NULL DEFAULT 'en',
  consent_messages INTEGER NOT NULL DEFAULT 0, consent_at TEXT, created_at TEXT NOT NULL);
INSERT INTO users(username, full_name, password_hash, role, created_at) VALUES ('old', 'Old Admin', 'x', 'admin', '2026-01-01 00:00:00');
"""


def test_init_db_migrates_old_database_idempotently(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript(OLD_USERS)
    conn.close()
    db.set_path(path)
    db.init_db()
    db.init_db()  # second run changes nothing
    cols = [r["name"] for r in db.query("PRAGMA table_info(users)")]
    assert "session_version" in cols
    assert "session_version" in [r["name"] for r in db.query("PRAGMA table_info(patients)")]
    assert db.one("SELECT username, role, session_version FROM users") == {"username": "old", "role": "admin", "session_version": 0}
    assert "'owner'" in db.scalar("SELECT sql FROM sqlite_master WHERE name='users'")
    auth.create_user("boss", "Owner", "owner-pass-1", "owner")
    assert db.scalar("SELECT role FROM users WHERE username='boss'") == "owner"


# ---------------------------------------------------------------- S-11 / S-18 / S-19: headers and docs

def test_security_headers_on_pages(client, fresh_db):
    r = client.get("/login")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "same-origin"
    assert "camera=()" in h["permissions-policy"]
    csp = h["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "script-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert h["cache-control"] == "no-store"
    assert "strict-transport-security" not in h
    https = TestClient(main.app, base_url="https://testserver").get("/login")
    assert "max-age=" in https.headers["strict-transport-security"]
    static = client.get("/static/style.css")
    assert static.headers["x-content-type-options"] == "nosniff" and static.headers.get("cache-control") != "no-store"


def test_templates_have_no_inline_scripts_or_handlers():
    """The CSP allows only same-origin scripts, so templates must not use inline JS."""
    for f in (ROOT / "app" / "templates").rglob("*.html"):
        html = f.read_text()
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), f"inline <script> in {f.name}"
        assert not re.search(r"\son[a-z]+\s*=", html), f"inline event handler in {f.name}"
        assert "javascript:" not in html, f"javascript: URL in {f.name}"


def test_api_docs_hidden(client, fresh_db):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_non_ascii_api_key_gives_401_not_500(client, fresh_db):
    r = client.get("/api/dashboard", headers={"X-API-Key": "ключ".encode()})
    assert r.status_code == 401


# ---------------------------------------------------------------- S-14: upload limit, branch on import

def test_csv_upload_over_5mb_rejected(client, fresh_db):
    login(client)
    token = csrf_of(client, "/import")
    big = b"name,phone,age,gender,consent\n" + b"x" * (5 * 1024 * 1024 + 10)
    r = client.post("/import", data={"csrf": token, "kind": "patients"}, files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413 and "larger than 5 MB" in r.text
    assert db.scalar("SELECT COUNT(*) FROM patients") == 0


def test_csv_missing_columns_is_a_friendly_error(client, fresh_db):
    login(client)
    r = client.post("/import", data={"csrf": csrf_of(client, "/import"), "kind": "patients"},
                    files={"file": ("p.csv", b"nom,tel\nA,1\n", "text/csv")})
    assert r.status_code == 400 and "missing columns" in r.text


def test_branch_bound_admin_imports_only_own_branch_bills(client, fresh_db):
    login(client, "admb", role="admin", branch="B")
    csv_text = ("bill_no,external_ref,phone,patient_name,branch_id,item,amount,paid,date\n"
                "X-1,,9876500001,Asha,A,Consult,500,0,2026-11-01\n"
                "X-2,,9876500002,Ravi,B,Consult,600,0,2026-11-01\n")
    r = client.post("/import", data={"csrf": csrf_of(client, "/import"), "kind": "bills"},
                    files={"file": ("b.csv", csv_text.encode(), "text/csv")})
    assert r.status_code == 200
    assert [b["bill_no"] for b in db.query("SELECT bill_no FROM bills")] == ["X-2"]
    assert "not your branch" in r.text


# ---------------------------------------------------------------- BUG-005 / BUG-006

def test_remind_on_paid_or_missing_bill_is_friendly(client, two_branches):
    bid = two_branches["A"]["bill"]
    billing.record_payment(bid, 1000, "Cash")
    login(client, "bill1", role="billing")
    token = csrf_of(client, "/billing")
    r = client.post(f"/billing/{bid}/remind", data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 303 and "err=" in r.headers["location"] and "fully%20paid" in r.headers["location"]
    r = client.post("/billing/424242/remind", data={"csrf": token})
    assert r.status_code == 404 and "could not find that bill" in r.text


def test_run_automations_message_is_plain_english(client, fresh_db):
    login(client)
    r = client.post("/settings/run-automations", data={"csrf": csrf_of(client, "/settings")}, follow_redirects=False)
    loc = r.headers["location"]
    assert "Automations%20ran" in loc
    assert "%7B" not in loc and "reminder_24h" not in loc       # no Python dicts
    text = automations.summary({"appointment_reminders": {"reminder_24h": 35, "reminder_2h": 4, "blocked": 4},
                                "dues_reminders": {"sent": 11, "blocked": 0, "call_tasks": 0},
                                "daily_owner_report": 74, "detect_unbilled": "off"})
    assert text == ("39 appointment reminders sent (4 blocked: no consent) · 11 dues reminders sent · "
                    "owner report sent · switched off: detect unbilled.")
