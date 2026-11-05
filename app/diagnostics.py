"""Diagnostics & Pharmacy: lab pipeline, critical call-outs, reflex rules, radiology, pharmacy counter.

Clinical safety rules built in here:
- Only normal results that pass the delta check are auto-validated; anything abnormal waits for a
  pathologist/doctor. Critical values open a call-out that must be closed with read-back.
- Patients see a result only after validation, and never an interpretation.
- Obstetric ultrasound cannot be marked performed until PCPNDT Form F is recorded. There is no field
  for the sex of a foetus anywhere in this module.
"""
from datetime import datetime, timedelta

from app import audit, billing, db, notify, util

LAB_FLOW = ["Ordered", "Collected", "Received", "Resulted", "Validated"]
RAD_FLOW = ["Scheduled", "Performed", "Reported"]
CALLOUT_ESCALATE_AFTER = timedelta(minutes=15)


class RuleError(ValueError):
    """A clinical or workflow rule stopped the action; the message is shown to staff."""


# ---------------------------------------------------------------- lab

def _test(code: str) -> dict:
    t = db.one("SELECT * FROM lab_tests WHERE code = ?", (code,))
    if t is None:
        raise RuleError(f"Unknown test code {code!r}")
    return t


def reference_range(test_code: str, patient: dict) -> tuple[float | None, float | None]:
    sex = (patient.get("gender") or "").upper()[:1]
    age = patient.get("age")
    rows = db.query("SELECT * FROM lab_ranges WHERE test_code = ? ORDER BY sex DESC, age_min DESC", (test_code,))
    for r in rows:
        if r["sex"] not in ("A", sex):
            continue
        if age is not None and not (r["age_min"] <= age <= r["age_max"]):
            continue
        return r["low"], r["high"]
    return None, None


def flag_for(value: float, test: dict, low: float | None, high: float | None) -> str:
    if test["crit_low"] is not None and value < test["crit_low"]:
        return "LL"
    if test["crit_high"] is not None and value > test["crit_high"]:
        return "HH"
    if low is not None and value < low:
        return "L"
    if high is not None and value > high:
        return "H"
    return "N"


def create_lab_order(patient_id: int, branch_id: str, test_code: str, *, doctor_id: int | None = None,
                     now: datetime | None = None, reflex_of: int | None = None, status: str = "Ordered",
                     sample_id: str | None = None, actor: str = "system") -> int:
    test = _test(test_code)
    ts = util.ts(now or util.now())
    order_id = billing.create_order(patient_id, branch_id, "Lab", test["name"], test["price"], created_at=ts, actor=actor)
    lid = db.execute(
        "INSERT INTO lab_orders(patient_id, branch_id, doctor_id, test_code, status, reflex_of, order_id, ordered_at,"
        " collected_at, received_at, sample_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (patient_id, branch_id, doctor_id, test_code, status, reflex_of, order_id, ts,
         ts if status in ("Collected", "Received") else None, ts if status == "Received" else None, sample_id))
    audit.log(actor, "create", "lab_order", lid, {"test": test_code, "reflex_of": reflex_of})
    return lid


def _sample_id(lab: dict, now: datetime) -> str:
    return f"{lab['branch_id']}-L{now:%y%m%d}-{lab['id']:05d}"


def advance(lab_id: int, *, actor: str, now: datetime | None = None) -> str:
    """Ordered -> Collected (prints a sample ID) -> Received. Resulting and validation have their own steps."""
    now = now or util.now()
    lab = db.one("SELECT * FROM lab_orders WHERE id = ?", (lab_id,))
    if lab is None:
        raise RuleError("Lab order not found")
    if lab["status"] == "Ordered":
        sid = _sample_id(lab, now)
        db.execute("UPDATE lab_orders SET status='Collected', collected_at=?, sample_id=? WHERE id=?", (util.ts(now), sid, lab_id))
        new = "Collected"
    elif lab["status"] == "Collected":
        db.execute("UPDATE lab_orders SET status='Received', received_at=? WHERE id=?", (util.ts(now), lab_id))
        new = "Received"
    elif lab["status"] == "Received":
        raise RuleError("Enter the result to move this test on")
    elif lab["status"] == "Resulted":
        raise RuleError("A pathologist must validate this result")
    else:
        raise RuleError(f"This test is already {lab['status'].lower()}")
    audit.log(actor, "lab_advance", "lab_order", lab_id, {"to": new})
    return new


