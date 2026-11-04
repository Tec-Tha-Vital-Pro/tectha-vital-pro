"""Pro: Diagnostics & Pharmacy, critical call-outs, reflex rules, Command Centre and Notifications."""
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app import auth, db, diagnostics, notify, patients, util
from app.routes import command, ui
from app.routes import diagnostics as diag_routes
from tests.flash_util import flash

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
NOW = datetime(2026, 11, 4, 11, 0, 0)


def catalogue():
    for row in diagnostics.TESTS:
        db.execute("INSERT INTO lab_tests(code,name,specimen,unit,crit_low,crit_high,delta_pct,tat_hours,price) VALUES (?,?,?,?,?,?,?,?,?)", row)
    for row in diagnostics.RANGES:
        db.execute("INSERT INTO lab_ranges(test_code,sex,age_min,age_max,low,high) VALUES (?,?,?,?,?,?)", row)
    db.execute("INSERT INTO lab_reflex_rules(trigger_code,on_flag,add_code) VALUES ('TSH','H','FT4')")


def patient(name="Venkata Subba Rao", phone="9812300001", age=58, gender="M"):
    p = patients.find_or_create(name, phone, consent=True)
    db.execute("UPDATE patients SET age = ?, gender = ? WHERE id = ?", (age, gender, p["id"]))
    return patients.get(p["id"])


def received(p, code, branch="A", now=NOW):
    lid = diagnostics.create_lab_order(p["id"], branch, code, now=now)
    diagnostics.advance(lid, actor="t", now=now)
    diagnostics.advance(lid, actor="t", now=now)
    return lid


@pytest.fixture()
def lab(fresh_db):
    catalogue()
    return fresh_db


# ---------------------------------------------------------------- rules

def test_pipeline_collect_receive_assigns_sample_id(lab):
    p = patient()
    lid = diagnostics.create_lab_order(p["id"], "A", "K", now=NOW)
    assert diagnostics.advance(lid, actor="t", now=NOW) == "Collected"
    row = db.one("SELECT * FROM lab_orders WHERE id = ?", (lid,))
    assert row["sample_id"] == f"A-L261104-{lid:05d}"
    assert diagnostics.advance(lid, actor="t", now=NOW) == "Received"
    with pytest.raises(diagnostics.RuleError):
        diagnostics.advance(lid, actor="t", now=NOW)      # result must be entered, not skipped


def test_test_is_billed_as_an_unbilled_service(lab):
    p = patient()
    lid = diagnostics.create_lab_order(p["id"], "A", "TSH", now=NOW)
    oid = db.scalar("SELECT order_id FROM lab_orders WHERE id = ?", (lid,))
    o = db.one("SELECT * FROM orders WHERE id = ?", (oid,))
    assert o["dept"] == "Lab" and o["amount"] == 450 and o["bill_id"] is None


def test_normal_result_auto_verified(lab):
    p = patient()
    lid = received(p, "NA")
    out = diagnostics.enter_result(lid, 139, actor="t", now=NOW)
    assert out == {"flag": "N", "auto_validated": True, "reflex": []}
    assert db.scalar("SELECT status FROM lab_orders WHERE id = ?", (lid,)) == "Validated"


def test_abnormal_waits_for_pathologist(lab):
    p = patient()
    lid = received(p, "PCT")
    out = diagnostics.enter_result(lid, 4.2, actor="t", now=NOW)
    assert out["flag"] == "H" and not out["auto_validated"]
    assert db.scalar("SELECT status FROM lab_orders WHERE id = ?", (lid,)) == "Resulted"
    diagnostics.validate(lid, actor="user:dr", now=NOW)
    assert db.scalar("SELECT validated_by FROM lab_orders WHERE id = ?", (lid,)) == "user:dr"


def test_sex_specific_reference_range(lab):
    m, f = patient(), patient("Kavya Reddy", "9812300002", age=30, gender="F")
    assert diagnostics.reference_range("HCT", m) == (40, 50)
    assert diagnostics.reference_range("HCT", f) == (36, 44)
    child = patient("Little Arjun", "9812300003", age=8, gender="M")
    assert diagnostics.reference_range("HCT", child) == (35, 41)


def test_delta_check_blocks_auto_verify(lab):
    p = patient()
    first = received(p, "CREAT", now=NOW - timedelta(days=2))
    diagnostics.enter_result(first, 0.8, actor="t", now=NOW - timedelta(days=2))
    second = received(p, "CREAT")
    out = diagnostics.enter_result(second, 1.25, actor="t", now=NOW)   # still in range, but +56 %
    assert out["flag"] == "N" and not out["auto_validated"]
    assert db.scalar("SELECT delta_flag FROM lab_orders WHERE id = ?", (second,)) == 1


