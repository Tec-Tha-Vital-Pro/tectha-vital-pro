"""NEWS2 early warning (Royal College of Physicians, 2017), SpO2 scale 1.

A rules-based published score, not a diagnosis and not a machine-learning model. Thresholds are
tunable by the ICU team in Settings. Alerts go to the ward's doctors and nurses; an emergency alert
that nobody acknowledges is escalated to admins after the escalation time.
"""
from datetime import datetime, timedelta

from app import audit, db, notify, util
from app.ai_features import governance

LABEL = "NEWS2 is a rules-based published score, not a diagnosis. Clinical judgement decides."
DEFAULTS = {"news2_urgent": 5, "news2_emergency": 7, "news2_rise": 2, "news2_escalate_minutes": 15}


def thresholds() -> dict[str, int]:
    return {k: int(db.get_setting(k, str(v))) for k, v in DEFAULTS.items()}


def set_thresholds(values: dict[str, str], actor: str) -> None:
    clean = {}
    for k in DEFAULTS:
        v = values.get(k, "")
        if not str(v).isdigit():
            raise ValueError("Thresholds must be whole numbers.")
        clean[k] = int(v)
    if not (1 <= clean["news2_urgent"] < clean["news2_emergency"] <= 20):
        raise ValueError("Urgent must be below emergency, both between 1 and 20.")
    if not (1 <= clean["news2_rise"] <= 10 and 1 <= clean["news2_escalate_minutes"] <= 120):
        raise ValueError("Rise must be 1–10 and escalation 1–120 minutes.")
    for k, v in clean.items():
        db.set_setting(k, str(v))
    audit.log(actor, "news2_thresholds_changed", "settings", None, clean)


def _rr(v):
    return 3 if v <= 8 else 1 if v <= 11 else 0 if v <= 20 else 2 if v <= 24 else 3


def _spo2(v):
    return 3 if v <= 91 else 2 if v <= 93 else 1 if v <= 95 else 0


def _sbp(v):
    return 3 if v <= 90 else 2 if v <= 100 else 1 if v <= 110 else 0 if v <= 219 else 3


def _pulse(v):
    return 3 if v <= 40 else 1 if v <= 50 else 0 if v <= 90 else 1 if v <= 110 else 2 if v <= 130 else 3


def _temp(v):
    return 3 if v <= 35.0 else 1 if v <= 36.0 else 0 if v <= 38.0 else 1 if v <= 39.0 else 2


def score(*, resp_rate: int, spo2: int, on_oxygen: bool, systolic_bp: int, pulse: int, consciousness: str,
          temperature: float) -> tuple[int, bool, dict[str, int]]:
    """Return (total, any single parameter scored 3, per-parameter scores)."""
    if consciousness not in ("A", "C", "V", "P", "U"):
        raise ValueError("Consciousness must be A, C, V, P or U (ACVPU).")
    parts = {"Respiration rate": _rr(resp_rate), "SpO2": _spo2(spo2), "Air or oxygen": 2 if on_oxygen else 0,
             "Systolic BP": _sbp(systolic_bp), "Pulse": _pulse(pulse),
             "Consciousness": 0 if consciousness == "A" else 3, "Temperature": _temp(temperature)}
    total = sum(parts.values())
    return total, any(v == 3 for v in parts.values()), parts


def record(patient_id: int, branch_id: str, values: dict, actor: str, *, bed_id: int | None = None,
           now: datetime | None = None) -> dict:
    now = now or util.now()
    ranges = {"resp_rate": (3, 70), "spo2": (50, 100), "systolic_bp": (40, 300), "pulse": (20, 250)}
    for k, (lo, hi) in ranges.items():
        if not lo <= int(values[k]) <= hi:
            raise ValueError(f"{k.replace('_', ' ')} looks wrong ({values[k]}). Check and enter again.")
    if not 30.0 <= float(values["temperature"]) <= 44.0:
        raise ValueError("Temperature should be in °C, between 30 and 44.")
    total, three, parts = score(resp_rate=int(values["resp_rate"]), spo2=int(values["spo2"]),
                                on_oxygen=bool(values.get("on_oxygen")), systolic_bp=int(values["systolic_bp"]),
                                pulse=int(values["pulse"]), consciousness=values["consciousness"],
                                temperature=float(values["temperature"]))
    prev = db.one("SELECT news2 FROM vitals WHERE patient_id = ? ORDER BY recorded_at DESC, id DESC LIMIT 1", (patient_id,))
    vid = db.execute(
        "INSERT INTO vitals(patient_id, bed_id, branch_id, resp_rate, spo2, on_oxygen, systolic_bp, pulse, consciousness,"
        " temperature, news2, any_three, recorded_by, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (patient_id, bed_id, branch_id, int(values["resp_rate"]), int(values["spo2"]), 1 if values.get("on_oxygen") else 0,
         int(values["systolic_bp"]), int(values["pulse"]), values["consciousness"], float(values["temperature"]),
         total, 1 if three else 0, actor, util.ts(now)))
    audit.log(actor, "vitals_recorded", "patient", patient_id, {"news2": total})
    alert = _maybe_alert(vid, patient_id, branch_id, total, three, prev["news2"] if prev else None, now)
    return {"id": vid, "news2": total, "any_three": three, "parts": parts, "alert": alert}


