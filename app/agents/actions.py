"""Decisions on findings. Accept runs the finding's one safe action; dismiss records why not."""
import json
from datetime import timedelta

from pydantic import BaseModel

from app import audit, billing, db, util
from app.ai import client as ai
from app.ai import insights

OPEN = "open"


class FindingSummary(BaseModel):
    summary: str


SUMMARY_PROMPT = (
    "You explain one finding from a hospital operations agent to a busy hospital manager in India. "
    "Write two or three short, plain sentences: what was found, why it matters, and what to check. "
    "Use only facts and numbers present in the finding's JSON; never add numbers, names or medical advice. "
    "The manager decides; you do not."
)


def get(finding_id: int) -> dict | None:
    f = db.one("SELECT * FROM findings WHERE id = ?", (finding_id,))
    if f:
        f["evidence_obj"] = json.loads(f["evidence"])
        f["action_obj"] = json.loads(f["action"]) if f["action"] else None
    return f


def _decide(f: dict, status: str, actor: str, note: str | None) -> None:
    db.execute("UPDATE findings SET status = ?, decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
               (status, actor, util.ts(util.now()), note, f["id"]))


def accept(finding_id: int, actor: str) -> str:
    """Run the finding's action and mark it accepted. Returns what was done, in plain words."""
    f = get(finding_id)
    if f is None:
        raise LookupError("Finding not found")
    if f["status"] != OPEN:
        raise ValueError("This finding was already decided.")
    a = f["action_obj"]
    if a is None:
        done = "Marked as reviewed."
    elif a["type"] == "add_order_to_bill":
        bill_id = billing.add_order_to_bill(int(a["order_id"]), actor=actor)
        bill_no = db.scalar("SELECT bill_no FROM bills WHERE id = ?", (bill_id,))
        done = f"Added to bill {bill_no}."
    elif a["type"] == "task":
        now = util.now()
        db.execute("INSERT OR IGNORE INTO tasks(kind, title, branch_id, related_type, related_id, status, due_at, created_at)"
                   " VALUES (?,?,?,?,?,'Open',?,?)", (a["kind"], a["title"][:200], f["branch_id"], a["related_type"],
                                                    a["related_id"], util.ts(now + timedelta(hours=4)), util.ts(now)))
        done = "Task created for the team."
    elif a["type"] == "stock_transfer":
        done = _transfer(int(a["batch_id"]), int(a["to_item_id"]), int(a["qty"]), actor)
    else:
        raise ValueError(f"Unknown action {a['type']!r}")
    _decide(f, "accepted", actor, done)
    audit.log(actor, "finding_accepted", "finding", f["id"], {"agent": f["agent"], "action": a, "result": done})
    return done


def dismiss(finding_id: int, actor: str, note: str) -> None:
    f = get(finding_id)
    if f is None:
        raise LookupError("Finding not found")
    if f["status"] != OPEN:
        raise ValueError("This finding was already decided.")
    note = (note or "").strip()[:300]
    if not note:
        raise ValueError("Say briefly why you are dismissing it, so the agent's owner can learn from it.")
    _decide(f, "dismissed", actor, note)
    audit.log(actor, "finding_dismissed", "finding", f["id"], {"agent": f["agent"], "note": note})


def _transfer(batch_id: int, to_item_id: int, qty: int, actor: str) -> str:
    src = db.one("SELECT b.*, i.name FROM stock_batches b JOIN stock_items i ON i.id = b.item_id WHERE b.id = ?", (batch_id,))
    dst = db.one("SELECT * FROM stock_items WHERE id = ?", (to_item_id,))
    if src is None or dst is None or dst["name"] != src["name"]:
        raise ValueError("The stock records changed; run the agent again.")
    if qty <= 0 or qty > src["qty"]:
        raise ValueError(f"Only {src['qty']} left in that batch; run the agent again.")
    now = util.ts(util.now())
    with db.connect() as conn:
        conn.execute("UPDATE stock_batches SET qty = qty - ? WHERE id = ?", (qty, batch_id))
        cur = conn.execute("INSERT INTO stock_batches(item_id, batch_no, expiry_date, qty, unit_cost) VALUES (?,?,?,?,?)",
                           (to_item_id, src["batch_no"], src["expiry_date"], qty, src["unit_cost"]))
        conn.execute("INSERT INTO stock_moves(batch_id, to_batch_id, qty, reason, actor, created_at) VALUES (?,?,?,?,?,?)",
                     (batch_id, cur.lastrowid, qty, "expiry transfer", actor, now))
    return f"Moved {qty} of {src['name']} batch {src['batch_no']} to Branch {dst['branch_id']}."


def summarize(finding_id: int, client=None) -> str | None:
    """Optional plain-language explanation by Claude. Every number must appear in the finding itself."""
    f = get(finding_id)
    if f is None:
        raise LookupError("Finding not found")
    if not ai.enabled() and client is None:
        return None
    payload = {"title": f["title"], "evidence": f["evidence_obj"], "suggested_action": f["suggested_action"],
               "amount": f["amount"]}
    out = ai.structured(system=SUMMARY_PROMPT, user=json.dumps(payload, ensure_ascii=False), output=FindingSummary,
                        effort="low", max_tokens=1024, client=client)
    kept, dropped = insights.verify([out.summary], payload)
    if dropped:
        audit.log("ai", "ai_summary_rejected", "finding", f["id"], {"reason": "numbers not in the finding"})
        raise ai.AIError("The explanation used numbers that are not in the finding, so it was not saved.")
    db.execute("UPDATE findings SET ai_summary = ? WHERE id = ?", (kept[0], f["id"]))
    audit.log("ai", "ai_summary", "finding", f["id"])
    return kept[0]
