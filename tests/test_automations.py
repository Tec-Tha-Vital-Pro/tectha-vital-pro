from datetime import datetime, timedelta

import pytest

import dataclasses

from app import automations, config, db, messaging, patients, scheduler, util

NOW = datetime(2026, 11, 4, 10, 0, 0)


def _patient(name="Ravi", phone="9876543210", consent=True):
    return patients.find_or_create(name, phone, consent=consent)


def _appt(pid, starts_at, status="Booked", doctor_id=1, branch="B"):
    return db.execute(
        "INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, created_at) VALUES (?,?,?,?,?,?)",
        (pid, doctor_id, branch, util.ts(starts_at), status, util.ts(NOW - timedelta(days=1))))


def _bill(pid, total, paid, created, bill_no="B-1001", branch="A"):
    bid = db.execute("INSERT INTO bills(bill_no, patient_id, branch_id, total, paid, created_at) VALUES (?,?,?,?,?,?)",
                     (bill_no, pid, branch, total, paid, util.ts(created)))
    db.execute("INSERT INTO bill_items(bill_id, description, amount) VALUES (?,?,?)", (bid, "Consultation", total))
    return bid


def _msgs(template=None):
    if template:
        return db.query("SELECT * FROM messages WHERE template = ? ORDER BY id", (template,))
    return db.query("SELECT * FROM messages ORDER BY id")


def test_appointment_reminders_24h_and_2h_idempotent(fresh_db):
    p = _patient()
    a24 = _appt(p["id"], NOW + timedelta(hours=20))
    a2 = _appt(p["id"], NOW + timedelta(hours=1))
    _appt(p["id"], NOW + timedelta(hours=30))  # too far
    _appt(p["id"], NOW + timedelta(hours=5), status="Cancelled")

    r = automations.appointment_reminders(NOW)
    assert r == {"reminder_24h": 1, "reminder_2h": 1, "blocked": 0}
    m24 = _msgs("appt_reminder_24h")
    assert len(m24) == 1 and m24[0]["related_id"] == a24
    assert f"OPD-{a24}" in m24[0]["body"] and "Reply 1 to confirm" in m24[0]["body"] and "Branch B" in m24[0]["body"]
    assert _msgs("appt_reminder_2h")[0]["related_id"] == a2

    assert automations.appointment_reminders(NOW) == {"reminder_24h": 0, "reminder_2h": 0, "blocked": 0}
    assert len(_msgs()) == 2


def test_reminder_blocked_without_consent_is_not_retried(fresh_db):
    p = _patient(consent=False)
    _appt(p["id"], NOW + timedelta(hours=10))
    assert automations.appointment_reminders(NOW)["blocked"] == 1
    assert _msgs()[0]["status"] == "blocked_no_consent"
    assert automations.appointment_reminders(NOW)["blocked"] == 0
    assert len(_msgs()) == 1


def test_feedback_requests(fresh_db):
    p = _patient()
    a = _appt(p["id"], NOW - timedelta(hours=5), status="Visited")
    _appt(p["id"], NOW - timedelta(hours=1), status="Visited")   # too recent
    _appt(p["id"], NOW - timedelta(hours=60), status="Visited")  # too old
    assert automations.feedback_requests(NOW) == {"sent": 1, "blocked": 0}
    assert _msgs("feedback_request")[0]["related_id"] == a
    assert automations.feedback_requests(NOW) == {"sent": 0, "blocked": 0}


