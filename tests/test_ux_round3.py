"""UX review round 3: blockers B1–B3 (server side), rename, and the majors fixed in this round."""
import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, db, patients, util
from app.routes import patient_app, ui
from tests.flash_util import flash
from tests.test_patient_app import _csrf, _login as patient_login
from tests.test_patient_app import STATIC, patient  # noqa: F401  (fixture)
from tests.test_ui import client, csrf_of, login  # noqa: F401  (fixture)


@pytest.fixture()
def pclient(fresh_db):
    from fastapi.staticfiles import StaticFiles
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(patient_app.router, prefix="/my")
    return TestClient(app)


def _bill(name="Asha Pillai", phone="9812345678", branch="A", total=5000, paid=0):
    from app import billing
    p = patients.find_or_create(name, phone, consent=True)
    bid = billing.create_bill(p["id"], branch, [("Consultation", total)])
    if paid:
        billing.record_payment(bid, paid, "Cash")
    return p, bid


# ---------------------------------------------------------------- B1

def test_booking_error_keeps_values_and_reopens_form(client):
    login(client)
    doc = db.scalar("SELECT id FROM doctors WHERE branch_id='B'")
    r = client.post("/appointments/book", data={"csrf": csrf_of(client, "/appointments"), "name": "Meena Joshi",
                                                "phone": "12345", "doctor_id": doc, "starts_at": "2030-01-10T11:30",
                                                "consent": "1"})
    assert r.status_code == 400
    assert 'value="Meena Joshi"' in r.text and 'value="12345"' in r.text and 'value="2030-01-10T11:30"' in r.text
    assert "data-open-on-load" in r.text and 'aria-describedby="a-phone-err"' in r.text
    assert "Enter a 10-digit mobile number" in r.text and "Not a valid" not in r.text
    assert 'pattern="[0-9 +]{10,15}"' in r.text and 'maxlength="15"' in r.text
    assert db.scalar("SELECT COUNT(*) FROM appointments") == 0


def test_enquiry_book_link_prefills_booking(client):
    login(client)
    page = client.get("/appointments?book=1&name=Ravi%20Kumar&phone=919876511111").text
    assert "data-open-on-load" in page and 'value="Ravi Kumar"' in page and 'value="9876511111"' in page


# ---------------------------------------------------------------- B2

def test_billing_search_finds_patient_and_opens_payment(client):
    p, bid = _bill()
    _bill("Gopal Rao", "9822222222", "A", 900)
    login(client, "cash", role="billing")
    for q in ("asha", p["uid"], "45678", db.scalar("SELECT bill_no FROM bills WHERE id=?", (bid,))):
        page = client.get(f"/billing?q={q}").text
        assert "Asha Pillai" in page and "Gopal Rao" not in page, q
        assert f'id="pay-{bid}" class="slide" aria-labelledby="pay-h-{bid}" data-open-on-load' in page
    assert 'action="/billing"' in client.get("/billing").text            # global search points billing at /billing
    client.post("/logout", data={"csrf": csrf_of(client, "/billing")})
    login(client, "boss", role="admin")
    assert 'id="b-q"' in client.get("/billing").text                    # admins (search goes to Patients) get a box on Billing


def test_payment_error_stays_in_dialog(client):
    _, bid = _bill(total=2000)
    login(client, "cash", role="billing")
    r = client.post(f"/billing/{bid}/payment", data={"csrf": csrf_of(client, "/billing"), "amount": "9999", "mode": "UPI"})
    assert r.status_code == 400 and "more than the balance" in r.text and f'pay-{bid}" class="slide"' in r.text
    assert "data-open-on-load" in r.text


# ---------------------------------------------------------------- B3 (markup) and toasts

def test_keyboard_users_get_a_save_button(client):
    login(client)
    now = util.ts(util.now())
    db.execute("INSERT INTO leads(name,phone,source,branch_id,created_at,updated_at) VALUES ('K','919811111111','Walk-in','A',?,?)", (now, now))
    page = client.get("/leads").text
    assert 'class="btn sm kbd-save" type="submit">Save' in page
    appts = client.get("/appointments").text
    assert "data-submit-on-blur" in appts and 'id="a-day" type="date" name="day" value="' in appts
    assert 'name="day" value="' in appts and "data-autosubmit>" not in appts.split('id="a-day"')[1][:80]


def test_crafted_toast_text_is_not_shown(client):
    login(client)
    page = client.get("/leads?err=Your%20account%20is%20blocked").text
    assert "Your account is blocked" not in page


