"""Numbers for the owner dashboard and the daily report. branch=None means all branches."""
from datetime import date, timedelta

from app import db


def _bf(col: str, branch: str | None) -> tuple[str, tuple]:
    return (f" AND {col} = ?", (branch,)) if branch else ("", ())


def kpis(day: date, branch: str | None = None) -> dict:
    d = day.isoformat()
    f, p = _bf("branch_id", branch)
    opd = db.scalar(f"SELECT COUNT(*) FROM appointments WHERE status='Visited' AND date(starts_at)=?{f}", (d, *p))
    booked = db.scalar(f"SELECT COUNT(*) FROM appointments WHERE date(starts_at)=?{f}", (d, *p))
    billed = db.scalar(f"SELECT COALESCE(SUM(total),0) FROM bills WHERE date(created_at)=?{f}", (d, *p))
    fb, pb = _bf("b.branch_id", branch)
    collected = db.scalar(
        f"SELECT COALESCE(SUM(pay.amount),0) FROM payments pay JOIN bills b ON b.id=pay.bill_id WHERE date(pay.paid_at)=?{fb}", (d, *pb))
    dues = db.scalar(f"SELECT COALESCE(SUM(total-paid),0) FROM bills WHERE total>paid{f}", p)
    since = (day - timedelta(days=30)).isoformat()
    done = db.one(
        f"SELECT SUM(status='NoShow') AS ns, SUM(status IN ('Visited','NoShow')) AS n FROM appointments"
        f" WHERE date(starts_at) BETWEEN ? AND ?{f}", (since, d, *p))
    no_show = round(100 * (done["ns"] or 0) / done["n"]) if done["n"] else 0
    return {"opd": opd, "booked": booked, "billed": billed, "collected": collected, "dues": dues, "no_show_pct": no_show}


def collections_by_day(end: date, days: int = 7) -> list[dict]:
    """[{day:'2026-11-04', A: rupees, B: rupees}, ...] oldest first."""
    branches = [b["id"] for b in db.query("SELECT id FROM branches ORDER BY id")]
    out = []
    for i in range(days - 1, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        row = {"day": d}
        for b in branches:
            row[b] = db.scalar(
                "SELECT COALESCE(SUM(pay.amount),0) FROM payments pay JOIN bills bl ON bl.id=pay.bill_id"
                " WHERE date(pay.paid_at)=? AND bl.branch_id=?", (d, b))
        out.append(row)
    return out


def funnel(start: date, end: date, branch: str | None = None) -> dict:
    f, p = _bf("l.branch_id", branch)
    rng = (start.isoformat(), end.isoformat(), *p)
    base = f"FROM leads l WHERE date(l.created_at) BETWEEN ? AND ?{f}"
    enquiries = db.scalar(f"SELECT COUNT(*) {base}", rng)
    booked = db.scalar(f"SELECT COUNT(*) {base} AND l.status IN ('Booked','Converted')", rng)
    visited = db.scalar(
        f"SELECT COUNT(*) {base} AND l.patient_id IS NOT NULL AND EXISTS"
        " (SELECT 1 FROM appointments a WHERE a.patient_id=l.patient_id AND a.status='Visited' AND a.starts_at>=l.created_at)", rng)
    paid = db.scalar(
        f"SELECT COUNT(*) {base} AND l.patient_id IS NOT NULL AND EXISTS"
        " (SELECT 1 FROM payments pay JOIN bills b ON b.id=pay.bill_id WHERE b.patient_id=l.patient_id AND pay.paid_at>=l.created_at)", rng)
    return {"enquiries": enquiries, "booked": booked, "visited": visited, "paid": paid}


def reply_speed(day: date, branch: str | None = None) -> dict:
    f, p = _bf("branch_id", branch)
    r = db.one(
        f"SELECT COUNT(*) AS n, SUM(first_reply_seconds IS NOT NULL AND first_reply_seconds<=300) AS fast,"
        f" SUM(first_reply_seconds IS NULL) AS waiting FROM leads WHERE date(created_at)=?{f}", (day.isoformat(), *p))
    n = r["n"] or 0
    return {"enquiries": n, "within_5_min_pct": round(100 * (r["fast"] or 0) / n) if n else 0, "not_replied": r["waiting"] or 0}


def attention(branch: str | None = None) -> dict:
    f, p = _bf("branch_id", branch)
    return {
        "claims_stuck": db.scalar(f"SELECT COUNT(*) FROM tasks WHERE kind='claim_stuck' AND status='Open'{f}", p),
        "unbilled_amount": db.scalar(f"SELECT COALESCE(SUM(amount),0) FROM orders WHERE bill_id IS NULL{f}", p),
        "missed_calls_open": db.scalar(f"SELECT COUNT(*) FROM tasks WHERE kind='missed_call' AND status='Open'{f}", p),
        "complaints_open": db.scalar(f"SELECT COUNT(*) FROM tasks WHERE kind='complaint' AND status='Open'{f}", p),
    }
