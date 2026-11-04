"""Bills, payments, service orders and insurance claims. Every write is audited."""
import uuid
from datetime import datetime

from app import audit, db, util

CLAIM_STAGES = ("PreAuthRequested", "PreAuthApproved", "FinalSent", "Settled", "Denied")


def _ts(dt: datetime | str | None) -> str:
    if dt is None:
        return util.ts(util.now())
    if isinstance(dt, datetime):
        return util.ts(dt)
    util.parse(dt)  # validates format
    return dt


def _require(sql: str, params: tuple, what: str) -> dict:
    row = db.one(sql, params)
    if row is None:
        raise LookupError(f"{what} not found")
    return row


def create_bill(patient_id: int, branch_id: str, items: list[tuple[str, int]], *, bill_no: str | None = None,
                external_ref: str | None = None, created_at: datetime | str | None = None, actor: str = "system") -> int:
    if not items:
        raise ValueError("A bill needs at least one item")
    for desc, amount in items:
        if not str(desc).strip():
            raise ValueError("Bill item description is empty")
        if int(amount) <= 0:
            raise ValueError(f"Bill item amount must be positive: {desc!r} = {amount}")
    _require("SELECT id FROM patients WHERE id = ?", (patient_id,), f"Patient {patient_id}")
    _require("SELECT id FROM branches WHERE id = ?", (branch_id,), f"Branch {branch_id!r}")
    if external_ref and db.one("SELECT id FROM bills WHERE external_ref = ?", (external_ref,)):
        raise ValueError(f"A bill with external reference {external_ref!r} already exists")
    if bill_no and db.one("SELECT id FROM bills WHERE bill_no = ?", (bill_no,)):
        raise ValueError(f"Bill number {bill_no!r} already exists")
    created = _ts(created_at)
    total = sum(int(a) for _, a in items)
    bid = db.execute(
        "INSERT INTO bills(bill_no, patient_id, branch_id, total, paid, external_ref, created_at) VALUES (?,?,?,?,0,?,?)",
        (bill_no or f"TMP-{uuid.uuid4().hex}", patient_id, branch_id, total, external_ref, created),
    )
    if not bill_no:
        bill_no = f"{branch_id}-{util.parse(created).strftime('%y%m%d')}-{bid:05d}"
        db.execute("UPDATE bills SET bill_no = ? WHERE id = ?", (bill_no, bid))
    for desc, amount in items:
        db.execute("INSERT INTO bill_items(bill_id, description, amount) VALUES (?,?,?)", (bid, str(desc).strip(), int(amount)))
    audit.log(actor, "create", "bill", bid, {"bill_no": bill_no, "total": total, "branch": branch_id})
    return bid


def record_payment(bill_id: int, amount: int, mode: str, *, paid_at: datetime | str | None = None, actor: str = "system") -> int:
    bill = _require("SELECT * FROM bills WHERE id = ?", (bill_id,), f"Bill {bill_id}")
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    balance = bill["total"] - bill["paid"]
    if amount > balance:
        raise ValueError(f"Payment {util.inr(amount)} is more than the balance {util.inr(balance)} on bill {bill['bill_no']}")
    if not str(mode).strip():
        raise ValueError("Payment mode is required")
    pid = db.execute("INSERT INTO payments(bill_id, amount, mode, paid_at) VALUES (?,?,?,?)", (bill_id, amount, mode.strip(), _ts(paid_at)))
    db.execute("UPDATE bills SET paid = paid + ? WHERE id = ?", (amount, bill_id))
    audit.log(actor, "payment", "bill", bill_id, {"amount": amount, "mode": mode, "payment_id": pid})
    return pid


def create_order(patient_id: int, branch_id: str, dept: str, description: str, amount: int, *,
                 created_at: datetime | str | None = None, actor: str = "system") -> int:
    if int(amount) <= 0:
        raise ValueError("Order amount must be positive")
    _require("SELECT id FROM patients WHERE id = ?", (patient_id,), f"Patient {patient_id}")
    _require("SELECT id FROM branches WHERE id = ?", (branch_id,), f"Branch {branch_id!r}")
    oid = db.execute(
        "INSERT INTO orders(patient_id, branch_id, dept, description, amount, created_at) VALUES (?,?,?,?,?,?)",
        (patient_id, branch_id, dept, description, int(amount), _ts(created_at)),
    )
    audit.log(actor, "create", "order", oid, {"dept": dept, "amount": int(amount)})
    return oid