def test_critical_value_opens_callout_task_and_notification(lab):
    auth.create_user("drmenon", "Dr Menon", "secret-pass-1", "doctor", "A")
    auth.create_user("drb", "Dr B", "secret-pass-1", "doctor", "B")
    p = patient()
    lid = received(p, "K")
    out = diagnostics.enter_result(lid, 6.4, actor="t", now=NOW)
    assert out["flag"] == "HH"
    assert db.scalar("SELECT status FROM lab_callouts WHERE lab_order_id = ?", (lid,)) == "Open"
    t = db.one("SELECT * FROM tasks WHERE related_type = 'lab_order' AND related_id = ?", (lid,))
    assert t["title"].startswith("URGENT critical value: Serum potassium 6.4")
    dr_a = db.scalar("SELECT id FROM users WHERE username='drmenon'")
    dr_b = db.scalar("SELECT id FROM users WHERE username='drb'")
    assert notify.unread_count(dr_a) == 1 and notify.unread_count(dr_b) == 0    # only the ordering branch
    with pytest.raises(diagnostics.RuleError):
        diagnostics.validate(lid, actor="t", now=NOW)        # must be called out first
    with pytest.raises(diagnostics.RuleError):
        diagnostics.call_out(lid, called_to="Dr Menon", read_back=False, actor="t", now=NOW)
    diagnostics.call_out(lid, called_to="Dr Menon, ward 3", read_back=True, actor="user:lab", now=NOW)
    assert db.scalar("SELECT status FROM tasks WHERE id = ?", (t["id"],)) == "Done"
    diagnostics.validate(lid, actor="user:dr", now=NOW)


def test_uncalled_critical_escalates_after_15_minutes_once(lab):
    auth.create_user("boss", "Owner", "secret-pass-1", "owner")
    p = patient()
    lid = received(p, "K")
    diagnostics.enter_result(lid, 2.1, actor="t", now=NOW)
    assert diagnostics.escalate_callouts(NOW + timedelta(minutes=10)) == 0
    assert diagnostics.escalate_callouts(NOW + timedelta(minutes=16)) == 1
    assert diagnostics.escalate_callouts(NOW + timedelta(minutes=30)) == 0
    owner = db.scalar("SELECT id FROM users WHERE username='boss'")
    assert "Not called out in 15 min" in notify.recent(owner)[0]["title"]


def test_reflex_rule_adds_free_t4_once(lab):
    p = patient()
    lid = received(p, "TSH")
    out = diagnostics.enter_result(lid, 8.4, actor="t", now=NOW)
    assert out["reflex"] == ["FT4"]
    kid = db.one("SELECT * FROM lab_orders WHERE reflex_of = ?", (lid,))
    assert kid["test_code"] == "FT4" and kid["status"] == "Received"


def test_patient_sees_only_validated_results(lab):
    p = patient()
    lid = received(p, "PCT")
    oid = db.scalar("SELECT order_id FROM lab_orders WHERE id = ?", (lid,))
    assert diagnostics.patient_results(oid) == ("pending", [])
    diagnostics.enter_result(lid, 4.2, actor="t", now=NOW)
    assert diagnostics.patient_results(oid) == ("pending", [])
    diagnostics.validate(lid, actor="t", now=NOW)
    state, rows = diagnostics.patient_results(oid)
    assert state == "validated" and rows[0][:3] == ("Procalcitonin", "4.2", "ng/mL")


def test_obstetric_usg_requires_form_f(lab):
    p = patient("Meena Gupta", "9812300004", 27, "F")
    rid = diagnostics.create_rad_order(p["id"], "A", "USG", "Obstetric scan", util.ts(NOW), obstetric=True, now=NOW)
    with pytest.raises(diagnostics.RuleError, match="Form F"):
        diagnostics.advance_rad(rid, actor="t", now=NOW)
    assert diagnostics.advance_rad(rid, actor="t", form_f=True, now=NOW) == "Performed"
    with pytest.raises(diagnostics.RuleError):
        diagnostics.advance_rad(rid, actor="t", now=NOW)                  # report text required
    assert diagnostics.advance_rad(rid, actor="t", report_text="Single live intrauterine pregnancy.", now=NOW) == "Reported"
    cols = {c["name"] for c in db.query("PRAGMA table_info(rad_orders)")}
    assert not any("sex" in c or "gender" in c for c in cols)          # PCPNDT: no such field exists