def enter_result(lab_id: int, value: float, *, actor: str, now: datetime | None = None) -> dict:
    """Store a numeric result, flag it, run the delta check, auto-validate normals, open a call-out
    for criticals and apply reflex rules. Returns {'flag', 'auto_validated', 'reflex': [codes]}."""
    now = now or util.now()
    lab = db.one("SELECT * FROM lab_orders WHERE id = ?", (lab_id,))
    if lab is None:
        raise RuleError("Lab order not found")
    if lab["status"] != "Received":
        raise RuleError("Results can only be entered once the sample is received in the lab")
    test = _test(lab["test_code"])
    patient = db.one("SELECT * FROM patients WHERE id = ?", (lab["patient_id"],))
    low, high = reference_range(test["code"], patient)
    flag = flag_for(value, test, low, high)
    prev = db.one("SELECT result_value FROM lab_orders WHERE patient_id = ? AND test_code = ? AND id <> ?"
                  " AND status IN ('Resulted','Validated') AND result_value IS NOT NULL ORDER BY resulted_at DESC LIMIT 1",
                  (lab["patient_id"], test["code"], lab_id))
    delta = 0
    if prev and prev["result_value"]:
        change = abs(value - prev["result_value"]) / abs(prev["result_value"]) * 100
        delta = 1 if change > test["delta_pct"] else 0
    auto = flag == "N" and not delta
    ts = util.ts(now)
    db.execute(
        "UPDATE lab_orders SET status=?, result_value=?, flag=?, ref_low=?, ref_high=?, delta_flag=?, auto_validated=?,"
        " resulted_at=?, validated_at=?, validated_by=? WHERE id=?",
        ("Validated" if auto else "Resulted", value, flag, low, high, delta, 1 if auto else 0, ts,
         ts if auto else None, "auto-verify" if auto else None, lab_id))
    audit.log(actor, "lab_result", "lab_order", lab_id, {"flag": flag, "delta": delta, "auto_validated": auto})
    if flag in ("LL", "HH"):
        _open_callout(lab, test, value, now)
    reflex = []
    for rule in db.query("SELECT * FROM lab_reflex_rules WHERE trigger_code = ? AND active = 1", (test["code"],)):
        if rule["on_flag"] == flag or (rule["on_flag"] == "ABN" and flag != "N") or (rule["on_flag"] in ("H", "L") and flag == rule["on_flag"] * 2):
            exists = db.scalar("SELECT 1 FROM lab_orders WHERE reflex_of = ? AND test_code = ?", (lab_id, rule["add_code"]))
            if not exists:
                create_lab_order(lab["patient_id"], lab["branch_id"], rule["add_code"], doctor_id=lab["doctor_id"], now=now,
                                 reflex_of=lab_id, status="Received", actor="reflex-rule")
                reflex.append(rule["add_code"])
    return {"flag": flag, "auto_validated": auto, "reflex": reflex}


def validate(lab_id: int, *, actor: str, now: datetime | None = None) -> None:
    lab = db.one("SELECT * FROM lab_orders WHERE id = ?", (lab_id,))
    if lab is None or lab["status"] != "Resulted":
        raise RuleError("Only resulted tests waiting for a pathologist can be validated")
    if lab["flag"] in ("LL", "HH") and db.scalar("SELECT status FROM lab_callouts WHERE lab_order_id = ?", (lab_id,)) == "Open":
        raise RuleError("Call out this critical value to the doctor before validating")
    db.execute("UPDATE lab_orders SET status='Validated', validated_at=?, validated_by=? WHERE id=?",
               (util.ts(now or util.now()), actor, lab_id))
    audit.log(actor, "lab_validate", "lab_order", lab_id)