def _maybe_alert(vid: int, patient_id: int, branch_id: str, total: int, three: bool, prev: int | None,
                 now: datetime) -> dict | None:
    th = thresholds()
    level, reason = None, ""
    if total >= th["news2_emergency"]:
        level, reason = "emergency", f"NEWS2 {total} (emergency threshold {th['news2_emergency']})"
    elif total >= th["news2_urgent"] or three:
        level, reason = "urgent", (f"NEWS2 {total} (urgent review threshold {th['news2_urgent']})" if total >= th["news2_urgent"]
                                   else f"NEWS2 {total} with a single parameter scoring 3")
    elif prev is not None and total - prev >= th["news2_rise"]:
        level, reason = "rise", f"NEWS2 rose from {prev} to {total}"
    if level is None:
        return None
    aid = db.execute("INSERT INTO news2_alerts(vitals_id, patient_id, branch_id, level, score, reason, created_at)"
                     " VALUES (?,?,?,?,?,?,?)", (vid, patient_id, branch_id, level, total, reason, util.ts(now)))
    name = db.scalar("SELECT name FROM patients WHERE id = ?", (patient_id,)) or "Patient"
    sev = "critical" if level == "emergency" else "warn"
    notify.notify(title=f"NEWS2 {level}: {name}, {reason}", link=f"/vitals#alert-{aid}", role=["doctor", "nurse"],
                  branch=branch_id, severity=sev, source_key=f"news2:{aid}")
    governance.log_decision("news2", "news2_rcp", "suggested", "system", output={"level": level, "score": total},
                            subject_type="news2_alert", subject_id=aid, input_summary=reason)
    return {"id": aid, "level": level, "reason": reason}


def acknowledge(alert_id: int, actor: str) -> None:
    a = db.one("SELECT * FROM news2_alerts WHERE id = ?", (alert_id,))
    if a is None:
        raise LookupError("Alert not found")
    if a["status"] == "Acknowledged":
        return
    db.execute("UPDATE news2_alerts SET status='Acknowledged', acknowledged_by=?, acknowledged_at=? WHERE id=?",
               (actor, util.ts(util.now()), alert_id))
    governance.log_decision("news2", "news2_rcp", "acknowledged", actor, output={"alert": alert_id},
                            subject_type="news2_alert", subject_id=alert_id)
    audit.log(actor, "news2_acknowledged", "news2_alert", alert_id)


def escalate_overdue(now: datetime) -> dict:
    """Emergency and urgent alerts not acknowledged in time go to admins (scheduler sweep)."""
    mins = thresholds()["news2_escalate_minutes"]
    cutoff = util.ts(now - timedelta(minutes=mins))
    n = 0
    for a in db.query("SELECT a.*, p.name FROM news2_alerts a JOIN patients p ON p.id = a.patient_id WHERE a.status = 'Open'"
                      " AND a.level IN ('urgent','emergency') AND a.escalated_at IS NULL AND a.created_at <= ?", (cutoff,)):
        notify.notify(title=f"Escalated: NEWS2 {a['level']} for {a['name']} not acknowledged in {mins} min",
                      link=f"/vitals#alert-{a['id']}", role=["admin", "owner"], branch=a["branch_id"], severity="critical",
                      source_key=f"news2-esc:{a['id']}")
        db.execute("UPDATE news2_alerts SET escalated_at = ? WHERE id = ?", (util.ts(now), a["id"]))
        governance.log_decision("news2", "news2_rcp", "escalated", "system", output={"alert": a["id"]},
                                subject_type="news2_alert", subject_id=a["id"])
        n += 1
    return {"escalated": n}


def open_alerts(branch: str | None) -> list[dict]:
    return db.query("SELECT a.*, p.name, p.uid FROM news2_alerts a JOIN patients p ON p.id = a.patient_id"
                    " WHERE a.status = 'Open'" + (" AND a.branch_id = ?" if branch else "") + " ORDER BY a.score DESC, a.created_at",
                    (branch,) if branch else ())


def inpatients(branch: str | None) -> list[dict]:
    """Occupied beds with the patient and their latest NEWS2."""
    rows = db.query(
        "SELECT bd.id AS bed_id, bd.label AS bed, w.name AS ward, w.branch_id, p.id AS patient_id, p.name, p.uid"
        " FROM beds bd JOIN wards w ON w.id = bd.ward_id JOIN patients p ON p.id = bd.patient_id"
        " WHERE bd.status = 'Occupied'" + (" AND w.branch_id = ?" if branch else "") + " ORDER BY w.branch_id, w.name, bd.label",
        (branch,) if branch else ())
    for r in rows:
        last = db.query("SELECT news2, recorded_at FROM vitals WHERE patient_id = ? ORDER BY recorded_at DESC, id DESC LIMIT 2",
                        (r["patient_id"],))
        r["news2"] = last[0]["news2"] if last else None
        r["recorded_at"] = last[0]["recorded_at"] if last else None
        r["trend"] = (last[0]["news2"] - last[1]["news2"]) if len(last) == 2 else None
    return rows
