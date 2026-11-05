"""Demo data for the next AI features (sample data only)."""
from datetime import datetime, timedelta

from app import db, util
from app.ai_features import coding, explainers, governance, news2

TABLES = ("ai_decisions", "news2_alerts", "vitals", "coding_suggestions", "draft_replies", "report_explainers")


def wipe() -> None:
    for t in TABLES:
        db.execute(f"DELETE FROM {t}")


def seed_ai(now: datetime) -> dict:
    governance.ensure_registered()
    n_exp = explainers.seed_starters()
    # Put demo patients in the occupied beds that have none, so the ward view has names.
    empty = db.query("SELECT bd.id FROM beds bd WHERE bd.status = 'Occupied' AND bd.patient_id IS NULL ORDER BY bd.id")
    pts = db.query("SELECT id FROM patients WHERE id NOT IN (SELECT patient_id FROM beds WHERE patient_id IS NOT NULL)"
                   " ORDER BY id LIMIT ?", (len(empty),))
    for bed, p in zip(empty, pts):
        db.execute("UPDATE beds SET patient_id = ? WHERE id = ?", (p["id"], bed["id"]))
    # Vitals: a stable patient, one whose score is rising, and one at the emergency threshold.
    beds = db.query("SELECT bd.id AS bed_id, w.branch_id, bd.patient_id FROM beds bd JOIN wards w ON w.id = bd.ward_id"
                    " WHERE bd.status = 'Occupied' AND bd.patient_id IS NOT NULL ORDER BY bd.id LIMIT 6")
    stable = dict(resp_rate=16, spo2=97, on_oxygen=False, systolic_bp=124, pulse=78, consciousness="A", temperature=36.8)
    worse = dict(resp_rate=22, spo2=94, on_oxygen=False, systolic_bp=108, pulse=104, consciousness="A", temperature=38.4)
    bad = dict(resp_rate=26, spo2=91, on_oxygen=True, systolic_bp=96, pulse=118, consciousness="C", temperature=38.9)
    n_v = 0
    for i, b in enumerate(beds):
        series = [stable, stable] if i % 3 == 0 else ([stable, worse] if i % 3 == 1 else [worse, bad])
        for j, vals in enumerate(series):
            news2.record(b["patient_id"], b["branch_id"], vals, "user:Nurse Demo (seed)", bed_id=b["bed_id"],
                         now=now - timedelta(hours=4 - 3 * j))
            n_v += 1
    # One coding suggestion waiting for a coder.
    # Use an open claim whose patient already has a bill, and record the ward note as billed on it,
    # so the seed's unbilled-order counts stay as they were.
    claim = db.one("SELECT c.id, c.patient_id, c.branch_id, (SELECT MAX(b.id) FROM bills b WHERE b.patient_id = c.patient_id)"
                   " AS bill_id FROM claims c WHERE c.stage IN ('PreAuthRequested','PreAuthApproved','FinalSent')"
                   " AND EXISTS (SELECT 1 FROM bills b WHERE b.patient_id = c.patient_id) ORDER BY c.id LIMIT 1")
    n_c = 0
    if claim:
        db.execute("INSERT INTO orders(patient_id, branch_id, dept, description, amount, bill_id, created_at)"
                   " VALUES (?,?,?,?,?,?,?)",
                   (claim["patient_id"], claim["branch_id"], "Ward", "Admitted with dengue fever, platelet monitoring twice daily",
                    1200, claim["bill_id"], util.ts(now - timedelta(days=1))))
        r = coding.suggest(claim["id"], "user:Billing Demo (seed)")
        n_c = len(r["items"])
    return {"report_explainers": n_exp, "vitals": n_v, "coding_suggestions": n_c,
            "news2_alerts_open": db.scalar("SELECT COUNT(*) FROM news2_alerts WHERE status='Open'")}