def _open_callout(lab: dict, test: dict, value: float, now: datetime) -> None:
    p = db.one("SELECT name FROM patients WHERE id = ?", (lab["patient_id"],))
    with db.connect() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO lab_callouts(lab_order_id, created_at) VALUES (?,?)", (lab["id"], util.ts(now)))
        if cur.rowcount == 0:
            return
        conn.execute(
            "INSERT OR IGNORE INTO tasks(kind, title, branch_id, related_type, related_id, due_at, created_at)"
            " VALUES ('followup_call',?,?,?,?,?,?)",
            (f"URGENT critical value: {test['name']} {fmt_value(value)} {test['unit']} for {p['name']}", lab["branch_id"],
             "lab_order", lab["id"], util.ts(now + CALLOUT_ESCALATE_AFTER), util.ts(now)))
    audit.log("system", "critical_value", "lab_order", lab["id"], {"test": test["code"], "value": value})
    notify.notify(title=f"Critical value: {test['name']} {fmt_value(value)} {test['unit']} · {p['name']}",
                  link=f"/diagnostics?tab=lab#lab-{lab['id']}", role=["doctor", "admin"], branch=lab["branch_id"],
                  severity="critical", source_key=f"callout:{lab['id']}")


def call_out(lab_id: int, *, called_to: str, read_back: bool, actor: str, now: datetime | None = None) -> None:
    if not called_to.strip():
        raise RuleError("Write who received the call (name and role)")
    if not read_back:
        raise RuleError("The receiver must read the value back before the call-out is recorded")
    c = db.one("SELECT * FROM lab_callouts WHERE lab_order_id = ?", (lab_id,))
    if c is None or c["status"] != "Open":
        raise RuleError("There is no open call-out for this result")
    ts = util.ts(now or util.now())
    db.execute("UPDATE lab_callouts SET status='CalledOut', called_by=?, called_to=?, read_back=1, called_at=? WHERE id=?",
               (actor, called_to.strip()[:120], ts, c["id"]))
    db.execute("UPDATE tasks SET status='Done' WHERE related_type='lab_order' AND related_id=? AND status='Open'", (lab_id,))
    audit.log(actor, "critical_called_out", "lab_order", lab_id, {"to": called_to.strip()[:120], "read_back": True})


def escalate_callouts(now: datetime) -> int:
    """Critical values not called out within 15 minutes: alert admins and the owner."""
    rows = db.query("SELECT c.*, l.branch_id, t.name AS test_name, p.name AS patient_name FROM lab_callouts c"
                    " JOIN lab_orders l ON l.id = c.lab_order_id JOIN lab_tests t ON t.code = l.test_code"
                    " JOIN patients p ON p.id = l.patient_id WHERE c.status = 'Open' AND c.escalated_at IS NULL AND c.created_at <= ?",
                    (util.ts(now - CALLOUT_ESCALATE_AFTER),))
    for c in rows:
        notify.notify(title=f"Not called out in 15 min: {c['test_name']} · {c['patient_name']}",
                      link=f"/diagnostics?tab=lab#lab-{c['lab_order_id']}", role=["admin", "owner"], branch=c["branch_id"],
                      severity="critical", source_key=f"escalate:{c['id']}")
        db.execute("UPDATE lab_callouts SET escalated_at = ? WHERE id = ?", (util.ts(now), c["id"]))
        audit.log("automation", "critical_escalated", "lab_order", c["lab_order_id"])
    return len(rows)


def fmt_value(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}" if abs(v) >= 1000 else (f"{v:g}")


