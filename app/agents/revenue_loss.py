"""Revenue-loss agent: services delivered but not billed, lines charged below the standard price,
and discounts far above normal."""
from datetime import datetime, timedelta

from app import db, util
from app.agents import Agent, register

DISCOUNT_SHARE = 0.20          # a discount over 20% of the bill is unusual enough to check
LOOKBACK_DAYS = 30


def run(now: datetime) -> list[dict]:
    out = []
    for o in db.query("SELECT o.*, p.name AS patient FROM orders o JOIN patients p ON p.id = o.patient_id"
                      " WHERE o.bill_id IS NULL AND o.created_at < ?", (util.ts(now - timedelta(hours=2)),)):
        out.append({
            "key": f"order:{o['id']}", "severity": "high" if o["amount"] >= 5000 else "medium",
            "title": f"Not billed: {o['dept']} – {o['description']} for {o['patient']}",
            "evidence": {"order_id": o["id"], "department": o["dept"], "done_at": o["created_at"], "amount": o["amount"]},
            "suggested_action": f"Add {util.inr(o['amount'])} to the patient's bill.",
            "action": {"type": "add_order_to_bill", "order_id": o["id"]}, "amount": o["amount"], "branch_id": o["branch_id"],
        })
    since = util.ts(now - timedelta(days=LOOKBACK_DAYS))
    for r in db.query("SELECT i.id, i.description, i.amount, t.amount AS standard, b.bill_no, b.branch_id, p.name AS patient"
                      " FROM bill_items i JOIN bills b ON b.id = i.bill_id JOIN patients p ON p.id = b.patient_id"
                      " JOIN tariffs t ON lower(t.description) = lower(i.description)"
                      " WHERE i.amount > 0 AND i.amount < t.amount AND b.created_at >= ?", (since,)):
        gap = r["standard"] - r["amount"]
        out.append({
            "key": f"below_tariff:{r['id']}", "severity": "medium" if gap >= 500 else "low",
            "title": f"Charged below standard price: {r['description']} on bill {r['bill_no']}",
            "evidence": {"bill_no": r["bill_no"], "patient": r["patient"], "charged": r["amount"], "standard": r["standard"]},
            "suggested_action": f"Check why {r['description']} was {util.inr(r['amount'])} instead of {util.inr(r['standard'])}.",
            "action": None, "amount": gap, "branch_id": r["branch_id"],
        })
    for r in db.query("SELECT i.id, i.description, i.amount, b.id AS bill_id, b.bill_no, b.branch_id,"
                      " (SELECT COALESCE(SUM(amount),0) FROM bill_items WHERE bill_id = b.id AND amount > 0) AS gross"
                      " FROM bill_items i JOIN bills b ON b.id = i.bill_id WHERE i.amount < 0 AND b.created_at >= ?", (since,)):
        if r["gross"] and -r["amount"] > DISCOUNT_SHARE * r["gross"]:
            out.append({
                "key": f"discount:{r['id']}", "severity": "medium",
                "title": f"Large discount on bill {r['bill_no']}: {util.inr(-r['amount'])} of {util.inr(r['gross'])}",
                "evidence": {"bill_no": r["bill_no"], "line": r["description"], "discount": -r["amount"], "gross": r["gross"],
                             "share_pct": round(100 * -r["amount"] / r["gross"])},
                "suggested_action": "Confirm who approved this discount and why.",
                "action": None, "amount": -r["amount"], "branch_id": r["branch_id"],
            })
    return out


register(Agent("revenue_loss", "Revenue-loss finder",
               "Finds services done but not billed, lines below the standard price and unusual discounts.",
               30, run))