def test_lead_status_change_offers_undo(client):
    login(client)
    now = util.ts(util.now())
    lid = db.execute("INSERT INTO leads(name,phone,source,branch_id,created_at,updated_at) VALUES ('Undo Me','919811111112','Walk-in','A',?,?)", (now, now))
    r = client.post(f"/leads/{lid}/status", data={"csrf": csrf_of(client), "status": "Lost"}, follow_redirects=False)
    page = client.get(r.headers["location"]).text
    assert f'action="/leads/{lid}/status" class="toast-undo"' in page and 'name="status" value="New"' in page


# ---------------------------------------------------------------- M2 / M3 staff

def test_booked_reads_not_confirmed_and_no_show_has_undo(client):
    p = patients.find_or_create("Lata Rao", "9833333333", consent=True)
    when = util.now().replace(hour=23, minute=0)
    aid = db.execute("INSERT INTO appointments(patient_id,doctor_id,branch_id,starts_at,status,token_no,created_at)"
                     " VALUES (?,1,'B',?,'Booked',4,?)", (p["id"], util.ts(when), util.ts(util.now())))
    login(client)
    page = client.get("/appointments").text
    assert "Not confirmed" in page and "B-</small>4" in page
    r = client.post(f"/appointments/{aid}/status", data={"csrf": csrf_of(client, "/appointments"), "status": "NoShow"},
                    follow_redirects=False)
    assert "No-show" in flash(r.headers["location"]) and "NoShow" not in flash(r.headers["location"])
    page = client.get(r.headers["location"]).text
    assert f'action="/appointments/{aid}/status" class="toast-undo"' in page and 'name="status" value="Booked"' in page


# ---------------------------------------------------------------- M6 / M7

def test_missed_call_task_has_tap_to_call(client):
    now = util.ts(util.now())
    db.execute("INSERT INTO tasks(kind,title,branch_id,status,due_at,created_at) VALUES ('missed_call','Call back +918085874951','A','Open',?,?)",
               (now, now))
    login(client)
    page = client.get("/tasks").text
    assert 'href="tel:+918085874951"' in page and "+91 80858 74951" in page and 'id="missed-calls"' in page


def test_staff_reply_rules(client):
    p = patients.find_or_create("Nisha Rao", "9844444444", consent=False)
    now = util.now()
    db.execute("INSERT INTO messages(patient_id,to_phone,direction,template,body,status,created_at) VALUES (?,?,'out','t','hi','simulated',?)",
               (p["id"], p["phone"], util.ts(now - timedelta(days=3))))
    login(client, "desk", role="frontdesk")
    tok = csrf_of(client, "/leads")
    # No consent and the patient has not written recently: blocked.
    r = client.post("/messages/reply", data={"csrf": tok, "phone": p["phone"], "text": "Hello"}, follow_redirects=False)
    assert "consent" in flash(r.headers["location"], "err")
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE template='staff_reply' AND status!='blocked_no_consent'") == 0
    # The patient writes in: a reply within 24 hours goes out.
    db.execute("INSERT INTO messages(patient_id,to_phone,direction,template,body,status,created_at) VALUES (?,?,'in','inbound','Is the doctor in?','received',?)",
               (p["id"], p["phone"], util.ts(now)))
    r = client.post("/messages/reply", data={"csrf": tok, "phone": p["phone"], "text": "Yes, till 1 pm."}, follow_redirects=False)
    assert flash(r.headers["location"]) == "Reply sent on WhatsApp."
    row = db.one("SELECT * FROM messages WHERE template='staff_reply' AND status='simulated'")
    assert row and row["body"] == "Yes, till 1 pm."
    assert db.scalar("SELECT actor FROM audit_log WHERE entity='message' AND entity_id=?", (row["id"],)).startswith("user:")
    # Unknown conversation or the owner's report thread: refused.
    assert client.post("/messages/reply", data={"csrf": tok, "phone": "919999999999", "text": "x"}).status_code == 404
    assert client.post("/messages/reply", data={"csrf": tok, "phone": config.settings.owner_phone, "text": "x"}).status_code == 404


# ---------------------------------------------------------------- M9 / M11 / M18

def test_claim_past_limit_from_time_in_stage(client):
    p = patients.find_or_create("Divya Singh", "9855555555", consent=True)
    old = util.ts(util.now() - timedelta(minutes=98))
    db.execute("INSERT INTO claims(patient_id,branch_id,insurer,amount,stage,stage_changed_at,created_at) VALUES (?,?,?,?,?,?,?)",
               (p["id"], "A", "HDFC ERGO", 185000, "PreAuthRequested", old, old))
    assert ui.claims_over_limit(None) == 1 and ui.claims_over_limit("B") == 0
    login(client)
    assert "Over the limit by 38 min" in client.get("/claims").text