def test_dues_stages(fresh_db):
    p = _patient()
    bid = _bill(p["id"], 5000, 1000, NOW - timedelta(days=4))
    _bill(p["id"], 3000, 3000, NOW - timedelta(days=30), bill_no="B-PAID")
    new_bill = _bill(p["id"], 2000, 0, NOW - timedelta(days=1), bill_no="B-NEW")

    assert automations.dues_reminders(NOW)["sent"] == 1  # B-NEW is too young
    db.execute("UPDATE bills SET paid = total WHERE id = ?", (new_bill,))
    body = _msgs("dues_reminder")[0]["body"]
    assert "₹4,000" in body and "https://pay.example.in/tectha/B-1001" in body
    assert "Consultation" not in body   # no health details on the lock screen
    assert automations.dues_reminders(NOW)["sent"] == 0  # stage 2 not due until day 10

    later = NOW + timedelta(days=7)  # age 11 days
    assert automations.dues_reminders(later)["sent"] == 1
    much_later = NOW + timedelta(days=18)  # age 22 days -> stage 3 + call task
    r = automations.dues_reminders(much_later)
    assert r == {"sent": 1, "blocked": 0, "call_tasks": 1}
    assert automations.dues_reminders(much_later + timedelta(days=30))["sent"] == 0
    stages = [r["stage"] for r in db.query("SELECT stage FROM dues_reminders WHERE bill_id = ? ORDER BY stage", (bid,))]
    assert stages == [1, 2, 3]
    assert db.scalar("SELECT COUNT(*) FROM tasks WHERE kind='followup_call' AND related_type='bill'") == 1


def test_send_dues_reminder_manual(fresh_db):
    p = _patient()
    bid = _bill(p["id"], 5000, 1000, NOW)
    mid = automations.send_dues_reminder(bid, NOW)
    assert db.one("SELECT template FROM messages WHERE id = ?", (mid,))["template"] == "dues_reminder"
    paid = _bill(p["id"], 100, 100, NOW, bill_no="B-2")
    with pytest.raises(ValueError):
        automations.send_dues_reminder(paid, NOW)
    with pytest.raises(LookupError):
        automations.send_dues_reminder(9999, NOW)


def test_send_dues_reminder_blocked_records_stage(fresh_db):
    p = _patient(consent=False)
    bid = _bill(p["id"], 5000, 0, NOW - timedelta(days=5))
    with pytest.raises(messaging.SendBlocked):
        automations.send_dues_reminder(bid, NOW)
    assert db.scalar("SELECT MAX(stage) FROM dues_reminders WHERE bill_id = ?", (bid,)) == 1


def test_followup_reminders(fresh_db):
    p = _patient()
    ts = util.ts(NOW)
    f1 = db.execute("INSERT INTO followups(patient_id, branch_id, due_date, reason, created_at) VALUES (?,?,?,?,?)",
                    (p["id"], "A", (NOW.date() + timedelta(days=2)).isoformat(), "review visit", ts))
    db.execute("INSERT INTO followups(patient_id, branch_id, due_date, reason, created_at) VALUES (?,?,?,?,?)",
               (p["id"], "A", (NOW.date() + timedelta(days=10)).isoformat(), "HbA1c test", ts))
    assert automations.followup_reminders(NOW) == {"sent": 1, "blocked": 0}
    assert db.one("SELECT status FROM followups WHERE id = ?", (f1,))["status"] == "Reminded"
    assert automations.followup_reminders(NOW) == {"sent": 0, "blocked": 0}


def test_detect_unbilled_and_stuck_claims(fresh_db):
    p = _patient()
    db.execute("INSERT INTO orders(patient_id, branch_id, dept, description, amount, created_at) VALUES (?,?,?,?,?,?)",
               (p["id"], "A", "Lab", "CBC", 450, util.ts(NOW - timedelta(hours=3))))
    db.execute("INSERT INTO orders(patient_id, branch_id, dept, description, amount, created_at) VALUES (?,?,?,?,?,?)",
               (p["id"], "A", "Lab", "LFT", 600, util.ts(NOW - timedelta(minutes=30))))
    assert automations.detect_unbilled(NOW) == {"tasks_created": 1}
    assert automations.detect_unbilled(NOW) == {"tasks_created": 0}

    def claim(stage, minutes_ago):
        db.execute("INSERT INTO claims(patient_id, branch_id, insurer, amount, stage, stage_changed_at, created_at) VALUES (?,?,?,?,?,?,?)",
                   (p["id"], "A", "Star Health", 100000, stage, util.ts(NOW - timedelta(minutes=minutes_ago)), util.ts(NOW)))
    claim("PreAuthRequested", 90)   # stuck
    claim("PreAuthRequested", 30)   # fine
    claim("FinalSent", 200)         # stuck
    claim("FinalSent", 100)         # fine
    claim("Settled", 1000)          # fine
    assert automations.detect_stuck_claims(NOW) == {"tasks_created": 2}
    assert automations.detect_stuck_claims(NOW) == {"tasks_created": 0}


