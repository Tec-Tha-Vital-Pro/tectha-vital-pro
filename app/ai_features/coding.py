"""Clinical coding assistant for claims.

Suggests ICD-10 diagnosis codes and PM-JAY package hints, each with the exact sentence from the
patient's record that supports it. A coder accepts, edits or rejects; nothing is submitted to a payer
automatically. With AI on, Claude reads the record; with AI off, a small keyword map is used.
"""
import json
from typing import Literal

from pydantic import BaseModel, Field

from app import audit, db, util
from app.ai import client as ai
from app.ai_features import governance

CODING_V1 = (
    "You suggest clinical codes for an Indian hospital insurance claim. You are decision support: a certified coder "
    "decides. Use only the record text given. For each suggestion give the ICD-10 code, a short label, and the exact "
    "sentence from the record that supports it (copy it word for word). If the record does not support a code, do not "
    "suggest it. Never invent diagnoses or procedures. At most five suggestions."
)

# keyword -> (system, code, label). PM-JAY package codes vary by state and HBP version, so they are labelled as hints.
RULES = [
    ("dengue", ("ICD-10", "A97.9", "Dengue, unspecified")),
    ("typhoid", ("ICD-10", "A01.0", "Typhoid fever")),
    ("pneumonia", ("ICD-10", "J18.9", "Pneumonia, unspecified organism")),
    ("sepsis", ("ICD-10", "A41.9", "Sepsis, unspecified organism")),
    ("diabetes", ("ICD-10", "E11.9", "Type 2 diabetes mellitus without complications")),
    ("hba1c", ("ICD-10", "E11.9", "Type 2 diabetes mellitus without complications")),
    ("hypertension", ("ICD-10", "I10", "Essential (primary) hypertension")),
    ("knee replacement", ("ICD-10", "M17.9", "Osteoarthritis of knee, unspecified")),
    ("appendic", ("ICD-10", "K35.80", "Acute appendicitis")),
    ("caesarean", ("ICD-10", "O82", "Delivery by caesarean section")),
    ("hyperkalaemia", ("ICD-10", "E87.5", "Hyperkalaemia")),
    ("potassium", ("ICD-10", "E87.5", "Hyperkalaemia (check the value supports it)")),
    ("thyroid", ("ICD-10", "E03.9", "Hypothyroidism, unspecified (check TSH/T4)")),
    ("tsh", ("ICD-10", "E03.9", "Hypothyroidism, unspecified (check TSH/T4)")),
]


class Suggestion(BaseModel):
    system: Literal["ICD-10", "PM-JAY package hint"]
    code: str
    label: str
    evidence: str = Field(description="Exact sentence copied from the record")


class Suggestions(BaseModel):
    items: list[Suggestion]


def record_text(claim: dict) -> list[str]:
    """Sentences from the patient's record around this claim: orders, lab tests and bill lines."""
    pid = claim["patient_id"]
    lines = [f"{o['dept']}: {o['description']}" for o in
             db.query("SELECT dept, description FROM orders WHERE patient_id = ? ORDER BY id DESC LIMIT 30", (pid,))]
    lines += [f"Bill item: {i['description']}" for i in db.query(
        "SELECT bi.description FROM bill_items bi JOIN bills b ON b.id = bi.bill_id WHERE b.patient_id = ? ORDER BY bi.id DESC LIMIT 30",
        (pid,))]
    lines += [f"Lab: {r['name']}" for r in db.query(
        "SELECT t.name FROM lab_orders l JOIN lab_tests t ON t.code = l.test_code WHERE l.patient_id = ? LIMIT 20", (pid,))]
    return lines


def _rules(lines: list[str]) -> list[dict]:
    out, seen = [], set()
    for line in lines:
        low = line.lower()
        for kw, (system, code, label) in RULES:
            if kw in low and code not in seen:
                seen.add(code)
                out.append({"system": system, "code": code, "label": label, "evidence": line})
    return out[:5]


def suggest(claim_id: int, actor: str, *, client=None) -> dict:
    claim = db.one("SELECT * FROM claims WHERE id = ?", (claim_id,))
    if claim is None:
        raise LookupError("Claim not found")
    lines = record_text(claim)
    if not lines:
        raise ValueError("There is nothing in this patient's record to code from yet.")
    if ai.enabled() or client is not None:
        try:
            res = ai.structured(system=CODING_V1, user="Record:\n" + "\n".join(lines), output=Suggestions,
                                effort="medium", max_tokens=1500, client=client)
            # Keep only suggestions whose evidence really appears in the record.
            items = [s.model_dump() for s in res.items if any(s.evidence.strip() and s.evidence.strip() in ln for ln in lines)]
            key = "coding_claude"
        except ai.AIError as e:
            audit.log(actor, "ai_error", "coding", claim_id, str(e))
            items, key = _rules(lines), "coding_rules"
    else:
        items, key = _rules(lines), "coding_rules"
    sid = db.execute("INSERT INTO coding_suggestions(claim_id, suggestions, model_key, created_at) VALUES (?,?,?,?)",
                     (claim_id, json.dumps(items, ensure_ascii=False), key, util.ts(util.now())))
    governance.log_decision("coding_assistant", key, "suggested", actor, output=items, subject_type="claim",
                            subject_id=claim_id, input_summary=f"{len(lines)} record lines")
    return {"id": sid, "items": items, "model_key": key}


def decide(suggestion_id: int, accepted_codes: list[str], actor: str) -> str:
    s = db.one("SELECT * FROM coding_suggestions WHERE id = ?", (suggestion_id,))
    if s is None:
        raise LookupError("Suggestion not found")
    if s["status"] != "Proposed":
        raise ValueError("This suggestion was already decided.")
    proposed = [i["code"] for i in json.loads(s["suggestions"])]
    codes = [c.strip().upper() for c in accepted_codes if c.strip()]
    status = "Accepted" if codes else "Rejected"
    db.execute("UPDATE coding_suggestions SET status=?, accepted_codes=?, decided_by=?, decided_at=? WHERE id=?",
               (status, json.dumps(codes), actor, util.ts(util.now()), suggestion_id))
    decision = "rejected" if not codes else ("accepted" if sorted(codes) == sorted(proposed) else "edited")
    governance.log_decision("coding_assistant", s["model_key"], decision, actor, output=codes, subject_type="claim",
                            subject_id=s["claim_id"])
    audit.log(actor, "coding_" + decision, "claim", s["claim_id"], {"codes": codes})
    return status


def latest_for_claims(claim_ids: list[int]) -> dict[int, dict]:
    if not claim_ids:
        return {}
    q = ",".join("?" * len(claim_ids))
    out = {}
    for r in db.query(f"SELECT * FROM coding_suggestions WHERE claim_id IN ({q}) ORDER BY id", tuple(claim_ids)):
        r["items"] = json.loads(r["suggestions"])
        r["accepted"] = json.loads(r["accepted_codes"]) if r["accepted_codes"] else []
        out[r["claim_id"]] = r
    return out
