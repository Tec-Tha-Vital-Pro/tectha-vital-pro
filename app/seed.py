"""Demo data for Tec Tha Care Connect: two branches, a month of activity, all relative to now.

Run:  python -m app.seed      (wipes all data rows except staff logins and settings, then rebuilds)
"""
import random
from datetime import datetime, timedelta

from app import billing, db, util

FIRST = ["Aarav", "Priya", "Ramesh", "Anita", "Mohammed", "Sunita", "Vikram", "Lakshmi", "Arjun", "Fatima",
         "Rahul", "Kavita", "Suresh", "Meena", "Gopal", "Neha", "Harish", "Shabana", "Deepak", "Asha",
         "Imran", "Geeta", "Anil", "Savita", "Ravi", "Pooja", "Kiran", "Divya", "Manoj", "Rekha",
         "Sanjay", "Nisha", "Ajay", "Farhan", "Lata", "Prakash", "Swati", "Venkat", "Joseph", "Mary"]
LAST = ["Sharma", "Kumar", "Desai", "Reddy", "Singh", "Iyer", "Patel", "Shaikh", "Verma", "Joshi",
        "Nair", "Gupta", "Rao", "Kapoor", "Menon", "Khan", "Jain", "Pillai", "Ali", "Sinha",
        "Kulkarni", "Das", "Bhat", "Shetty", "Mishra", "Chopra", "Thomas", "Fernandes", "Naidu", "Ghosh"]
DOCTORS = [("Dr. R. Iyer", "General Medicine", "A", 500), ("Dr. P. Sharma", "Obstetrics & Gynaecology", "A", 700),
           ("Dr. A. Khan", "Cardiology", "A", 900), ("Dr. S. Menon", "Orthopaedics", "B", 600),
           ("Dr. K. Reddy", "Paediatrics", "B", 500), ("Dr. N. Desai", "Dermatology", "B", 600)]
NEEDS = ["Knee pain", "Fever", "Pregnancy check-up", "Full body check-up", "Diabetes review", "Chest pain",
         "Child vaccination", "Skin allergy", "Back pain", "Thyroid test", "BP check", "Physiotherapy"]
SOURCES = [("WhatsApp", 30), ("Phone call", 22), ("Website form", 12), ("Google", 12), ("Facebook ad", 8),
           ("Instagram ad", 5), ("Practo", 6), ("Walk-in", 3), ("Referral", 2)]
TESTS = [("CBC", 350), ("Lipid profile", 650), ("HbA1c", 450), ("X-ray", 850), ("ECG", 300),
         ("Thyroid profile", 600), ("Ultrasound", 1200), ("Urine routine", 200)]
INSURERS = ["Star Health", "HDFC ERGO", "Care Health", "Niva Bupa", "ICICI Lombard", "PM-JAY"]
MODES = ["UPI"] * 11 + ["Card"] * 4 + ["Cash"] * 4 + ["Insurance"]

WIPE = ["audit_log", "messages", "feedback", "followups", "tasks", "claims", "orders", "dues_reminders",
        "payments", "bill_items", "bills", "appointments", "leads", "doctors", "patients"]


def _w(rng: random.Random, pairs):
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs])[0]


