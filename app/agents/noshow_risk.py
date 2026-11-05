"""No-show risk agent: suggests a reminder call for high-risk appointments in the next 48 hours, and a
capped overbooking suggestion per doctor-day. Suggestions only; staff decide."""
from collections import defaultdict
from datetime import datetime, timedelta

from app import db, util
from app.agents import Agent, register
from app.ai_features import noshow


def run(now: datetime) -> list[dict]:
    rows = db.query(
        "SELECT a.*, p.name AS patient, d.name AS doctor FROM appointments a JOIN patients p ON p.id = a.patient_id"
        " JOIN doctors d ON d.id = a.doctor_id WHERE a.status IN ('Booked','Confirmed') AND a.starts_at BETWEEN ? AND ?",
        (util.ts(now), util.ts(now + timedelta(hours=48))))
    noshow.annotate(rows, now)
    out, by_day = [], defaultdict(list)
    for r in rows:
        if "risk" not in r:
            continue
        by_day[(r["doctor_id"], r["starts_at"][:10], r["doctor"], r["branch_id"])].append(r)
        if r["risk_level"] != "high":
            continue
        out.append({
            "key": f"noshow:{r['id']}", "severity": "medium",
            "title": f"{r['patient']} may miss {r['starts_at'][8:10]}/{r['starts_at'][5:7]} {r['starts_at'][11:16]}"
                     f" with {r['doctor']} (risk {r['risk']}/100)",
            "evidence": {"appointment_id": r["id"], "risk_score": r["risk"], "reasons": r["risk_reasons"],
                         "model": "noshow_rules 1.0 (rules, decision support)"},
            "suggested_action": "Call the patient to confirm or offer another time.",
            "action": {"type": "task", "kind": "followup_call", "related_type": "appointment", "related_id": r["id"],
                       "title": f"Confirm visit: {r['patient']} at {r['starts_at'][11:16]} with {r['doctor']}"},
            "branch_id": r["branch_id"],
        })
    for (doctor_id, day, doctor, branch_id), appts in by_day.items():
        extra = noshow.overbook_suggestion(appts)
        if extra:
            out.append({
                "key": f"overbook:{doctor_id}:{day}", "severity": "low",
                "title": f"{doctor} on {day[8:10]}/{day[5:7]}: about {extra} likely no-show{'s' if extra > 1 else ''}",
                "evidence": {"doctor_id": doctor_id, "day": day, "booked": len(appts), "suggested_extra": extra,
                             "cap": noshow.OVERBOOK_CAP, "note": "Suggestion only; the front desk decides."},
                "suggested_action": f"Consider offering up to {extra} extra slot{'s' if extra > 1 else ''} from the waitlist."
                                    " Do not overbook without the doctor's agreement.",
                "action": None, "branch_id": branch_id,
            })
    return out


register(Agent("noshow_risk", "No-show risk",
               "Scores upcoming appointments for no-show risk with reasons, suggests reminder calls and a capped "
               "overbooking suggestion. Rules-based decision support.", 60, run))
