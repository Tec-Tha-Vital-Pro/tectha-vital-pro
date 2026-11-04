import pytest

from app import util
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, db, seed
from app.routes import api

H = {"X-API-Key": "test-key"}


@pytest.fixture()
def client(fresh_db):
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    return TestClient(app)


def test_health_needs_no_key(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True and "scheduler_running" in body


def test_auth_missing_wrong_and_disabled(client, monkeypatch):
    body = {"name": "A", "phone": "9845012345", "source": "Website form"}
    assert client.post("/api/leads", json=body).status_code == 401
    assert client.post("/api/leads", json=body, headers={"X-API-Key": "nope"}).status_code == 401
    monkeypatch.setattr(config, "settings", config.Settings(**{**config.settings.__dict__, "api_key": ""}))
    r = client.post("/api/leads", json=body, headers=H)
    assert r.status_code == 503 and "TT_API_KEY" in r.json()["detail"]


def test_lead_created(client):
    r = client.post("/api/leads", json={"name": "Priya", "phone": "99001 23456", "need": "Check-up", "source": "Facebook ad", "branch_id": "A"}, headers=H)
    assert r.status_code == 200
    lead = db.one("SELECT * FROM leads WHERE id = ?", (r.json()["id"],))
    assert lead["status"] == "New" and lead["phone"] == "919900123456"


def test_lead_validation(client):
    assert client.post("/api/leads", json={"name": "P", "phone": "123", "source": "X"}, headers=H).status_code == 400
    assert client.post("/api/leads", json={"name": "P", "phone": "9900123456", "source": "X", "branch_id": "Z"}, headers=H).status_code == 400
    assert client.post("/api/leads", json={"phone": "9900123456"}, headers=H).status_code == 422


def test_bill_payment_flow(client):
    r = client.post("/api/bills", json={"phone": "9845012345", "patient_name": "Ramesh", "branch_id": "B",
                                        "items": [{"description": "Consultation", "amount": 600}, {"description": "X-ray", "amount": 850}],
                                        "external_ref": "INV-9"}, headers=H)
    assert r.status_code == 200
    bill_no = r.json()["bill_no"]
    assert r.json()["total"] == 1450 and r.json()["patient_uid"] == "TT-000001"
    dup = client.post("/api/bills", json={"phone": "9845012345", "patient_name": "Ramesh", "branch_id": "B",
                                          "items": [{"description": "C", "amount": 1}], "external_ref": "INV-9"}, headers=H)
    assert dup.status_code == 400
    p = client.post("/api/payments", json={"bill_no": bill_no, "amount": 1000, "mode": "UPI"}, headers=H)
    assert p.json()["balance"] == 450
    assert client.post("/api/payments", json={"bill_no": bill_no, "amount": 451, "mode": "UPI"}, headers=H).status_code == 400
    assert client.post("/api/payments", json={"bill_no": "NOPE", "amount": 1, "mode": "UPI"}, headers=H).status_code == 404


def test_orders_and_claims(client):
    o = client.post("/api/orders", json={"phone": "9845012345", "patient_name": "R", "branch_id": "A", "dept": "Lab",
                                         "description": "CBC", "amount": 350}, headers=H)
    assert o.status_code == 200
    c = client.post("/api/claims", json={"phone": "9845012345", "patient_name": "R", "branch_id": "A",
                                         "insurer": "Star Health", "amount": 50000}, headers=H)
    cid = c.json()["id"]
    assert client.patch(f"/api/claims/{cid}", json={"stage": "PreAuthApproved"}, headers=H).status_code == 200
    assert client.patch(f"/api/claims/{cid}", json={"stage": "Paid"}, headers=H).status_code == 400
    assert client.patch("/api/claims/999", json={"stage": "Settled"}, headers=H).status_code == 404


def test_dashboard(client):
    r = client.get("/api/dashboard", headers=H)
    assert r.status_code == 200 and set(r.json()["kpis"]) >= {"opd", "billed", "collected", "dues", "no_show_pct"}
    assert client.get("/api/dashboard?branch=Z", headers=H).status_code == 400


def test_seed_builds_data_in_both_branches(fresh_db):
    fixed = util.now()
    summary = seed.seed(now=fixed)
    assert summary["patients"] >= 80 and summary["doctors"] == 6
    for br in ("A", "B"):
        assert db.scalar("SELECT COUNT(*) FROM bills WHERE branch_id = ?", (br,)) > 10
        assert db.scalar("SELECT COUNT(*) FROM leads WHERE branch_id = ?", (br,)) > 10
    assert db.scalar("SELECT COUNT(*) FROM orders WHERE bill_id IS NULL") == 3
    assert {r["stage"] for r in db.query("SELECT stage FROM claims")} == {"PreAuthRequested", "PreAuthApproved", "FinalSent", "Settled", "Denied"}
    assert db.scalar("SELECT COUNT(*) FROM appointments WHERE status IN ('Booked','Confirmed') AND reminder_2h_sent_at IS NULL"
                     " AND starts_at > datetime('now','+5 hours','+30 minutes')") > 0
    assert db.scalar("SELECT COUNT(*) FROM bills WHERE total > paid AND created_at < datetime('now','+5 hours','+30 minutes','-30 days')") >= 1
    # reproducible counts
    assert seed.seed(now=fixed) == summary