def seed(now: datetime | None = None) -> dict:
    now = (now or util.now()).replace(microsecond=0)
    rng = random.Random(42)
    db.init_db()
    for t in WIPE:
        db.execute(f"DELETE FROM {t}")
    db.execute("INSERT INTO branches(id, name) VALUES ('A','Branch A'), ('B','Branch B') "
               "ON CONFLICT(id) DO UPDATE SET name = excluded.name")
    db.set_setting("hospital_name", "Your Hospital")

    doctors = {"A": [], "B": []}
    for name, spec, br, fee in DOCTORS:
        did = db.execute("INSERT INTO doctors(name, specialty, branch_id, fee) VALUES (?,?,?,?)", (name, spec, br, fee))
        doctors[br].append({"id": did, "fee": fee, "name": name})

    used_phones: set[str] = set()

    def new_phone() -> str:
        while True:
            ph = "91" + rng.choice("987") + "".join(rng.choice("0123456789") for _ in range(9))
            if ph not in used_phones:
                used_phones.add(ph)
                return ph

    def new_patient(created: datetime, name: str | None = None, phone: str | None = None) -> int:
        name = name or f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        phone = phone or new_phone()
        consent = rng.random() < 0.9
        pid = db.execute(
            "INSERT INTO patients(name, phone, age, gender, consent_messages, consent_at, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, phone, rng.randint(2, 80), rng.choice(["M", "F"]), int(consent), util.ts(created) if consent else None, util.ts(created)))
        db.execute("UPDATE patients SET uid = ? WHERE id = ?", (util.patient_uid(pid), pid))
        return pid

    pool = [new_patient(now - timedelta(days=rng.randint(40, 400))) for _ in range(80)]
    counts = {"bills": 0, "payments": 0}

    def bill_visit(pid: int, br: str, doc: dict, when: datetime, pay: str = "full") -> int:
        items = [("Consultation", doc["fee"])]
        for t in rng.sample(TESTS, rng.choice([0, 0, 1, 1, 2])):
            items.append(t)
        bid = billing.create_bill(pid, br, items, created_at=when, actor="seed")
        counts["bills"] += 1
        total = sum(a for _, a in items)
        if pay == "full":
            billing.record_payment(bid, total, rng.choice(MODES), paid_at=when + timedelta(minutes=rng.randint(5, 50)), actor="seed")
            counts["payments"] += 1
        elif pay == "partial":
            billing.record_payment(bid, total // 2, rng.choice(MODES), paid_at=when + timedelta(minutes=20), actor="seed")
            counts["payments"] += 1
        return bid

    # --- appointments: past 30 days, earlier today, next 3 days
    token: dict[tuple, int] = {}
    n_appts = 0
    start_day = (now - timedelta(days=30)).date()
    for offset in range(0, 34):
        day = start_day + timedelta(days=offset)
        for br, per_day in (("A", 10), ("B", 7)):
            n = per_day if day.weekday() != 6 else per_day // 2
            for _ in range(n + rng.randint(-2, 2)):
                doc = rng.choice(doctors[br])
                when = datetime(day.year, day.month, day.day, rng.randint(9, 18), rng.choice([0, 15, 30, 45]))
                key = (doc["id"], day)
                token[key] = token.get(key, 0) + 1
                pid = rng.choice(pool)
                if when < now - timedelta(hours=1):
                    r = rng.random()
                    status = "Visited" if r < 0.78 else "NoShow" if r < 0.90 else "Cancelled"
                    sent = util.ts(when - timedelta(hours=24))
                    fb = util.ts(when + timedelta(hours=3)) if status == "Visited" and when < now - timedelta(days=1) else None
                    db.execute(
                        "INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, token_no, source,"
                        " reminder_24h_sent_at, reminder_2h_sent_at, feedback_sent_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, doc["id"], br, util.ts(when), status, token[key], "Front desk", sent,
                         util.ts(when - timedelta(hours=2)), fb, util.ts(when - timedelta(days=2))))
                    if status == "Visited" and when >= now - timedelta(days=14):
                        bill_visit(pid, br, doc, when + timedelta(minutes=30), "full" if rng.random() < 0.93 else "partial")
                else:
                    if when > now + timedelta(days=3):
                        continue
                    db.execute(
                        "INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, token_no, source, created_at)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (pid, doc["id"], br, util.ts(when), rng.choice(["Booked", "Booked", "Confirmed"]), token[key],
                         rng.choice(["WhatsApp", "Front desk", "Website form"]), util.ts(now - timedelta(days=1))))
                n_appts += 1
    # guaranteed reminder cases: one in ~90 min, two in ~24 h
    for delta, br in ((timedelta(minutes=90), "B"), (timedelta(hours=24), "A"), (timedelta(hours=23, minutes=30), "B")):
        doc = doctors[br][0]
        db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, source, created_at) VALUES (?,?,?,?,?,?,?)",
                   (rng.choice(pool), doc["id"], br, util.ts(now + delta), "Booked", "WhatsApp", util.ts(now - timedelta(days=1))))
        n_appts += 1

    # --- leads: last 30 days, ~12 per day
    n_leads = 0
    for d in range(30, -1, -1):
        for _ in range(12 + rng.randint(-3, 3)):
            created = now - timedelta(days=d, minutes=rng.randint(0, 600))
            if created > now:
                created = now - timedelta(minutes=rng.randint(1, 120))
            src = _w(rng, SOURCES)
            br = rng.choice("AAAB" if src != "Practo" else "AB")
            r = rng.random()
            if d == 0:
                status = "New" if r < 0.3 else "Contacted" if r < 0.6 else "Booked"
            else:
                status = "Converted" if r < 0.38 else "Booked" if r < 0.55 else "Contacted" if r < 0.78 else "Lost" if r < 0.9 else "New"
            q = rng.random()
            reply = rng.randint(20, 300) if q < 0.85 else rng.randint(301, 1800) if q < 0.93 else None
            if status in ("Contacted", "Booked", "Converted") and reply is None:
                reply = rng.randint(60, 900)
            name, phone = f"{rng.choice(FIRST)} {rng.choice(LAST)}", new_phone()
            pid = None
            if status in ("Booked", "Converted"):
                pid = new_patient(created, name, phone)
                visit = created + timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 4))
                doc = rng.choice(doctors[br])
                if status == "Converted" and visit < now:
                    db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, source,"
                               " reminder_24h_sent_at, reminder_2h_sent_at, feedback_sent_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                               (pid, doc["id"], br, util.ts(visit), "Visited", src, util.ts(visit - timedelta(hours=24)),
                                util.ts(visit - timedelta(hours=2)), util.ts(visit + timedelta(hours=3)), util.ts(created)))
                    bill_visit(pid, br, doc, visit + timedelta(minutes=30))
                    n_appts += 1
                elif status == "Converted":
                    status = "Booked"
                if status == "Booked":
                    future = now + timedelta(days=rng.randint(0, 2), hours=rng.randint(2, 30))
                    db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, source, created_at)"
                               " VALUES (?,?,?,?,?,?,?)", (pid, doc["id"], br, util.ts(future), "Booked", src, util.ts(created)))
                    n_appts += 1
            db.execute("INSERT INTO leads(name, phone, need, source, branch_id, status, first_reply_seconds, patient_id, created_at, updated_at)"
                       " VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (name, phone, rng.choice(NEEDS), src, br, status, reply, pid, util.ts(created), util.ts(created)))
            n_leads += 1

    # --- missed calls today, not yet returned
    for i, mins in enumerate((25, 9)):
        created = now - timedelta(minutes=mins)
        name, phone = f"{rng.choice(FIRST)} {rng.choice(LAST)}", new_phone()
        lid = db.execute("INSERT INTO leads(name, phone, need, source, branch_id, status, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?,?,?)", (name, phone, "Missed call", "Phone call", "AB"[i], "New", util.ts(created), util.ts(created)))
        db.execute("INSERT INTO tasks(kind, title, branch_id, related_type, related_id, due_at, created_at) VALUES (?,?,?,?,?,?,?)",
                   ("missed_call", f"Call back {name} (+{phone})", "AB"[i], "lead", lid, util.ts(created + timedelta(minutes=15)), util.ts(created)))

    # --- older unpaid bills
    for age, br, items in ((4, "A", [("IPD room charges (2 days)", 6000), ("Medicines", 1650)]),
                           (12, "B", [("Day-care procedure", 12800)]),
                           (25, "A", [("Physiotherapy package (10 sessions)", 7500)]),
                           (40, "B", [("Surgery balance after insurance", 26300)]),
                           (40, "A", [("IPD room charges (5 days)", 15000), ("Pharmacy", 4200), ("Lab", 2900)])):
        when = now - timedelta(days=age, hours=3)
        bid = billing.create_bill(rng.choice(pool), br, items, created_at=when, actor="seed")
        counts["bills"] += 1
        if age >= 12:
            db.execute("INSERT INTO dues_reminders(bill_id, stage, sent_at) VALUES (?,?,?)", (bid, 1, util.ts(when + timedelta(days=3))))
        if age >= 25:
            db.execute("INSERT INTO dues_reminders(bill_id, stage, sent_at) VALUES (?,?,?)", (bid, 2, util.ts(when + timedelta(days=10))))

    # --- service orders: most billed, a few not
    for hours, br, dept, desc, amt in ((3, "A", "Lab", "CBC + LFT", 1850), (5, "B", "Ward", "2 extra bed-days", 6000),
                                       (26, "A", "Pharmacy", "Dressing kit", 420)):
        billing.create_order(rng.choice(pool), br, dept, desc, amt, created_at=now - timedelta(hours=hours), actor="seed")
    for _ in range(6):
        oid = billing.create_order(rng.choice(pool), rng.choice("AB"), "Lab", rng.choice(TESTS)[0], rng.choice(TESTS)[1],
                                   created_at=now - timedelta(days=rng.randint(1, 10)), actor="seed")
        billing.add_order_to_bill(oid, actor="seed")

    # --- insurance claims, one or more in each stage
    for stage, age, br, amt in (("PreAuthRequested", timedelta(minutes=95), "A", 185000),
                                ("PreAuthRequested", timedelta(minutes=20), "B", 62000),
                                ("PreAuthApproved", timedelta(hours=6), "B", 94000),
                                ("PreAuthApproved", timedelta(days=1), "A", 30000),
                                ("FinalSent", timedelta(hours=4, minutes=30), "A", 128000),
                                ("FinalSent", timedelta(minutes=50), "B", 54000),
                                ("Settled", timedelta(days=2), "B", 71000),
                                ("Denied", timedelta(days=5), "A", 43000)):
        billing.create_claim(rng.choice(pool), br, rng.choice(INSURERS), amt, stage=stage, created_at=now - age, actor="seed")

    # --- follow-ups due in the next 3 days
    for d in range(0, 4):
        for _ in range(2):
            br = rng.choice("AB")
            db.execute("INSERT INTO followups(patient_id, branch_id, due_date, reason, created_at) VALUES (?,?,?,?,?)",
                       (rng.choice(pool), br, (now + timedelta(days=d)).date().isoformat(),
                        rng.choice(["Review visit after surgery", "HbA1c re-test", "Antenatal visit", "BP review", "Physiotherapy review"]),
                        util.ts(now - timedelta(days=10))))

    # --- feedback
    visited = db.query("SELECT id, patient_id, branch_id, starts_at FROM appointments WHERE status='Visited' ORDER BY starts_at DESC LIMIT 12")
    for i, a in enumerate(visited):
        score = 2 if i == 3 else rng.choice([4, 5, 5, 5])
        fid = db.execute("INSERT INTO feedback(patient_id, appointment_id, score, comment, escalated, created_at) VALUES (?,?,?,?,?,?)",
                         (a["patient_id"], a["id"], score, "Waited over an hour at billing" if score <= 3 else None,
                          int(score <= 3), util.ts(util.parse(a["starts_at"]) + timedelta(hours=4))))
        if score <= 3:
            db.execute("INSERT INTO tasks(kind, title, branch_id, related_type, related_id, due_at, created_at) VALUES (?,?,?,?,?,?,?)",
                       ("complaint", "Call patient about low score (2/5): billing wait", a["branch_id"], "feedback", fid,
                        util.ts(now + timedelta(hours=4)), util.ts(now - timedelta(hours=2))))

    summary = {
        "patients": db.scalar("SELECT COUNT(*) FROM patients"),
        "doctors": db.scalar("SELECT COUNT(*) FROM doctors"),
        "leads": n_leads + 2,
        "appointments": db.scalar("SELECT COUNT(*) FROM appointments"),
        "bills": db.scalar("SELECT COUNT(*) FROM bills"),
        "payments": db.scalar("SELECT COUNT(*) FROM payments"),
        "unbilled_orders": db.scalar("SELECT COUNT(*) FROM orders WHERE bill_id IS NULL"),
        "claims": db.scalar("SELECT COUNT(*) FROM claims"),
        "followups": db.scalar("SELECT COUNT(*) FROM followups"),
        "feedback": db.scalar("SELECT COUNT(*) FROM feedback"),
    }
    return summary


if __name__ == "__main__":
    result = seed()
    print("Seeded demo data for Tec Tha Care Connect:")
    for k, v in result.items():
        print(f"  {k:16} {v}")
