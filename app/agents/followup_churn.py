"""Follow-up and churn agent: patients overdue for their review, scored by how likely they are to drop out."""
from datetime import datetime, timedelta

from app import db, util
from app.agents import Agent, register

GRACE_DAYS = 3


def run(now: datetime) -> list[dict]:
    out = []
    cutoff = (now.date() - timedelta(days=GRACE_DAYS)).isoformat()
    since = util.ts(now - timedelta(days=180))
    for f in db.query("SELECT f.*, p.name AS patient, p.phone FROM followups f JOIN patients p ON p.id = f.patient_id"
                      " WHERE f.status IN ('Due','Reminded') AND f.due_date < ?", (cutoff,)):
        came_back = db.scalar("SELECT 1 FROM appointments WHERE patient_id = ? AND status IN ('Booked','Confirmed','Visited')"
                              " AND date(starts_at) >= ? LIMIT 1", (f["patient_id"], f["due_date"]))
        if came_back:
            continue
        days = (now.date() - datetime.strptime(f["due_date"], "%Y-%m-%d").date()).days
        no_shows = db.scalar("SELECT COUNT(*) FROM appointments WHERE patient_id = ? AND status = 'NoShow' AND starts_at >= ?",
                             (f["patient_id"], since)) or 0
        dues = db.scalar("SELECT COALESCE(SUM(total - paid), 0) FROM bills WHERE patient_id = ? AND total > paid",
                         (f["patient_id"],)) or 0
        low_score = db.scalar("SELECT 1 FROM feedback WHERE patient_id = ? AND score <= 3 LIMIT 1", (f["patient_id"],))
        score, reasons = 40, [f"{days} days overdue for {f['reason']}"]
        score += min(30, days)
        if no_shows:
            score += 10 * min(no_shows, 2)
            reasons.append(f"{no_shows} missed visit{'s' if no_shows > 1 else ''} in 6 months")
        if dues:
            score += 10
            reasons.append(f"{util.inr(dues)} pending on bills")
        if low_score:
            score += 10
            reasons.append("gave a low feedback score")
        score = min(score, 100)
        out.append({
            "key": f"followup:{f['id']}", "severity": "high" if score >= 70 else "medium",
            "title": f"{f['patient']} has not come back for {f['reason']} (risk {score}/100)",
            "evidence": {"followup_id": f["id"], "due_date": f["due_date"], "risk_score": score, "reasons": reasons},
            "suggested_action": "Call the patient and offer a convenient time."
                                + (" Mention a payment plan for the pending amount." if dues else ""),
            "action": {"type": "task", "kind": "followup_call", "related_type": "followup", "related_id": f["id"],
                       "title": f"Call {f['patient']} about overdue {f['reason']}"},
            "branch_id": f["branch_id"],
        })
    return out


register(Agent("followup_churn", "Follow-up and churn",
               "Finds patients overdue for review visits and scores how likely they are to drop out of care.", 60, run))