def lab_kpis(branch: str | None) -> dict:
    f, p = (" AND branch_id = ?", (branch,)) if branch else ("", ())
    c = lambda st: db.scalar(f"SELECT COUNT(*) FROM lab_orders WHERE status = ?{f}", (st, *p))
    crit = db.scalar("SELECT COUNT(*) FROM lab_callouts c JOIN lab_orders l ON l.id = c.lab_order_id WHERE c.status = 'Open'"
                     + (" AND l.branch_id = ?" if branch else ""), p)
    return {"collected": c("Collected"), "received": c("Received"), "resulted": c("Resulted"), "critical": crit}


def patient_results(order_id: int) -> tuple[str, list[tuple[str, str, str, str]]] | None:
    """For the patient app: ('validated', rows) once validated, ('pending', []) before. None if not a lab order.
    Rows are (test, value, unit, reference range) with no interpretation."""
    lab = db.one("SELECT l.*, t.name, t.unit FROM lab_orders l JOIN lab_tests t ON t.code = l.test_code WHERE l.order_id = ?",
                 (order_id,))
    if lab is None:
        return None
    if lab["status"] != "Validated":
        return ("pending", [])
    ref = "" if lab["ref_low"] is None and lab["ref_high"] is None else \
        f"{fmt_value(lab['ref_low']) if lab['ref_low'] is not None else ''} – {fmt_value(lab['ref_high']) if lab['ref_high'] is not None else ''}".strip()
    return ("validated", [(lab["name"], fmt_value(lab["result_value"]), lab["unit"], ref)])


# ---------------------------------------------------------------- radiology

def create_rad_order(patient_id: int, branch_id: str, modality: str, study: str, slot_at: str, *, obstetric: bool = False,
                     doctor_id: int | None = None, actor: str = "system", now: datetime | None = None) -> int:
    if modality not in ("X-ray", "USG", "CT", "MRI"):
        raise RuleError("Choose X-ray, USG, CT or MRI")
    if not study.strip():
        raise RuleError("Write the study, for example 'Chest PA view'")
    if obstetric and modality != "USG":
        raise RuleError("Only ultrasound can be marked obstetric")
    price = {"X-ray": 450, "USG": 1200, "CT": 3500, "MRI": 6500}[modality]
    ts = util.ts(now or util.now())
    order_id = billing.create_order(patient_id, branch_id, "Radiology", f"{modality} {study.strip()}", price, created_at=ts, actor=actor)
    rid = db.execute("INSERT INTO rad_orders(patient_id, branch_id, doctor_id, modality, study, is_obstetric, slot_at, order_id, created_at)"
                     " VALUES (?,?,?,?,?,?,?,?,?)", (patient_id, branch_id, doctor_id, modality, study.strip()[:120],
                                                    1 if obstetric else 0, slot_at, order_id, ts))
    audit.log(actor, "create", "rad_order", rid, {"modality": modality, "obstetric": obstetric})
    return rid


def advance_rad(rad_id: int, *, actor: str, form_f: bool = False, report_text: str = "", now: datetime | None = None) -> str:
    r = db.one("SELECT * FROM rad_orders WHERE id = ?", (rad_id,))
    if r is None:
        raise RuleError("Radiology order not found")
    ts = util.ts(now or util.now())
    if r["status"] == "Scheduled":
        if r["is_obstetric"] and not (form_f or r["form_f_recorded"]):
            raise RuleError("PCPNDT: record that Form F is completed before an obstetric ultrasound is performed")
        db.execute("UPDATE rad_orders SET status='Performed', form_f_recorded=? WHERE id=?",
                   (1 if (form_f or r["form_f_recorded"]) else 0, rad_id))
        new = "Performed"
    elif r["status"] == "Performed":
        if not report_text.strip():
            raise RuleError("Write the report before marking it reported")
        db.execute("UPDATE rad_orders SET status='Reported', report_text=?, reported_by=?, reported_at=? WHERE id=?",
                   (report_text.strip()[:4000], actor, ts, rad_id))
        new = "Reported"
    else:
        raise RuleError(f"This study is already {r['status'].lower()}")
    audit.log(actor, "rad_advance", "rad_order", rad_id, {"to": new})
    return new


