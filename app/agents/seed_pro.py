"""Demo data for AI Labs (called from app.seed): standard prices, payer document lists, claim
documents, a below-price line and a large discount on two bills, and pharmacy stock with expiries."""
import random
from datetime import datetime, timedelta

from app import db, util

TARIFFS = [("Consultation", 500), ("CBC", 350), ("Lipid profile", 650), ("HbA1c", 450), ("X-ray", 850), ("ECG", 300),
           ("Ultrasound abdomen", 1200), ("Thyroid profile", 550)]
CHECKLIST = {
    "*": ["Pre-authorisation form", "Doctor's admission note", "Patient ID proof", "Policy or e-card copy"],
    "PM-JAY": ["Beneficiary e-card", "Pre-authorisation form", "Doctor's admission note"],
}
# (name, unit, reorder level, daily use at A, daily use at B, unit cost)
STOCK = [("Paracetamol 500 mg", "strips", 80, 12.0, 6.0, 18), ("Amoxicillin 500 mg", "strips", 40, 4.0, 2.0, 62),
         ("Insulin glargine pen", "pens", 10, 0.6, 1.4, 780), ("Ceftriaxone 1 g injection", "vials", 30, 3.0, 1.0, 55),
         ("ORS sachet", "sachets", 100, 10.0, 12.0, 21), ("Pantoprazole 40 mg injection", "vials", 20, 2.0, 0.2, 48)]
TABLES = ["findings", "agent_runs", "claim_documents", "payer_checklists", "tariffs", "stock_moves", "stock_batches",
          "stock_items", "voice_turns", "voice_sessions"]


def wipe() -> None:
    for t in TABLES:
        db.execute(f"DELETE FROM {t}")


def seed_pro(now: datetime, rng: random.Random) -> dict:
    wipe()
    for d, a in TARIFFS:
        db.execute("INSERT INTO tariffs(description, amount) VALUES (?,?)", (d, a))
    for insurer, docs in CHECKLIST.items():
        for doc in docs:
            db.execute("INSERT INTO payer_checklists(insurer, document) VALUES (?,?)", (insurer, doc))
    ts = util.ts(now)
    for c in db.query("SELECT id, insurer FROM claims ORDER BY id"):
        docs = CHECKLIST.get(c["insurer"], CHECKLIST["*"])
        keep = docs if rng.random() < 0.4 else rng.sample(docs, max(1, len(docs) - rng.choice([1, 2])))
        for doc in keep:
            db.execute("INSERT INTO claim_documents(claim_id, document, received_at) VALUES (?,?,?)", (c["id"], doc, ts))

    # One ECG charged below its standard price, and one unusually large discount, on recent bills.
    recent = db.query("SELECT id, total, paid FROM bills WHERE created_at >= ? ORDER BY id DESC LIMIT 40",
                      (util.ts(now - timedelta(days=10)),))
    if recent:
        b = recent[0]
        db.execute("INSERT INTO bill_items(bill_id, description, amount) VALUES (?,?,?)", (b["id"], "ECG", 200))
        db.execute("UPDATE bills SET total = total + 200 WHERE id = ?", (b["id"],))
    unpaid = [b for b in recent if b["total"] - b["paid"] >= 400]
    if unpaid:
        b = unpaid[0]
        gross = db.scalar("SELECT SUM(amount) FROM bill_items WHERE bill_id = ? AND amount > 0", (b["id"],))
        disc = min(b["total"] - b["paid"], max(400, int(gross * 0.35)))
        db.execute("INSERT INTO bill_items(bill_id, description, amount) VALUES (?,?,?)",
                   (b["id"], "Discount (approved at counter)", -disc))
        db.execute("UPDATE bills SET total = total - ? WHERE id = ?", (disc, b["id"]))

    # Two patients overdue for their review, for the follow-up and churn agent.
    quiet = db.query("SELECT p.id, (SELECT branch_id FROM appointments WHERE patient_id = p.id ORDER BY starts_at DESC LIMIT 1)"
                     " AS branch_id FROM patients p WHERE EXISTS (SELECT 1 FROM appointments WHERE patient_id = p.id)"
                     " AND NOT EXISTS (SELECT 1 FROM appointments a WHERE a.patient_id = p.id AND a.starts_at >= ?)"
                     " ORDER BY p.id LIMIT 2", (util.ts(now - timedelta(days=14)),))
    for q, reason in zip(quiet, ["diabetes review (HbA1c)", "BP review"]):
        db.execute("INSERT INTO followups(patient_id, branch_id, due_date, reason, status, created_at) VALUES (?,?,?,?,'Due',?)",
                   (q["id"], q["branch_id"] or "A", (now.date() - timedelta(days=8)).isoformat(), reason,
                    util.ts(now - timedelta(days=40))))

    today = now.date()
    batches = 0
    for name, unit, reorder, use_a, use_b, cost in STOCK:
        for br, use in (("A", use_a), ("B", use_b)):
            iid = db.execute("INSERT INTO stock_items(name, branch_id, unit, reorder_level, daily_usage) VALUES (?,?,?,?,?)",
                             (name, br, unit, reorder, use))
            plan = [(rng.randint(150, 400), int(use * rng.randint(40, 90)) + reorder)]
            if (name, br) in (("Pantoprazole 40 mg injection", "B"), ("Insulin glargine pen", "A")):
                plan = [(45, 60 if unit == "vials" else 30)]          # will expire with most of it unused
            if (name, br) == ("Pantoprazole 40 mg injection", "A"):
                plan = [(200, 25)]                                    # busy branch, little stock: can take more
            if name == "Amoxicillin 500 mg" and br == "B":
                plan = [(25, 90)]                                     # expires soon; nowhere uses this much
            if name == "Ceftriaxone 1 g injection" and br == "B":
                plan = [(300, 12)]                                    # below reorder level
            for days, qty in plan:
                db.execute("INSERT INTO stock_batches(item_id, batch_no, expiry_date, qty, unit_cost) VALUES (?,?,?,?,?)",
                           (iid, f"{name[:3].upper()}{br}{rng.randint(1000, 9999)}", (today + timedelta(days=days)).isoformat(),
                            qty, cost))
                batches += 1
    return {"tariffs": len(TARIFFS), "stock_batches": batches}