def add_order_to_bill(order_id: int, *, actor: str = "system") -> int:
    order = _require("SELECT * FROM orders WHERE id = ?", (order_id,), f"Order {order_id}")
    if order["bill_id"] is not None:
        raise ValueError(f"Order {order_id} is already on bill {order['bill_id']}")
    today = util.now().date().isoformat()
    bill = db.one(
        "SELECT * FROM bills WHERE patient_id = ? AND branch_id = ? AND (total > paid OR date(created_at) = ?)"
        " ORDER BY created_at DESC, id DESC LIMIT 1",
        (order["patient_id"], order["branch_id"], today),
    )
    item = f"{order['dept']}: {order['description']}"
    if bill is None:
        bid = create_bill(order["patient_id"], order["branch_id"], [(item, order["amount"])], actor=actor)
    else:
        bid = bill["id"]
        db.execute("INSERT INTO bill_items(bill_id, description, amount) VALUES (?,?,?)", (bid, item, order["amount"]))
        db.execute("UPDATE bills SET total = total + ? WHERE id = ?", (order["amount"], bid))
    db.execute("UPDATE orders SET bill_id = ? WHERE id = ?", (bid, order_id))
    db.execute("UPDATE tasks SET status = 'Done' WHERE kind = 'unbilled' AND related_type = 'order' AND related_id = ? AND status = 'Open'", (order_id,))
    audit.log(actor, "order_billed", "order", order_id, {"bill_id": bid, "amount": order["amount"]})
    return bid


def create_claim(patient_id: int, branch_id: str, insurer: str, amount: int, *, stage: str = "PreAuthRequested",
                 created_at: datetime | str | None = None, actor: str = "system") -> int:
    if stage not in CLAIM_STAGES:
        raise ValueError(f"Unknown claim stage {stage!r}; use one of {', '.join(CLAIM_STAGES)}")
    if int(amount) <= 0:
        raise ValueError("Claim amount must be positive")
    _require("SELECT id FROM patients WHERE id = ?", (patient_id,), f"Patient {patient_id}")
    created = _ts(created_at)
    cid = db.execute(
        "INSERT INTO claims(patient_id, branch_id, insurer, amount, stage, stage_changed_at, created_at) VALUES (?,?,?,?,?,?,?)",
        (patient_id, branch_id, insurer, int(amount), stage, created, created),
    )
    audit.log(actor, "create", "claim", cid, {"insurer": insurer, "amount": int(amount), "stage": stage})
    return cid


def set_claim_stage(claim_id: int, stage: str, *, actor: str = "system") -> None:
    if stage not in CLAIM_STAGES:
        raise ValueError(f"Unknown claim stage {stage!r}; use one of {', '.join(CLAIM_STAGES)}")
    claim = _require("SELECT * FROM claims WHERE id = ?", (claim_id,), f"Claim {claim_id}")
    db.execute("UPDATE claims SET stage = ?, stage_changed_at = ? WHERE id = ?", (stage, util.ts(util.now()), claim_id))
    db.execute("UPDATE tasks SET status = 'Done' WHERE kind = 'claim_stuck' AND related_type = 'claim' AND related_id = ? AND status = 'Open'", (claim_id,))
    audit.log(actor, "claim_stage", "claim", claim_id, {"from": claim["stage"], "to": stage})


def dues(branch: str | None = None) -> list[dict]:
    where, params = ("AND b.branch_id = ?", (branch,)) if branch else ("", ())
    rows = db.query(
        "SELECT b.*, p.name AS patient_name, p.phone, p.uid, b.total - b.paid AS balance,"
        " (SELECT COUNT(*) FROM dues_reminders r WHERE r.bill_id = b.id) AS reminders_sent,"
        " (SELECT MAX(sent_at) FROM dues_reminders r WHERE r.bill_id = b.id) AS last_reminder_at"
        f" FROM bills b JOIN patients p ON p.id = b.patient_id WHERE b.total > b.paid {where}"
        " ORDER BY b.created_at ASC",
        params,
    )
    now = util.now()
    for r in rows:
        r["age_days"] = (now - util.parse(r["created_at"])).days
    return rows
