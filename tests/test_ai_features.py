"""Pro next AI features: no-show risk, report explainers, draft replies, coding assistant, NEWS2, governance."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app import agents, auth, db, patients, util
from app.ai_features import coding, drafts, explainers, governance, news2, noshow
from app.routes import ai_features as aif_routes
from app.routes import command  # noqa: F401  (registers base.html globals)
from app.routes import ui

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
PW = "secret-pass-1"
NOW = util.now().replace(microsecond=0)


def make_app():
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(ui.router)
    app.include_router(aif_routes.router)
    aif_routes.install_nav()
    return app


@pytest.fixture()
def client(fresh_db):
    governance.ensure_registered()
    return TestClient(make_app())


def _csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _login(client, username="admin", role="admin", branch=None):
    auth.create_user(username, username.title(), PW, role, branch_id=branch)
    r = client.post("/login", data={"username": username, "password": PW}, follow_redirects=False)
    assert r.status_code == 303


def _patient(name="Asha Rao", phone="9812345601", consent=True):
    return patients.find_or_create(name, phone, consent=consent)


def _appt(pid, starts, status="Booked", created=None, branch="A", reminded=False):
    doc = db.scalar("SELECT id FROM doctors WHERE branch_id = ? LIMIT 1", (branch,))
    return db.execute(
        "INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, created_at, reminder_24h_sent_at)"
        " VALUES (?,?,?,?,?,?,?)", (pid, doc, branch, util.ts(starts), status, util.ts(created or starts - timedelta(days=1)),
                                    util.ts(starts - timedelta(hours=20)) if reminded else None))


def _bed(pid, branch="A"):
    wid = db.execute("INSERT INTO wards(branch_id, name) VALUES (?, 'General')", (branch,))
    return db.execute("INSERT INTO beds(ward_id, label, status, patient_id) VALUES (?, 'G1', 'Occupied', ?)", (wid, pid))


# ---------------------------------------------------------------- governance

def test_every_feature_is_registered_and_decisions_are_logged(client):
    keys = {r["key"] for r in db.query("SELECT key FROM model_registry")}
    assert set(governance.MODELS) <= keys
    governance.log_decision("news2", "news2_rcp", "acknowledged", "user:Nurse", output={"x": 1})
    assert db.scalar("SELECT COUNT(*) FROM ai_decisions WHERE feature='news2'") == 1
    with pytest.raises(ValueError):
        governance.log_decision("news2", "news2_rcp", "auto_sent", "x", output="")


# ---------------------------------------------------------------- no-show risk

def test_noshow_score_uses_history_and_unconfirmed_reminder_with_reasons(fresh_db):
    p = _patient()
    for d in (30, 20):
        _appt(p["id"], NOW - timedelta(days=d), status="NoShow")
    aid = _appt(p["id"], NOW + timedelta(hours=20), created=NOW - timedelta(days=20), reminded=True)
    row = db.one("SELECT * FROM appointments WHERE id = ?", (aid,))
    score, level, reasons = noshow.score_row(row, NOW)
    assert level == "high" and score >= noshow.HIGH
    assert any("missed 2" in r for r in reasons) and any("did not confirm" in r for r in reasons)
    joined = " ".join(reasons).lower()
    for sensitive in ("religion", "caste", "gender", "income"):
        assert sensitive not in joined


def test_noshow_low_risk_for_reliable_patient(fresh_db):
    p = _patient()
    for d in (40, 30, 20):
        _appt(p["id"], NOW - timedelta(days=d), status="Visited")
    aid = _appt(p["id"], (NOW + timedelta(days=1)).replace(hour=11), status="Confirmed")
    assert noshow.score_row(db.one("SELECT * FROM appointments WHERE id = ?", (aid,)), NOW)[1] == "low"


def test_overbooking_is_capped_and_only_suggested(fresh_db):
    assert noshow.overbook_suggestion([{"risk": 90}] * 10) == noshow.OVERBOOK_CAP
    p = _patient()
    for d in (30, 20):
        _appt(p["id"], NOW - timedelta(days=d), status="NoShow")
    _appt(p["id"], NOW + timedelta(hours=10), created=NOW - timedelta(days=20), reminded=True)
    found = agents.REGISTRY["noshow_risk"].run(NOW)
    calls = [f for f in found if f["key"].startswith("noshow:")]
    assert calls and calls[0]["action"]["type"] == "task" and calls[0]["action"]["kind"] == "followup_call"
    assert all(f["action"] is None for f in found if f["key"].startswith("overbook:"))


def test_appointments_page_shows_risk_pill(client):
    p = _patient()
    for d in (30, 20):
        _appt(p["id"], NOW - timedelta(days=d), status="NoShow")
    start = (NOW + timedelta(hours=3)) if (NOW + timedelta(hours=3)).date() == NOW.date() else NOW + timedelta(minutes=5)
    _appt(p["id"], start, created=NOW - timedelta(days=20), reminded=True)
    _login(client)
    html = client.get(f"/appointments?day={NOW.date().isoformat()}").text
    assert "no-show risk" in html and "rules-based decision support" in html


# ---------------------------------------------------------------- report explainers

def test_explainer_refuses_result_interpretation_and_needs_approval(fresh_db):
    with pytest.raises(ValueError):
        explainers.save("TSH", "en", "Your result is high, so you have thyroid disease.", "user:Dr")
    explainers.save("TSH", "en", "TSH is a hormone that controls the thyroid gland.", "user:Dr")
    assert explainers.for_patient("TSH", "en") is None            # draft: patients see nothing
    explainers.approve("TSH", "en", "user:Dr")
    text = explainers.for_patient("TSH", "hi")                     # falls back to approved English
    assert text.startswith("TSH is a hormone") and "discuss your result with your doctor" in text
    explainers.save("TSH", "en", "TSH tells the thyroid how much hormone to make.", "user:Dr")
    assert explainers.for_patient("TSH", "en") is None            # any edit needs approval again
    assert db.scalar("SELECT COUNT(*) FROM ai_decisions WHERE feature='report_explainer'") == 1


def test_explainers_page_roles(client):
    _login(client, "fd", "frontdesk")
    assert client.get("/explainers").status_code == 403


# ---------------------------------------------------------------- draft replies

def _conversation(phone="919812345602", text="I want to book an appointment for my mother"):
    db.execute("INSERT INTO messages(to_phone, direction, template, body, status, created_at) VALUES (?,?,?,?,?,?)",
               (phone, "in", "inbound", text, "received", util.ts(NOW)))
    return phone


def test_draft_is_never_sent_and_template_is_used_when_ai_off(fresh_db):
    phone = _conversation()
    before = db.scalar("SELECT COUNT(*) FROM messages WHERE direction='out'")
    d = drafts.propose(phone, "user:Front")
    assert d["model_key"] == "draft_reply_templates" and "which day and time" in d["draft"].lower()
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE direction='out'") == before


def test_emergency_draft_points_to_108(fresh_db):
    phone = _conversation(text="Papa ko seene mein dard hai")
    assert "108" in drafts.propose(phone, "user:Front")["draft"]


class FakeClient:
    """Stands in for the Anthropic client: returns a parsed object like messages.parse."""
    def __init__(self, parsed):
        self.beta = self
        self.messages = self
        self._parsed = parsed

    def parse(self, **kwargs):
        class R:
            stop_reason = "end_turn"
        r = R()
        r.parsed_output = self._parsed
        return r


def test_ai_draft_uses_claude_and_edit_is_logged(fresh_db):
    phone = _conversation()
    d = drafts.propose(phone, "user:Front", client=FakeClient(drafts.Draft(reply="Namaste! Which day suits you?",
                                                                            needs_human_check=False)))
    assert d["model_key"] == "draft_reply_claude"
    drafts.record_sent(d["id"], "Namaste! Which day suits your mother?", "user:Front")
    row = db.one("SELECT decision FROM ai_decisions WHERE feature='draft_reply' ORDER BY id DESC LIMIT 1")
    assert row["decision"] == "edited"


def test_draft_route_prefills_reply_box(client):
    phone = _conversation()
    _login(client)
    page = client.get(f"/messages?phone={phone}")
    r = client.post("/messages/draft", data={"csrf": _csrf(page.text), "phone": phone}, follow_redirects=False)
    assert r.status_code == 303 and "draft=" in r.headers["location"]
    html = client.get(r.headers["location"]).text
    assert "read and edit before you send" in html and 'name="draft_id"' in html


# ---------------------------------------------------------------- coding assistant

def _claim(branch="A"):
    p = _patient("Ravi Kumar", "9812345603")
    db.execute("INSERT INTO orders(patient_id, branch_id, dept, description, amount, created_at) VALUES (?,?,?,?,?,?)",
               (p["id"], branch, "Ward", "Admitted with dengue fever, platelet monitoring", 1200, util.ts(NOW)))
    return db.execute("INSERT INTO claims(patient_id, branch_id, insurer, amount, stage, stage_changed_at, created_at)"
                      " VALUES (?,?,?,?,?,?,?)", (p["id"], branch, "Star Health", 40000, "PreAuthRequested",
                                                  util.ts(NOW), util.ts(NOW)))


def test_coding_rules_quote_evidence_and_coder_decides(fresh_db):
    cid = _claim()
    r = coding.suggest(cid, "user:Coder")
    assert r["model_key"] == "coding_rules"
    item = next(i for i in r["items"] if i["code"] == "A97.9")
    assert "dengue" in item["evidence"].lower()
    assert coding.decide(r["id"], ["A97.9", "D69.6"], "user:Coder") == "Accepted"
    assert db.one("SELECT decision FROM ai_decisions WHERE feature='coding_assistant' ORDER BY id DESC LIMIT 1")["decision"] == "edited"
    with pytest.raises(ValueError):
        coding.decide(r["id"], ["A97.9"], "user:Coder")


def test_ai_coding_drops_suggestions_without_real_evidence(fresh_db):
    cid = _claim()
    fake = FakeClient(coding.Suggestions(items=[
        coding.Suggestion(system="ICD-10", code="A97.9", label="Dengue", evidence="Ward: Admitted with dengue fever, platelet monitoring"),
        coding.Suggestion(system="ICD-10", code="I21.9", label="Heart attack", evidence="Patient had a heart attack"),
    ]))
    r = coding.suggest(cid, "user:Coder", client=fake)
    assert [i["code"] for i in r["items"]] == ["A97.9"]


def test_claims_branch_isolation_for_coding(client):
    cid = _claim(branch="B")
    _login(client, "billa", "billing", branch="A")
    page = client.get("/claims")
    r = client.post(f"/claims/{cid}/codes/suggest", data={"csrf": _csrf(page.text)}, follow_redirects=False)
    assert r.status_code == 404


def test_claims_page_renders_proposed_codes_with_evidence(client):
    cid = _claim(branch="A")
    coding.suggest(cid, "user:Coder")
    _login(client, "billb", "billing", branch="A")
    page = client.get("/claims")
    assert page.status_code == 200
    assert "A97.9" in page.text and "decision support" in page.text and f"/claims/codes/" in page.text


# ---------------------------------------------------------------- NEWS2

def test_news2_published_scoring():
    assert news2.score(resp_rate=16, spo2=97, on_oxygen=False, systolic_bp=124, pulse=78, consciousness="A",
                       temperature=36.8)[0] == 0
    total, three, parts = news2.score(resp_rate=25, spo2=91, on_oxygen=True, systolic_bp=90, pulse=131,
                                      consciousness="V", temperature=35.0)
    assert total == 3 + 3 + 2 + 3 + 3 + 3 + 3 and three
    assert news2.score(resp_rate=21, spo2=95, on_oxygen=False, systolic_bp=105, pulse=95, consciousness="A",
                       temperature=38.5)[0] == 2 + 1 + 0 + 1 + 1 + 0 + 1


def test_news2_alert_levels_rise_and_escalation(fresh_db):
    p = _patient()
    stable = dict(resp_rate=16, spo2=97, on_oxygen=False, systolic_bp=124, pulse=78, consciousness="A", temperature=36.8)
    assert news2.record(p["id"], "A", stable, "user:Nurse", now=NOW - timedelta(hours=2))["alert"] is None
    rise = dict(stable, resp_rate=21, pulse=95)             # 2 + 1 = 3, a rise of 3
    r = news2.record(p["id"], "A", rise, "user:Nurse", now=NOW - timedelta(hours=1))
    assert r["alert"]["level"] == "rise"
    emerg = dict(stable, resp_rate=26, spo2=91, systolic_bp=95, pulse=120)
    r = news2.record(p["id"], "A", emerg, "user:Nurse", now=NOW - timedelta(minutes=30))
    assert r["alert"]["level"] == "emergency"
    assert news2.escalate_overdue(NOW) == {"escalated": 1}
    assert news2.escalate_overdue(NOW) == {"escalated": 0}
    news2.acknowledge(r["alert"]["id"], "user:Dr")
    assert db.scalar("SELECT status FROM news2_alerts WHERE id = ?", (r["alert"]["id"],)) == "Acknowledged"


def test_news2_rejects_implausible_values_and_bad_thresholds(fresh_db):
    p = _patient()
    with pytest.raises(ValueError):
        news2.record(p["id"], "A", dict(resp_rate=16, spo2=97, systolic_bp=124, pulse=78, consciousness="A",
                                        temperature=98.6), "user:Nurse")
    with pytest.raises(ValueError):
        news2.set_thresholds({"news2_urgent": "8", "news2_emergency": "7", "news2_rise": "2",
                              "news2_escalate_minutes": "15"}, "user:Admin")


def test_vitals_screen_records_and_is_branch_scoped(client):
    pa = _patient()
    _bed(pa["id"], "A")
    pb = _patient("Kiran", "9812345609")
    _bed(pb["id"], "B")
    _login(client, "nurse_a", "nurse", branch="A")
    page = client.get("/vitals")
    assert "rules-based published score, not a diagnosis" in page.text and "Kiran" not in page.text
    data = {"csrf": _csrf(page.text), "resp_rate": "26", "spo2": "91", "systolic_bp": "95", "pulse": "120",
            "consciousness": "A", "temperature": "37"}
    r = client.post("/vitals", data={**data, "patient_id": str(pa["id"])}, follow_redirects=False)
    assert r.status_code == 303
    assert db.scalar("SELECT COUNT(*) FROM news2_alerts WHERE patient_id = ?", (pa["id"],)) == 1
    r = client.post("/vitals", data={**data, "patient_id": str(pb["id"])}, follow_redirects=False)
    assert r.status_code == 404


def test_nav_has_new_screens_and_lab_home():
    aif_routes.install_nav()
    hrefs = [n[0] for n in ui.NAV]
    assert "/vitals" in hrefs and "/explainers" in hrefs
    assert ui.HOME["lab"] == "/diagnostics" and ui.HOME["pharmacy"] == "/diagnostics"