def test_pharmacy_fefo_schedule_register_and_bill(lab):
    for code, name, sch, price in diagnostics.DRUGS:
        db.execute("INSERT INTO drugs(code,name,schedule,unit_price) VALUES (?,?,?,?)", (code, name, sch, price))
    db.execute("INSERT INTO drug_batches(drug_code,branch_id,batch_no,expiry,qty) VALUES ('AZI500','A','OLD','2026-11-01',50)")  # expired
    db.execute("INSERT INTO drug_batches(drug_code,branch_id,batch_no,expiry,qty) VALUES ('AZI500','A','SOON','2026-12-15',50)")
    db.execute("INSERT INTO drug_batches(drug_code,branch_id,batch_no,expiry,qty) VALUES ('AZI500','A','LATER','2027-09-01',50)")
    p = patient()
    rx = db.execute("INSERT INTO prescriptions(patient_id,branch_id,created_at) VALUES (?,?,?)", (p["id"], "A", util.ts(NOW)))
    db.execute("INSERT INTO prescription_items(prescription_id,drug_code,qty) VALUES (?, 'AZI500', 3)", (rx,))
    assert diagnostics.advance_rx(rx, actor="user:pharm", now=NOW) == "Dispensed"
    assert db.scalar("SELECT qty FROM drug_batches WHERE batch_no='SOON'") == 47       # first expiry, not expired
    reg = db.one("SELECT * FROM schedule_register")
    assert reg["schedule"] == "H1" and reg["batch_no"] == "SOON" and reg["dispensed_by"] == "user:pharm"
    assert diagnostics.advance_rx(rx, actor="user:pharm", now=NOW) == "Billed"
    bill = db.one("SELECT b.* FROM bills b JOIN prescriptions x ON x.bill_id = b.id WHERE x.id = ?", (rx,))
    assert bill["total"] == 66


def test_pharmacy_refuses_without_in_date_stock(lab):
    db.execute("INSERT INTO drugs(code,name,schedule,unit_price) VALUES ('ORS','ORS sachet','',18)")
    db.execute("INSERT INTO drug_batches(drug_code,branch_id,batch_no,expiry,qty) VALUES ('ORS','A','X','2026-10-01',100)")
    p = patient()
    rx = db.execute("INSERT INTO prescriptions(patient_id,branch_id,created_at) VALUES (?,?,?)", (p["id"], "A", util.ts(NOW)))
    db.execute("INSERT INTO prescription_items(prescription_id,drug_code,qty) VALUES (?, 'ORS', 2)", (rx,))
    with pytest.raises(diagnostics.RuleError, match="in-date stock"):
        diagnostics.advance_rx(rx, actor="t", now=NOW)


def test_notify_role_expansion_and_dedupe(lab):
    auth.create_user("a1", "Admin", "secret-pass-1", "admin")
    auth.create_user("b1", "Billing B", "secret-pass-1", "billing", "B")
    assert notify.notify(title="Claim past limit", link="/claims", role=["admin", "billing"], branch="A", source_key="k1") == 1
    assert notify.notify(title="Claim past limit", link="/claims", role=["admin", "billing"], branch="A", source_key="k1") == 0
    with pytest.raises(ValueError):
        notify.notify(title="x", link="https://evil.example", role="admin")


# ---------------------------------------------------------------- screens

def make_app() -> FastAPI:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(ui.router)
    app.include_router(diag_routes.router)
    app.include_router(command.router)
    return app


def login(client, username="admin", role="admin", branch=None):
    auth.create_user(username, username.title(), "secret-pass-1", role, branch)
    r = client.post("/login", data={"username": username, "password": "secret-pass-1"}, follow_redirects=False)
    assert r.status_code == 303
    return client


def csrf(client, path="/diagnostics"):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


@pytest.fixture()
def client(lab):
    return TestClient(make_app())


def test_lab_screen_order_result_callout_flow(client):
    login(client)
    tok = csrf(client)
    r = client.post("/diagnostics/lab/order", data={"csrf": tok, "name": "Gurpreet Kaur", "phone": "98123 00009",
                                                    "test_code": "K", "branch_id": "A"}, follow_redirects=False)
    assert r.status_code == 303 and "Test ordered" in flash(r.headers["location"])
    lid = db.scalar("SELECT id FROM lab_orders")
    for _ in range(2):
        client.post(f"/diagnostics/lab/{lid}/advance", data={"csrf": tok}, follow_redirects=False)
    r = client.post(f"/diagnostics/lab/{lid}/result", data={"csrf": tok, "value": "6.8"}, follow_redirects=False)
    assert "Critical value" in flash(r.headers["location"])
    page = client.get("/diagnostics?tab=lab").text
    assert "6.8 mmol/L" in page and "!!" in page and "Call out" in page and "Call-out needed" in page
    r = client.post(f"/diagnostics/lab/{lid}/callout", data={"csrf": tok, "called_to": "Dr Iyer"}, follow_redirects=False)
    assert "read the value back" in flash(r.headers["location"], "err")
    r = client.post(f"/diagnostics/lab/{lid}/callout", data={"csrf": tok, "called_to": "Dr Iyer", "read_back": "1"}, follow_redirects=False)
    assert "Call-out recorded" in flash(r.headers["location"])
    assert "Called out" in client.get("/diagnostics?tab=lab").text


