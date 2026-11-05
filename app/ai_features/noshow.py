"""No-show risk: a transparent rule-based score for each upcoming appointment, with its reasons.

Rules first (research: no local data yet); a trained model can replace the rules after about three
months of the hospital's own history. Never uses sensitive attributes (religion, caste, gender,
age group, income). Overbooking is only ever suggested, and capped.
"""
from datetime import datetime

from app import db, util

HIGH, MEDIUM = 60, 35
OVERBOOK_CAP = 2          # never suggest more than two extra bookings per doctor per day


def score_row(a: dict, now: datetime) -> tuple[int, str, list[str]]:
    """a: an appointments row with patient_id, starts_at, created_at, status, reminder_24h_sent_at, branch_id."""
    reasons: list[str] = []
    s = 10
    past = db.one("SELECT SUM(status='NoShow') AS ns, SUM(status IN ('Visited','NoShow')) AS n FROM appointments"
                  " WHERE patient_id = ? AND starts_at < ? AND id != ?", (a["patient_id"], util.ts(now), a["id"]))
    ns, n = past["ns"] or 0, past["n"] or 0
    if ns:
        s += min(40, 20 * ns)
        reasons.append(f"missed {ns} of {n} earlier visit{'s' if n != 1 else ''}")
    elif n >= 2:
        s -= 5
        reasons.append(f"came to all {n} earlier visits")
    starts = util.parse(a["starts_at"])
    lead_days = (starts - util.parse(a["created_at"])).days
    if lead_days >= 14:
        s += 15
        reasons.append(f"booked {lead_days} days ahead")
    elif lead_days >= 7:
        s += 8
        reasons.append(f"booked {lead_days} days ahead")
    if a["status"] == "Booked" and a.get("reminder_24h_sent_at"):
        s += 15
        reasons.append("did not confirm the 24-hour reminder")
    if starts.weekday() == 0 or starts.hour < 9 or starts.hour >= 18:
        s += 5
        reasons.append("early, late or Monday slot")
    other_branch_visits = db.scalar(
        "SELECT COUNT(*) FROM appointments WHERE patient_id = ? AND branch_id != ? AND status = 'Visited'",
        (a["patient_id"], a["branch_id"])) or 0
    same_branch_visits = db.scalar(
        "SELECT COUNT(*) FROM appointments WHERE patient_id = ? AND branch_id = ? AND status = 'Visited'",
        (a["patient_id"], a["branch_id"])) or 0
    if other_branch_visits > same_branch_visits:
        s += 5
        reasons.append("usually visits the other branch (likely farther away)")
    dues = db.scalar("SELECT COALESCE(SUM(total - paid), 0) FROM bills WHERE patient_id = ? AND total > paid",
                     (a["patient_id"],)) or 0
    if dues:
        s += 10
        reasons.append(f"{util.inr(dues)} pending on bills")
    s = max(0, min(100, s))
    level = "high" if s >= HIGH else "medium" if s >= MEDIUM else "low"
    if not reasons:
        reasons.append("no risk signals")
    return s, level, reasons


def annotate(rows: list[dict], now: datetime) -> None:
    """Add risk, risk_level and risk_reasons to upcoming Booked/Confirmed rows (in place)."""
    for r in rows:
        if r.get("status") in ("Booked", "Confirmed") and util.parse(r["starts_at"]) >= now:
            r["risk"], r["risk_level"], r["risk_reasons"] = score_row(r, now)


def overbook_suggestion(doctor_rows: list[dict]) -> int:
    """Expected no-shows for one doctor's day, rounded down and capped. A suggestion only."""
    expected = sum((r.get("risk") or 0) / 100 for r in doctor_rows)
    return min(OVERBOOK_CAP, int(expected))
