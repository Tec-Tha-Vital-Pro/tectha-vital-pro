"""Claims document checker: claim files missing a document the insurer or TPA needs."""
from datetime import datetime

from app import db, util
from app.agents import Agent, register

OPEN_STAGES = ("PreAuthRequested", "PreAuthApproved", "FinalSent")


def run(now: datetime) -> list[dict]:
    out = []
    marks = ",".join("?" * len(OPEN_STAGES))
    for c in db.query(f"SELECT c.*, p.name AS patient FROM claims c JOIN patients p ON p.id = c.patient_id"
                      f" WHERE c.stage IN ({marks})", OPEN_STAGES):
        needed = [r["document"] for r in db.query(
            "SELECT document FROM payer_checklists WHERE insurer = ? OR insurer = '*' ORDER BY document", (c["insurer"],))]
        have = {r["document"] for r in db.query("SELECT document FROM claim_documents WHERE claim_id = ?", (c["id"],))}
        missing = [d for d in needed if d not in have]
        if not missing:
            continue
        out.append({
            "key": f"claim:{c['id']}", "severity": "high" if c["stage"] == "FinalSent" else "medium",
            "title": f"Claim for {c['patient']} ({c['insurer']}) is missing {len(missing)} document{'s' if len(missing) > 1 else ''}",
            "evidence": {"claim_id": c["id"], "insurer": c["insurer"], "stage": c["stage"], "missing": missing,
                         "amount": c["amount"]},
            "suggested_action": "Collect and upload: " + ", ".join(missing) + ".",
            "action": {"type": "task", "kind": "followup_call", "related_type": "claim", "related_id": c["id"],
                       "title": f"Collect claim documents for {c['patient']}: {', '.join(missing)}"},
            "amount": c["amount"], "branch_id": c["branch_id"],
        })
    return out


register(Agent("claims_docs", "Claims document checker",
               "Checks every open insurance or TPA claim against the payer's document list.", 30, run))
