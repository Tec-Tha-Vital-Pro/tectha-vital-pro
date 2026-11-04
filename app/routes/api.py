"""REST API for the hospital's other systems: billing software, website forms, lead ads (via n8n/Zapier).

All endpoints except /health need the header X-API-Key matching TT_API_KEY.
"""
import hmac
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app import audit, billing, config, db, metrics, patients, util

router = APIRouter()


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = config.settings.api_key
    if not expected:
        raise HTTPException(status_code=503, detail="Set TT_API_KEY to enable the API")
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or wrong X-API-Key header")


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(e, LookupError) else 400, detail=str(e))


def _branch(branch_id: str | None) -> None:
    if branch_id is not None and not db.one("SELECT id FROM branches WHERE id = ?", (branch_id,)):
        raise HTTPException(status_code=400, detail=f"Unknown branch_id {branch_id!r}")


class LeadIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str
    need: str | None = None
    source: str = Field(min_length=1)
    branch_id: str | None = None


class PatientIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str
    age: int | None = Field(default=None, ge=0, le=130)
    gender: str | None = None
    consent: bool | None = None


class Item(BaseModel):
    description: str = Field(min_length=1)
    amount: int = Field(gt=0)


class BillIn(BaseModel):
    phone: str
    patient_name: str = Field(min_length=1)
    branch_id: str
    items: list[Item] = Field(min_length=1)
    external_ref: str | None = None
    bill_no: str | None = None


class PaymentIn(BaseModel):
    bill_no: str
    amount: int = Field(gt=0)
    mode: str = Field(min_length=1)


class OrderIn(BaseModel):
    phone: str
    patient_name: str = Field(min_length=1)
    branch_id: str
    dept: str = Field(min_length=1)
    description: str = Field(min_length=1)
    amount: int = Field(gt=0)


class ClaimIn(BaseModel):
    phone: str
    patient_name: str = Field(min_length=1)
    branch_id: str
    insurer: str = Field(min_length=1)
    amount: int = Field(gt=0)
    stage: str = "PreAuthRequested"


class StageIn(BaseModel):
    stage: str


@router.get("/health")
def health() -> dict:
    """For uptime checks. 'scheduler_running' false means no reminders are going out."""
    from app import scheduler
    last = db.scalar("SELECT MAX(created_at) FROM audit_log WHERE actor = 'automation'")
    return {"ok": True, "scheduler_running": scheduler.is_running(), "last_automation_activity": last}


@router.post("/leads", dependencies=[Depends(require_key)])
def create_lead(body: LeadIn) -> dict:
    _branch(body.branch_id)
    try:
        phone = util.normalize_phone(body.phone)
    except ValueError as e:
        raise _bad(e)
    existing = db.one("SELECT id FROM patients WHERE phone = ?", (phone,))
    now = util.ts(util.now())
    lid = db.execute(
        "INSERT INTO leads(name, phone, need, source, branch_id, status, patient_id, created_at, updated_at)"
        " VALUES (?,?,?,?,?, 'New', ?, ?, ?)",
        (body.name.strip(), phone, body.need, body.source.strip(), body.branch_id, existing["id"] if existing else None, now, now),
    )
    audit.log("api", "create", "lead", lid, {"source": body.source})
    return {"id": lid}


@router.post("/patients", dependencies=[Depends(require_key)])
def create_patient(body: PatientIn) -> dict:
    try:
        p = patients.find_or_create(body.name, body.phone, age=body.age, gender=body.gender, consent=body.consent, actor="api")
    except ValueError as e:
        raise _bad(e)
    return {"id": p["id"], "uid": p["uid"]}


@router.post("/bills", dependencies=[Depends(require_key)])
def create_bill(body: BillIn) -> dict:
    _branch(body.branch_id)
    try:
        p = patients.find_or_create(body.patient_name, body.phone, actor="api")
        bid = billing.create_bill(p["id"], body.branch_id, [(i.description, i.amount) for i in body.items],
                                  bill_no=body.bill_no, external_ref=body.external_ref, actor="api")
    except (ValueError, LookupError) as e:
        raise _bad(e)
    bill = db.one("SELECT id, bill_no, total FROM bills WHERE id = ?", (bid,))
    return {"id": bill["id"], "bill_no": bill["bill_no"], "total": bill["total"], "patient_uid": p["uid"]}


@router.post("/payments", dependencies=[Depends(require_key)])
def create_payment(body: PaymentIn) -> dict:
    bill = db.one("SELECT id FROM bills WHERE bill_no = ?", (body.bill_no,))
    if bill is None:
        raise HTTPException(status_code=404, detail=f"Bill {body.bill_no!r} not found")
    try:
        pid = billing.record_payment(bill["id"], body.amount, body.mode, actor="api")
    except ValueError as e:
        raise _bad(e)
    b = db.one("SELECT total - paid AS balance FROM bills WHERE id = ?", (bill["id"],))
    return {"id": pid, "balance": b["balance"]}


@router.post("/orders", dependencies=[Depends(require_key)])
def create_order(body: OrderIn) -> dict:
    _branch(body.branch_id)
    try:
        p = patients.find_or_create(body.patient_name, body.phone, actor="api")
        oid = billing.create_order(p["id"], body.branch_id, body.dept, body.description, body.amount, actor="api")
    except (ValueError, LookupError) as e:
        raise _bad(e)
    return {"id": oid}


@router.post("/claims", dependencies=[Depends(require_key)])
def create_claim(body: ClaimIn) -> dict:
    _branch(body.branch_id)
    try:
        p = patients.find_or_create(body.patient_name, body.phone, actor="api")
        cid = billing.create_claim(p["id"], body.branch_id, body.insurer, body.amount, stage=body.stage, actor="api")
    except (ValueError, LookupError) as e:
        raise _bad(e)
    return {"id": cid}


@router.patch("/claims/{claim_id}", dependencies=[Depends(require_key)])
def update_claim(claim_id: int, body: StageIn) -> dict:
    try:
        billing.set_claim_stage(claim_id, body.stage, actor="api")
    except (ValueError, LookupError) as e:
        raise _bad(e)
    return {"id": claim_id, "stage": body.stage}


@router.get("/dashboard", dependencies=[Depends(require_key)])
def dashboard(branch: str | None = None) -> dict:
    _branch(branch)
    today: date = util.now().date()
    return {"date": today.isoformat(), "branch": branch or "all",
            "kpis": metrics.kpis(today, branch), "attention": metrics.attention(branch)}