# ---------------------------------------------------------------- pharmacy counter

def fefo_batch(drug_code: str, branch_id: str, qty: int, today: str) -> dict | None:
    """First-expiry-first-out: the batch that expires soonest, is not expired and has enough stock."""
    return db.one("SELECT * FROM drug_batches WHERE drug_code = ? AND branch_id = ? AND qty >= ? AND expiry > ?"
                  " ORDER BY expiry, id LIMIT 1", (drug_code, branch_id, qty, today))


def advance_rx(rx_id: int, *, actor: str, now: datetime | None = None) -> str:
    """Pending -> Dispensed (FEFO batches, Schedule register) -> Billed (bill created)."""
    now = now or util.now()
    rx = db.one("SELECT r.*, p.name AS patient_name, d.name AS doctor_name FROM prescriptions r"
                " JOIN patients p ON p.id = r.patient_id LEFT JOIN doctors d ON d.id = r.doctor_id WHERE r.id = ?", (rx_id,))
    if rx is None:
        raise RuleError("Prescription not found")
    items = db.query("SELECT i.*, g.name, g.schedule, g.unit_price FROM prescription_items i JOIN drugs g ON g.code = i.drug_code"
                     " WHERE i.prescription_id = ? ORDER BY i.id", (rx_id,))
    ts = util.ts(now)
    if rx["status"] == "Pending":
        picks = []
        for it in items:
            b = fefo_batch(it["drug_code"], rx["branch_id"], it["qty"], now.date().isoformat())
            if b is None:
                raise RuleError(f"Not enough in-date stock of {it['name']} at this branch")
            picks.append((it, b))
        with db.connect() as conn:
            for it, b in picks:
                conn.execute("UPDATE drug_batches SET qty = qty - ? WHERE id = ?", (it["qty"], b["id"]))
                conn.execute("UPDATE prescription_items SET batch_id = ?, amount = ? WHERE id = ?",
                             (b["id"], it["qty"] * it["unit_price"], it["id"]))
                if it["schedule"]:
                    conn.execute("INSERT INTO schedule_register(item_id, schedule, drug_name, patient_name, prescriber, qty,"
                                 " batch_no, branch_id, dispensed_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (it["id"], it["schedule"], it["name"], rx["patient_name"], rx["doctor_name"], it["qty"],
                                  b["batch_no"], rx["branch_id"], actor, ts))
            conn.execute("UPDATE prescriptions SET status='Dispensed', dispensed_at=?, dispensed_by=? WHERE id=?", (ts, actor, rx_id))
        audit.log(actor, "rx_dispensed", "prescription", rx_id)
        return "Dispensed"
    if rx["status"] == "Dispensed":
        bill_id = billing.create_bill(rx["patient_id"], rx["branch_id"],
                                      [(f"{it['name']} × {it['qty']}", it["qty"] * it["unit_price"]) for it in items],
                                      created_at=ts, actor=actor)
        db.execute("UPDATE prescriptions SET status='Billed', bill_id=? WHERE id=?", (bill_id, rx_id))
        audit.log(actor, "rx_billed", "prescription", rx_id, {"bill_id": bill_id})
        return "Billed"
    raise RuleError("This prescription is already billed")


# ---------------------------------------------------------------- automation sweep

