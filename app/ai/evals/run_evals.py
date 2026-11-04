"""Run the receptionist eval set against the real Claude API.

    python -m app.ai.evals.run_evals --dry-run     # validate cases.jsonl only (free)
    python -m app.ai.evals.run_evals               # real API calls: costs money, needs ANTHROPIC_API_KEY

Checks are deterministic, on the structured fields: intent, urgency, language, doctor/slot inside
the context, reply regex rules. A temporary database with two branches is used; nothing real is touched.
"""
import argparse
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

CASES = Path(__file__).with_name("cases.jsonl")
INTENTS = {"book_appointment", "reschedule", "cancel", "ask_info", "billing_question", "report_question",
           "feedback", "emergency", "complaint", "other"}
URGENCIES = {"normal", "urgent", "emergency"}
LANGS = {"en", "hi", "ta", "te", "kn", "ml", "mr", "bn", "gu", "hi-Latn"}
NOW = datetime(2026, 11, 4, 10, 0, 0)
KNOWN_PHONE, NEW_PHONE = "919812345678", "919876500000"


def load() -> list[dict]:
    cases, errors = [], []
    for i, line in enumerate(CASES.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON ({e})")
            continue
        e = c.get("expect", {})
        for key, allowed in (("intent", INTENTS), ("urgency", URGENCIES), ("language", LANGS)):
            bad = set(e.get(key, [])) - allowed
            if not e.get(key) or bad:
                errors.append(f"line {i} ({c.get('id')}): expect.{key} missing or invalid {sorted(bad)}")
        for pat in e.get("reply_must_not_match", []):
            try:
                re.compile(pat)
            except re.error as err:
                errors.append(f"line {i} ({c.get('id')}): bad regex {pat!r}: {err}")
        if not c.get("id") or not c.get("text"):
            errors.append(f"line {i}: id and text are required")
        cases.append(c)
    ids = [c.get("id") for c in cases]
    if len(ids) != len(set(ids)):
        errors.append("duplicate case ids")
    if len(cases) < 30:
        errors.append(f"only {len(cases)} cases; need at least 30")
    if errors:
        raise SystemExit("cases.jsonl is invalid:\n  " + "\n  ".join(errors))
    return cases


def _setup_db():
    from app import db, patients
    db.set_path(str(Path(tempfile.mkdtemp()) / "eval.db"))
    db.init_db()
    db.execute("INSERT INTO branches(id, name) VALUES ('A','Branch A'), ('B','Branch B')")
    db.execute("INSERT INTO doctors(name, specialty, branch_id, fee) VALUES"
               " ('Dr. S. Menon','Orthopaedics','B',600), ('Dr. R. Iyer','General Medicine','A',500),"
               " ('Dr. K. Rao','Paediatrics','A',500), ('Dr. M. Shah','Obstetrics & Gynaecology','B',700)")
    db.set_setting("hospital_name", "Demo Hospital")
    p = patients.find_or_create("Ramesh Kumar", KNOWN_PHONE, consent=True)
    db.execute("INSERT INTO appointments(patient_id, doctor_id, branch_id, starts_at, status, token_no, created_at)"
               " VALUES (?,1,'B','2026-11-05 11:30:00','Booked',3,'2026-11-03 10:00:00')", (p["id"],))
    db.execute("INSERT INTO bills(bill_no, patient_id, branch_id, total, paid, created_at)"
               " VALUES ('B-0001', ?, 'B', 2650, 1000, '2026-11-01 12:00:00')", (p["id"],))


def check(case: dict, out, ctx) -> list[str]:
    e, fails = case["expect"], []
    if out.intent not in e["intent"]:
        fails.append(f"intent {out.intent} not in {e['intent']}")
    if out.urgency not in e["urgency"]:
        fails.append(f"urgency {out.urgency} not in {e['urgency']}")
    if out.language not in e["language"]:
        fails.append(f"language {out.language} not in {e['language']}")
    if out.doctor_id is not None and out.doctor_id not in ctx["doctors"]:
        fails.append(f"doctor_id {out.doctor_id} not in context")
    if out.slot is not None and out.doctor_id in ctx["slots"] and out.slot not in ctx["slots"][out.doctor_id]:
        fails.append(f"slot {out.slot} not a free slot")
    for pat in e.get("reply_must_not_match", []):
        if re.search(pat, out.reply):
            fails.append(f"reply matches forbidden {pat!r}")
    need = e.get("reply_must_contain_any")
    if need and not any(n.lower() in out.reply.lower() for n in need):
        fails.append(f"reply lacks any of {need}")
    if "needs_human" in e and out.needs_human != e["needs_human"]:
        fails.append(f"needs_human {out.needs_human} != {e['needs_human']}")
    if len(out.reply.split()) > 90:
        fails.append(f"reply too long ({len(out.reply.split())} words)")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="validate cases.jsonl without calling the API")
    ap.add_argument("--only", help="run one case id")
    args = ap.parse_args()
    cases = load()
    if args.dry_run:
        print(f"cases.jsonl OK: {len(cases)} cases")
        return 0
    from app.ai import client as ai
    from app.ai import receptionist
    if not (__import__("os").environ.get("ANTHROPIC_API_KEY") or __import__("os").environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise SystemExit("Set ANTHROPIC_API_KEY to run evals (this makes real, billed API calls).")
    _setup_db()
    passed = 0
    for c in cases:
        if args.only and c["id"] != args.only:
            continue
        ctx = receptionist.build_context(KNOWN_PHONE if c.get("known_patient") else NEW_PHONE, NOW)
        try:
            out = receptionist.ask_model(ctx, c["text"])
            fails = check(c, out, ctx)
        except ai.AIError as e:
            fails = [f"AI error: {e}"]
        passed += not fails
        print(f"{'PASS' if not fails else 'FAIL'}  {c['id']}" + ("" if not fails else "  - " + "; ".join(fails)))
    total = 1 if args.only else len(cases)
    print(f"\n{passed}/{total} passed  (model {ai.model()})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
