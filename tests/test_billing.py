from datetime import timedelta

import pytest

from app import billing, db, patients, util


@pytest.fixture()
def pid(fresh_db):
    return patients.find_or_create("Ramesh Kumar", "9845012345", consent=True)["id"]


def test_create_bill_totals_items_and_numbers_it(pid):
    bid = billing.create_bill(pid, "B", [("Consultation", 600), ("X-ray", 850)])
    bill = db.one("SELECT * FROM bills WHERE id = ?", (bid,))
    assert bill["total"] == 1450 and bill["paid"] == 0
    assert bill["bill_no"].startswith("B-") and bill["bill_no"].endswith(f"{bid:05d}")
    assert db.scalar("SELECT COUNT(*) FROM bill_items WHERE bill_id = ?", (bid,)) == 2
    assert db.scalar("SELECT COUNT(*) FROM audit_log WHERE entity='bill' AND entity_id=?", (bid,)) == 1


def test_duplicate_external_ref_rejected(pid):
    billing.create_bill(pid, "A", [("Consultation", 500)], external_ref="INV-1")
    with pytest.raises(ValueError, match="already exists"):
        billing.create_bill(pid, "A", [("Consultation", 500)], external_ref="INV-1")


def test_bill_validation(pid):
    with pytest.raises(ValueError):
        billing.create_bill(pid, "A", [])
    with pytest.raises(ValueError):
        billing.create_bill(pid, "A", [("Bad", 0)])
    with pytest.raises(LookupError):
        billing.create_bill(pid, "Z", [("Consultation", 500)])


def test_payment_updates_paid_and_rejects_overpayment(pid):
    bid = billing.create_bill(pid, "A", [("Consultation", 1000)])
    billing.record_payment(bid, 400, "UPI")
    assert db.scalar("SELECT paid FROM bills WHERE id = ?", (bid,)) == 400
    with pytest.raises(ValueError, match="more than the balance"):
        billing.record_payment(bid, 601, "UPI")
    with pytest.raises(ValueError):
        billing.record_payment(bid, 0, "UPI")
    billing.record_payment(bid, 600, "Cash")
    assert db.scalar("SELECT total - paid FROM bills WHERE id = ?", (bid,)) == 0


def test_order_goes_onto_open_bill_and_closes_task(pid):
    bid = billing.create_bill(pid, "A", [("Consultation", 500)])
    oid = billing.create_order(pid, "A", "Lab", "CBC", 350, created_at=util.now() - timedelta(hours=3))
    db.execute("INSERT INTO tasks(kind, title, branch_id, related_type, related_id, created_at) VALUES ('unbilled','x','A','order',?,?)",
               (oid, util.ts(util.now())))
    assert billing.add_order_to_bill(oid) == bid
    assert db.scalar("SELECT total FROM bills WHERE id = ?", (bid,)) == 850
    assert db.scalar("SELECT bill_id FROM orders WHERE id = ?", (oid,)) == bid
    assert db.scalar("SELECT status FROM tasks WHERE related_id = ?", (oid,)) == "Done"
    with pytest.raises(ValueError, match="already on bill"):
        billing.add_order_to_bill(oid)


def test_order_creates_new_bill_when_none_open(pid):
    old = billing.create_bill(pid, "A", [("Consultation", 500)], created_at=util.now() - timedelta(days=5))
    billing.record_payment(old, 500, "UPI")
    oid = billing.create_order(pid, "A", "Pharmacy", "Dressing kit", 420)
    new = billing.add_order_to_bill(oid)
    assert new != old
    assert db.scalar("SELECT total FROM bills WHERE id = ?", (new,)) == 420


def test_claim_stage_change_closes_stuck_task(pid):
    cid = billing.create_claim(pid, "A", "Star Health", 185000)
    db.execute("INSERT INTO tasks(kind, title, branch_id, related_type, related_id, created_at) VALUES ('claim_stuck','x','A','claim',?,?)",
               (cid, util.ts(util.now())))
    billing.set_claim_stage(cid, "PreAuthApproved")
    assert db.scalar("SELECT stage FROM claims WHERE id = ?", (cid,)) == "PreAuthApproved"
    assert db.scalar("SELECT status FROM tasks WHERE related_id = ?", (cid,)) == "Done"
    with pytest.raises(ValueError, match="Unknown claim stage"):
        billing.set_claim_stage(cid, "Paid")


def test_dues_lists_oldest_first_with_age(pid):
    b1 = billing.create_bill(pid, "A", [("A", 1000)], created_at=util.now() - timedelta(days=12))
    billing.create_bill(pid, "B", [("B", 500)], created_at=util.now() - timedelta(days=2))
    paid = billing.create_bill(pid, "A", [("C", 300)])
    billing.record_payment(paid, 300, "UPI")
    db.execute("INSERT INTO dues_reminders(bill_id, stage, sent_at) VALUES (?,1,?)", (b1, util.ts(util.now())))
    rows = billing.dues()
    assert [r["balance"] for r in rows] == [1000, 500]
    assert rows[0]["age_days"] == 12 and rows[0]["reminders_sent"] == 1 and rows[0]["uid"] == "TT-000001"
    assert [r["balance"] for r in billing.dues("B")] == [500]