def test_lab_post_needs_csrf(client):
    login(client)
    r = client.post("/diagnostics/lab/order", data={"name": "X", "phone": "9812300010", "test_code": "K"}, follow_redirects=False)
    assert r.status_code == 403


def test_branch_user_cannot_touch_other_branch_lab_order(client):
    p = patient()
    other = diagnostics.create_lab_order(p["id"], "B", "K", now=NOW)
    login(client, "fda", "frontdesk", "A")
    tok = csrf(client)
    r = client.post(f"/diagnostics/lab/{other}/advance", data={"csrf": tok}, follow_redirects=False)
    assert r.status_code == 404
    assert db.scalar("SELECT status FROM lab_orders WHERE id = ?", (other,)) == "Ordered"
    assert "Venkata" not in client.get("/diagnostics?tab=lab").text


def test_billing_role_cannot_validate(client):
    p = patient()
    lid = received(p, "PCT")
    diagnostics.enter_result(lid, 4.2, actor="t", now=NOW)
    login(client, "cash", "billing")
    tok = csrf(client, "/diagnostics?tab=rx")
    r = client.post(f"/diagnostics/lab/{lid}/validate", data={"csrf": tok}, follow_redirects=False)
    assert r.status_code == 403


def test_radiology_and_pharmacy_tabs_render(client):
    login(client)
    assert "Radiology schedule" in client.get("/diagnostics?tab=rad").text
    assert "Prescriptions queue" in client.get("/diagnostics?tab=rx").text


def test_command_centre_and_wall_mode(client):
    w = db.execute("INSERT INTO wards(branch_id,name) VALUES ('A','ICU')")
    db.execute("INSERT INTO beds(ward_id,label,status) VALUES (?,'I01','Occupied'),(?,'I02','Free')", (w, w))
    login(client)
    page = client.get("/command").text
    assert "Command Centre" in page and "Beds occupied" in page and "data-autorefresh" in page
    assert "wall-mode" in client.get("/command?wall=1").text


def test_command_centre_forbidden_for_frontdesk(client):
    login(client, "fd", "frontdesk")
    assert client.get("/command", follow_redirects=False).status_code == 403


def test_bell_shows_count_and_open_marks_read(client):
    login(client)
    uid = db.scalar("SELECT id FROM users WHERE username='admin'")
    notify.notify(title="Critical value: K 6.4", link="/diagnostics?tab=lab", user_ids=[uid], severity="critical")
    page = client.get("/diagnostics").text
    assert 'class="bell-count num">1<' in page
    nid = db.scalar("SELECT id FROM notifications")
    r = client.post(f"/notifications/{nid}/open", data={"csrf": csrf(client)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/diagnostics?tab=lab"
    assert notify.unread_count(uid) == 0


def test_cannot_open_someone_elses_notification(client):
    auth.create_user("other", "Other", "secret-pass-1", "admin")
    oid = db.scalar("SELECT id FROM users WHERE username='other'")
    notify.notify(title="Private", link="/claims", user_ids=[oid])
    login(client)
    nid = db.scalar("SELECT id FROM notifications")
    assert client.post(f"/notifications/{nid}/open", data={"csrf": csrf(client)}, follow_redirects=False).status_code == 404


def test_demo_card_and_strip_in_simulator_mode(client):
    login(client)
    page = client.get("/diagnostics").text
    assert "Demo build · synthetic data only" in page and "not for clinical use" in page


def test_navigation_lists_pro_screens(client):
    login(client)
    page = client.get("/diagnostics").text
    assert 'href="/command"' in page and 'href="/diagnostics"' in page


def test_seed_builds_diagnostics_demo(fresh_db):
    from app import seed
    out = seed.seed(NOW)
    assert out["lab_orders"] >= 12 and out["beds"] > 0
    assert db.scalar("SELECT COUNT(*) FROM lab_callouts WHERE status='Open'") == 1
    assert db.scalar("SELECT COUNT(*) FROM lab_callouts WHERE status='CalledOut'") == 1
    assert db.scalar("SELECT COUNT(*) FROM lab_orders WHERE reflex_of IS NOT NULL") == 1
    seed.seed(NOW)     # reseeding works (Pro tables are cleared before core tables)


def test_sweep_notifies_people_added_after_the_critical(lab):
    p = patient()
    lid = received(p, "K")
    diagnostics.enter_result(lid, 6.9, actor="t", now=NOW)
    auth.create_user("newdoc", "New Doc", "secret-pass-1", "doctor", "A")
    uid = db.scalar("SELECT id FROM users WHERE username='newdoc'")
    assert notify.unread_count(uid) == 0
    diagnostics.sweep(NOW + timedelta(minutes=1))
    diagnostics.sweep(NOW + timedelta(minutes=2))
    assert notify.unread_count(uid) == 1