def sweep(now: datetime) -> dict:
    """Runs with the other automations: escalate un-called criticals, and raise bell notifications for
    stuck claims and complaints created by the automations."""
    esc = escalate_callouts(now)
    made = 0
    # Open critical values reach every doctor/admin of the branch, including people added after the
    # result came in (source_key keeps it to one notification per person).
    for c in db.query("SELECT c.lab_order_id, l.branch_id, t.name, l.result_value, t.unit, p.name AS patient_name"
                      " FROM lab_callouts c JOIN lab_orders l ON l.id = c.lab_order_id JOIN lab_tests t ON t.code = l.test_code"
                      " JOIN patients p ON p.id = l.patient_id WHERE c.status = 'Open'"):
        made += notify.notify(title=f"Critical value: {c['name']} {fmt_value(c['result_value'])} {c['unit']} · {c['patient_name']}",
                              link=f"/diagnostics?tab=lab#lab-{c['lab_order_id']}", role=["doctor", "admin"],
                              branch=c["branch_id"], severity="critical", source_key=f"callout:{c['lab_order_id']}")
    for t in db.query("SELECT * FROM tasks WHERE status = 'Open' AND kind IN ('claim_stuck','complaint')"):
        link = "/claims" if t["kind"] == "claim_stuck" else "/tasks#complaints"
        roles = ["admin", "billing"] if t["kind"] == "claim_stuck" else ["admin"]
        made += notify.notify(title=t["title"], link=link, role=roles, branch=t["branch_id"],
                              severity="warn", source_key=f"task:{t['id']}")
    return {"escalated": esc, "notifications": made}


# ---------------------------------------------------------------- demo data

TESTS = [  # code, name, specimen, unit, crit_low, crit_high, delta%, tat, price
    ("K", "Serum potassium", "Serum", "mmol/L", 2.5, 6.0, 25, 2, 250),
    ("NA", "Serum sodium", "Serum", "mmol/L", 120, 160, 10, 2, 250),
    ("PCT", "Procalcitonin", "Serum", "ng/mL", None, None, 200, 4, 1800),
    ("PLT", "Platelet count", "EDTA blood", "/µL", 20000, 1000000, 50, 2, 200),
    ("HCT", "Haematocrit", "EDTA blood", "%", 18, 60, 25, 2, 150),
    ("INR", "INR", "Citrate plasma", "", None, 5.0, 50, 2, 400),
    ("TSH", "TSH", "Serum", "mIU/L", None, None, 200, 24, 450),
    ("FT4", "Free T4", "Serum", "ng/dL", None, None, 200, 24, 450),
    ("HBA1C", "HbA1c", "EDTA blood", "%", None, None, 50, 24, 550),
    ("BCX", "Blood culture × 2", "Blood culture bottles", "", None, None, 999, 72, 1600),
    ("CREAT", "Serum creatinine", "Serum", "mg/dL", None, 10, 50, 4, 200),
]
RANGES = [  # code, sex, age_min, age_max, low, high
    ("K", "A", 0, 120, 3.5, 5.1), ("NA", "A", 0, 120, 135, 145), ("PCT", "A", 0, 120, None, 0.5),
    ("PLT", "A", 0, 120, 150000, 450000), ("HCT", "M", 13, 120, 40, 50), ("HCT", "F", 13, 120, 36, 44),
    ("HCT", "A", 0, 12, 35, 41), ("INR", "A", 0, 120, 0.8, 1.2), ("TSH", "A", 0, 120, 0.4, 4.0),
    ("FT4", "A", 0, 120, 0.8, 1.8), ("HBA1C", "A", 0, 120, 4.0, 5.6), ("CREAT", "M", 13, 120, 0.7, 1.3),
    ("CREAT", "F", 13, 120, 0.6, 1.1), ("CREAT", "A", 0, 12, 0.3, 0.7),
]
DRUGS = [("PCM650", "Paracetamol 650 mg tab", "", 2), ("AMOX500", "Amoxicillin 500 mg cap", "H", 6),
         ("AZI500", "Azithromycin 500 mg tab", "H1", 22), ("ALP05", "Alprazolam 0.5 mg tab", "H1", 4),
         ("MET500", "Metformin 500 mg tab", "", 3), ("TRAM50", "Tramadol 50 mg cap", "H1", 9),
         ("ORS", "ORS sachet", "", 18), ("PAN40", "Pantoprazole 40 mg tab", "H", 7)]
