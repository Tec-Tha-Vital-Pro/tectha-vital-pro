"""AI Labs: agents raise findings; only an admin's Accept runs the safe action; everything is audited."""
import json
import random
import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app import agents, auth, billing, db, patients, util
from app.agents import actions, seed_pro
from app.routes import ai_labs, ui
from app.routes import command  # noqa: F401  (registers base.html globals)
from tests.flash_util import flash

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
NOW = util.now()


@pytest.fixture()
def client(fresh_db):
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(ui.router)
    app.include_router(ai_labs.router)
    return TestClient(app)


def _login(client, role="admin", branch=None, name=None):
    name = name or role
    auth.create_user(name, name.title(), "secret-pass-1", role, branch)
    client.post("/login", data={"username": name, "password": "secret-pass-1"})
    return client


def _csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _unbilled(branch="A", amount=1850):
    p = patients.find_or_create("Gopal Rao", "9876500001", consent=True)
    return billing.create_order(p["id"], branch, "Lab", "CBC + LFT", amount, created_at=NOW - timedelta(hours=5), actor="t")


def test_revenue_agent_finds_unbilled_and_accept_bills_it(client):
    oid = _unbilled()
    r = agents.run_agent("revenue_loss", NOW)
    assert r["new"] == 1
    f = db.one("SELECT * FROM findings WHERE agent='revenue_loss'")
    assert json.loads(f["action"]) == {"type": "add_order_to_bill", "order_id": oid}
    assert agents.run_agent("revenue_loss", NOW)["new"] == 0                 # idempotent
    _login(client)
    page = client.get("/ai-labs")
    assert "Not billed" in page.text
    r = client.post(f"/ai-labs/findings/{f['id']}/accept", data={"csrf": _csrf(page.text)}, follow_redirects=False)
    assert "Added to bill" in flash(r.headers["location"])
    assert db.scalar("SELECT bill_id FROM orders WHERE id = ?", (oid,)) is not None
    assert db.one("SELECT * FROM audit_log WHERE action='finding_accepted'")
    assert agents.run_agent("revenue_loss", NOW)["found"] == 0


def test_resolved_findings_close_themselves(fresh_db):
    oid = _unbilled()
    agents.run_agent("revenue_loss", NOW)
    billing.add_order_to_bill(oid, actor="t")
    assert agents.run_agent("revenue_loss", NOW)["resolved"] == 1
    assert db.scalar("SELECT decision_note FROM findings") == "Resolved on its own"


def test_dismiss_needs_reason_and_owner_cannot_decide(client):
    _unbilled()
    agents.run_agent("revenue_loss", NOW)
    fid = db.scalar("SELECT id FROM findings")
    with pytest.raises(ValueError):
        actions.dismiss(fid, "user:x", "")
    _login(client, "owner")
    page = client.get("/ai-labs")
    assert page.status_code == 200 and "An admin decides" in page.text
    assert client.post(f"/ai-labs/findings/{fid}/accept", data={"csrf": _csrf(page.text)}).status_code == 403


def test_branch_admin_sees_only_own_branch(client):
    _unbilled("B")
    agents.run_agent("revenue_loss", NOW)
    fid = db.scalar("SELECT id FROM findings")
    _login(client, "admin", branch="A", name="adminA")
    page = client.get("/ai-labs")
    assert "Not billed" not in page.text
    assert client.post(f"/ai-labs/findings/{fid}/accept", data={"csrf": _csrf(page.text)}).status_code == 404


def test_all_agents_on_demo_data_and_stock_transfer(fresh_db):
    from app import seed
    seed.seed(NOW)
    results = {n: agents.run_agent(n, NOW) for n in agents.REGISTRY}
    for name in ("revenue_loss", "claims_docs", "followup_churn", "stock_expiry"):
        assert results[name]["found"] > 0, name
    f = db.one("SELECT * FROM findings WHERE agent='stock_expiry' AND action IS NOT NULL")
    a = json.loads(f["action"])
    before = db.scalar("SELECT qty FROM stock_batches WHERE id = ?", (a["batch_id"],))
    done = actions.accept(f["id"], "user:admin")
    assert "Moved" in done
    assert db.scalar("SELECT qty FROM stock_batches WHERE id = ?", (a["batch_id"],)) == before - a["qty"]
    assert db.scalar("SELECT COUNT(*) FROM stock_moves") == 1
    c = db.one("SELECT * FROM findings WHERE agent='claims_docs'")
    assert "Task created" in actions.accept(c["id"], "user:admin")


def test_agent_switch_and_scheduler(fresh_db):
    agents.set_enabled("revenue_loss", False, "user:admin")
    _unbilled()
    out = agents.run_due(NOW)
    assert "revenue_loss" not in out and "claims_docs" in out
    agents.set_enabled("owner_briefing", False, "user:admin")
    from app import automations
    assert automations.is_enabled("daily_owner_report") is False


def test_ai_summary_rejects_invented_numbers(fresh_db):
    _unbilled()
    agents.run_agent("revenue_loss", NOW)
    fid = db.scalar("SELECT id FROM findings")

    class Fake:
        pass
    from app.ai import client as ai
    for text, ok in [("CBC + LFT worth ₹1,850 was not billed.", True), ("₹9,999 was lost.", False)]:
        db.execute("UPDATE findings SET ai_summary = NULL")
        orig = ai.structured
        ai.structured = lambda **kw: actions.FindingSummary(summary=text)
        try:
            if ok:
                assert actions.summarize(fid, client=Fake()) == text
            else:
                with pytest.raises(ai.AIError):
                    actions.summarize(fid, client=Fake())
        finally:
            ai.structured = orig