def test_daily_owner_report_once_after_9(fresh_db, monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, owner_phone="919811100000"))
    p = _patient()
    _bill(p["id"], 2000, 0, NOW - timedelta(days=1))
    assert automations.daily_owner_report(NOW.replace(hour=8)) is None
    mid = automations.daily_owner_report(NOW)
    m = db.one("SELECT * FROM messages WHERE id = ?", (mid,))
    assert m["template"] == "owner_daily_report" and m["patient_id"] is None and m["status"] == "simulated"
    assert "Branch A" in m["body"] and "₹2,000" in m["body"]
    assert automations.daily_owner_report(NOW + timedelta(hours=3)) is None
    assert automations.daily_owner_report(NOW + timedelta(days=1)) is not None


def test_run_all_and_scheduler_tick(fresh_db):
    r = automations.run_all(NOW)
    assert set(r) == {"appointment_reminders", "feedback_requests", "dues_reminders", "followup_reminders",
                      "detect_unbilled", "detect_stuck_claims", "daily_owner_report", "diagnostics_sweep", "news2_escalation"}
    assert scheduler.tick() is not None


def test_owner_report_skipped_without_owner_phone(fresh_db, monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, owner_phone=""))
    assert automations.daily_owner_report(NOW) is None
    assert db.one("SELECT * FROM audit_log WHERE action = 'owner_report_skipped'") is not None


def test_quiet_hours_hold_patient_messages(fresh_db):
    r = automations.run_all(NOW.replace(hour=22))
    assert r["appointment_reminders"].startswith("quiet hours") and r["dues_reminders"].startswith("quiet hours")
    assert isinstance(r["detect_stuck_claims"], dict)   # staff alerts still run


def test_each_automation_can_be_switched_off(fresh_db):
    automations.set_enabled("dues_reminders", False)
    assert automations.run_all(NOW)["dues_reminders"] == "off"
    automations.set_enabled("dues_reminders", True)
    assert automations.run_all(NOW)["dues_reminders"] != "off"


def test_scheduler_logs_errors(fresh_db, monkeypatch):
    def boom(now):
        raise RuntimeError("billing sync down")
    monkeypatch.setattr(automations, "run_all", boom)
    assert scheduler.tick() is None
    row = db.one("SELECT * FROM audit_log WHERE action = 'automation_error'")
    assert "billing sync down" in row["detail"]


def test_scheduler_start_twice_single_thread(fresh_db, monkeypatch):
    monkeypatch.setattr(automations, "run_all", lambda now: {})
    scheduler.start(3600)
    t1 = scheduler._thread
    scheduler.start(3600)
    assert scheduler._thread is t1 and scheduler.is_running()
    scheduler.stop()
    assert not scheduler.is_running()


def test_old_bill_does_not_get_stages_back_to_back(fresh_db):
    p = _patient()
    _bill(p["id"], 3000, 0, NOW - timedelta(days=40))          # e.g. imported late
    assert automations.dues_reminders(NOW)["sent"] == 1
    assert automations.dues_reminders(NOW + timedelta(minutes=1))["sent"] == 0
    assert automations.dues_reminders(NOW + timedelta(days=6))["sent"] == 1