DIAG_TABLES = ["schedule_register", "prescription_items", "prescriptions", "drug_batches", "drugs", "lab_callouts",
               "lab_reflex_rules", "lab_orders", "lab_ranges", "lab_tests", "rad_orders", "beds", "wards", "notifications"]


def wipe() -> None:
    """Clear this module's tables (children first). The seed calls it before wiping core tables,
    because lab, radiology and pharmacy rows point at patients, orders and bills."""
    for t in DIAG_TABLES:
        db.execute(f"DELETE FROM {t}")


def seed_diagnostics(now: datetime) -> dict:
    """Realistic demo data for the Diagnostics, Command Centre and Notifications screens."""
    wipe()
    for row in TESTS:
        db.execute("INSERT INTO lab_tests(code,name,specimen,unit,crit_low,crit_high,delta_pct,tat_hours,price) VALUES (?,?,?,?,?,?,?,?,?)", row)
    for row in RANGES:
        db.execute("INSERT INTO lab_ranges(test_code,sex,age_min,age_max,low,high) VALUES (?,?,?,?,?,?)", row)
    db.execute("INSERT INTO lab_reflex_rules(trigger_code,on_flag,add_code) VALUES ('TSH','H','FT4')")
    for row in DRUGS:
        db.execute("INSERT INTO drugs(code,name,schedule,unit_price) VALUES (?,?,?,?)", row)
    today = now.date()
    for bi, br in enumerate(("A", "B")):
        for di, (code, *_rest) in enumerate(DRUGS):
            db.execute("INSERT INTO drug_batches(drug_code,branch_id,batch_no,expiry,qty) VALUES (?,?,?,?,?)",
                       (code, br, f"{code[:3]}{24 + di}{br}1", (today + timedelta(days=45 + 20 * di)).isoformat(), 40 + 10 * di))
            db.execute("INSERT INTO drug_batches(drug_code,branch_id,batch_no,expiry,qty) VALUES (?,?,?,?,?)",
                       (code, br, f"{code[:3]}{25 + di}{br}2", (today + timedelta(days=300 + 15 * di)).isoformat(), 200))
        for wname, n in (("General ward", 12), ("ICU", 6), ("Maternity", 8)):
            wid = db.execute("INSERT INTO wards(branch_id,name) VALUES (?,?)", (br, wname))
            for k in range(n):
                status = "Occupied" if (k * 7 + bi * 3) % 10 < (8 if wname == "ICU" else 6) else ("Cleaning" if k % 5 == 0 else "Free")
                db.execute("INSERT INTO beds(ward_id,label,status) VALUES (?,?,?)", (wid, f"{wname[:1]}{k + 1:02d}", status))

    pts = db.query("SELECT id, age, gender FROM patients ORDER BY id LIMIT 40")
    docs = {b: [d["id"] for d in db.query("SELECT id FROM doctors WHERE branch_id = ?", (b,))] for b in ("A", "B")}
    if not pts:
        return {"lab_orders": 0}
    plan = [  # patient index, branch, test, minutes ago, target status, value
        (0, "A", "K", 60, "Resulted", 6.4), (1, "A", "PCT", 300, "Resulted", 4.2), (2, "B", "PLT", 60, "Resulted", 62000),
        (2, "B", "HCT", 60, "Resulted", 44), (3, "A", "INR", 46, "Received", None), (4, "A", "TSH", 1440, "Resulted", 8.4),
        (0, "A", "BCX", 1200, "Received", None), (5, "B", "HBA1C", 31, "Collected", None), (6, "B", "NA", 90, "Resulted", 139),
        (7, "A", "CREAT", 120, "Resulted", 0.9), (8, "B", "K", 20, "Ordered", None), (9, "A", "PLT", 15, "Ordered", None),
        (11, "B", "K", 25, "Resulted", 2.3),   # second critical: left open, so "call-out needed" shows
    ]
    made = 0
    for idx, br, code, mins, target, value in plan:
        p = pts[idx % len(pts)]
        when = now - timedelta(minutes=mins)
        lid = create_lab_order(p["id"], br, code, doctor_id=(docs[br] or [None])[0], now=when, actor="seed")
        made += 1
        if target in ("Collected", "Received", "Resulted"):
            advance(lid, actor="seed", now=when + timedelta(minutes=5))
        if target in ("Received", "Resulted"):
            advance(lid, actor="seed", now=when + timedelta(minutes=15))
        if target == "Resulted":
            enter_result(lid, value, actor="seed", now=when + timedelta(minutes=40))
    # One critical already called out (shows the "Called out" state); the other stays open.
    first = db.one("SELECT c.lab_order_id FROM lab_callouts c ORDER BY c.id LIMIT 1")
    if first:
        call_out(first["lab_order_id"], called_to="Dr. on duty, Ward 3 (read back 6.4)", read_back=True, actor="seed",
                 now=now - timedelta(minutes=10))
    for i, (br, modality, study, obst, hrs, target) in enumerate([
            ("A", "X-ray", "Chest PA view", False, -2, "Reported"), ("A", "USG", "Obstetric scan, 20 weeks", True, 1, "Scheduled"),
            ("B", "CT", "Head plain", False, -1, "Performed"), ("B", "MRI", "Lumbar spine", False, 3, "Scheduled")]):
        p = pts[(i + 10) % len(pts)]
        rid = create_rad_order(p["id"], br, modality, study, util.ts(now + timedelta(hours=hrs)), obstetric=obst,
                               doctor_id=(docs[br] or [None])[0], actor="seed", now=now - timedelta(hours=3))
        if target in ("Performed", "Reported"):
            advance_rad(rid, actor="seed", now=now - timedelta(hours=2))
        if target == "Reported":
            advance_rad(rid, actor="seed", report_text="Lung fields clear. No active lesion. Cardiac size normal.", now=now - timedelta(hours=1))
    rx_plan = [("A", [("PCM650", 10), ("AMOX500", 15)], "Pending"), ("A", [("AZI500", 3)], "Dispensed"),
               ("B", [("MET500", 30), ("PAN40", 10)], "Pending"), ("B", [("TRAM50", 6), ("ORS", 4)], "Billed")]
    for i, (br, items, target) in enumerate(rx_plan):
        p = pts[(i + 20) % len(pts)]
        rx = db.execute("INSERT INTO prescriptions(patient_id,branch_id,doctor_id,created_at) VALUES (?,?,?,?)",
                        (p["id"], br, (docs[br] or [None])[0], util.ts(now - timedelta(minutes=20 + 10 * i))))
        for code, qty in items:
            db.execute("INSERT INTO prescription_items(prescription_id,drug_code,qty) VALUES (?,?,?)", (rx, code, qty))
        if target in ("Dispensed", "Billed"):
            advance_rx(rx, actor="seed", now=now - timedelta(minutes=5))
        if target == "Billed":
            advance_rx(rx, actor="seed", now=now - timedelta(minutes=4))
    # OPD tests are billed upfront: put the seeded lab and radiology services on bills, so the demo's
    # "services not on a bill" figure shows only the deliberately unbilled examples from the core seed.
    for oid in [r["order_id"] for r in db.query("SELECT order_id FROM lab_orders UNION ALL SELECT order_id FROM rad_orders")]:
        if oid and db.scalar("SELECT bill_id FROM orders WHERE id = ?", (oid,)) is None:
            billing.add_order_to_bill(oid, actor="seed")
    return {"lab_orders": made, "rad_orders": 4, "prescriptions": len(rx_plan),
            "beds": db.scalar("SELECT COUNT(*) FROM beds")}