def test_unknown_staff_url_is_a_friendly_page(fresh_db):
    from app.main import app
    with TestClient(app) as c:
        r = c.get("/nope")
        assert r.status_code == 404 and "Page not found" in r.text and "<main" in r.text
        assert c.get("/api/nope").headers["content-type"].startswith("application/json")
        r = c.get("/my/nope")
        assert r.status_code == 404 and "Page not found" in r.text


def test_product_name_everywhere(client):
    assert config.PRODUCT_NAME == "Tec Tha Vital" and config.PRODUCT_TAGLINE == "Hospital OS"
    m = json.loads(client.get("/manifest.webmanifest").text)
    assert m["name"] == "Tec Tha Vital · Hospital OS" and m["short_name"] == "Tec Tha Vital"
    login_page = client.get("/login").text
    assert "Tec Tha Vital" in login_page and "Hospital OS" in login_page
    assert "Care Connect" not in login_page and "Tec Tha HP" not in login_page
    assert "Tec Tha Vital" in client.get("/offline.html").text
    assert 'tectha-static-v2' in client.get("/sw.js").text


# ---------------------------------------------------------------- patient app: M3, M12, M13, M14

def test_patient_cancel_needs_confirmation(pclient, patient):  # noqa: F811
    patient_login(pclient)
    when = util.now() + timedelta(days=1)
    aid = db.execute("INSERT INTO appointments(patient_id,doctor_id,branch_id,starts_at,status,token_no,created_at) VALUES (?,1,'B',?,'Booked',3,?)",
                     (patient["id"], util.ts(when), util.ts(util.now())))
    home = pclient.get("/my/").text
    assert f'href="/my/appointments/{aid}/cancel?back=/my/"' in home and 'value="cancel"' not in home
    page = pclient.get(f"/my/appointments/{aid}/cancel?back=/my/").text
    assert "Keep my visit" in page and "Yes, cancel" in page and "Dr. S. Menon" in page
    assert db.scalar("SELECT status FROM appointments WHERE id=?", (aid,)) == "Booked"
    pclient.post(f"/my/appointments/{aid}/action", data={"csrf": _csrf(page), "action": "cancel", "back": "/my/"})
    assert db.scalar("SELECT status FROM appointments WHERE id=?", (aid,)) == "Cancelled"


def test_patient_hindi_toggle(pclient, patient):  # noqa: F811
    r = pclient.get("/my/lang/hi?next=/my/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/login"
    page = pclient.get("/my/login").text
    assert 'lang="hi"' in page and "WhatsApp पर कोड पाएं" in page
    assert pclient.get("/my/lang/hi?next=https://evil.example", follow_redirects=False).headers["location"] == "/my/"


def test_patient_bills_unpaid_first_with_pay_button(pclient, patient):  # noqa: F811
    from app import billing
    paid = billing.create_bill(patient["id"], "A", [("Old visit", 500)], created_at=util.ts(util.now() - timedelta(days=40)))
    billing.record_payment(paid, 500, "Cash")
    due = billing.create_bill(patient["id"], "A", [("Physio", 26300)], created_at=util.ts(util.now() - timedelta(days=60)))
    billing.create_bill(patient["id"], "A", [("Newest, paid", 300)])
    billing.record_payment(db.scalar("SELECT MAX(id) FROM bills"), 300, "UPI")
    patient_login(pclient)
    page = pclient.get("/my/bills").text
    assert page.index("₹26,300") < page.index("₹300") and f'href="/my/bills/{due}/pay"' in page and "to pay" in page


def test_patient_help_is_tappable(pclient, patient):  # noqa: F811
    db.set_setting("hospital_whatsapp", "919900011122")
    db.set_setting("front_desk_phone", "919900033344")
    patient_login(pclient)
    home = pclient.get("/my/").text
    assert 'href="https://wa.me/919900011122"' in home and 'href="tel:+919900033344"' in home


def test_nothing_is_indexed(fresh_db):
    from app.main import app
    with TestClient(app) as c:
        for path in ("/login", "/my/login"):
            r = c.get(path)
            assert r.headers["x-robots-tag"] == "noindex, nofollow"
            assert '<meta name="robots" content="noindex, nofollow">' in r.text
            assert '<meta name="description"' in r.text and "<title>" in r.text
        assert c.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"
        assert c.get("/api/health").headers["x-robots-tag"] == "noindex, nofollow"
