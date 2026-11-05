"""Staff screens for the next AI features: vitals and NEWS2, report explainers, draft replies, coding assistant.

All of them are decision support. Nothing here sends a message, submits a claim or changes a
clinical decision by itself; a person presses the button, and that decision is logged.
"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app import auth, db
from app.ai_features import coding, drafts, explainers, governance, news2
from app.auth import ADMIN, BILLING, CLINICAL, FRONT
from app.routes import ui
from app.routes.ui import _own, _scope, back, render

router = APIRouter(route_class=ui.UIRoute)

VITALS_ROLES = CLINICAL | {"nurse"}
EXPLAINER_ROLES = {"admin", "doctor"}


# ---------------------------------------------------------------- vitals and NEWS2

@router.get("/vitals", response_class=HTMLResponse)
def vitals_page(request: Request, branch: str = ""):
    user = auth.require(request, VITALS_ROLES)
    br = _scope(user, branch)
    return render(request, "vitals.html", user, beds=news2.inpatients(br), alerts=news2.open_alerts(br),
                  th=news2.thresholds(), label=news2.LABEL, can_tune=user["role"] in ADMIN, f_branch=br or "")


@router.post("/vitals")
async def vitals_record(request: Request, patient_id: str = Form(""), resp_rate: str = Form(""), spo2: str = Form(""),
                        on_oxygen: str = Form(""), systolic_bp: str = Form(""), pulse: str = Form(""),
                        consciousness: str = Form("A"), temperature: str = Form("")):
    user = await auth.require_post(request, VITALS_ROLES)
    if not patient_id.isdigit():
        return back("/vitals", err="Choose a patient.")
    bed = next((b for b in news2.inpatients(user["branch_id"]) if b["patient_id"] == int(patient_id)), None)
    if bed is None:
        raise auth.NotFound("patient")
    try:
        vals = {"resp_rate": int(resp_rate), "spo2": int(spo2), "on_oxygen": on_oxygen == "1",
                "systolic_bp": int(systolic_bp), "pulse": int(pulse), "consciousness": consciousness,
                "temperature": float(temperature)}
        r = news2.record(bed["patient_id"], bed["branch_id"], vals, auth.actor(user), bed_id=bed["bed_id"])
    except ValueError as e:
        return back("/vitals", err=str(e) if str(e) and "invalid literal" not in str(e) else "Fill in every vital sign as a number.")
    msg = f"Vitals saved for {bed['name']}: NEWS2 {r['news2']}."
    if r["alert"]:
        msg += f" {r['alert']['level'].capitalize()} alert sent to the ward doctors and nurses."
    return back("/vitals", msg=msg)


@router.post("/vitals/alerts/{alert_id}/ack")
async def vitals_ack(request: Request, alert_id: int):
    user = await auth.require_post(request, VITALS_ROLES)
    a = db.one("SELECT * FROM news2_alerts WHERE id = ?", (alert_id,))
    if a is None or (user["branch_id"] and a["branch_id"] != user["branch_id"]):
        raise auth.NotFound("alert")
    news2.acknowledge(alert_id, auth.actor(user))
    return back("/vitals", msg="Alert acknowledged. Record the review in the patient's notes.")


@router.post("/vitals/thresholds")
async def vitals_thresholds(request: Request, news2_urgent: str = Form(""), news2_emergency: str = Form(""),
                            news2_rise: str = Form(""), news2_escalate_minutes: str = Form("")):
    user = await auth.require_post(request, ADMIN)
    try:
        news2.set_thresholds({"news2_urgent": news2_urgent, "news2_emergency": news2_emergency, "news2_rise": news2_rise,
                              "news2_escalate_minutes": news2_escalate_minutes}, auth.actor(user))
    except ValueError as e:
        return back("/vitals", err=str(e))
    return back("/vitals", msg="NEWS2 thresholds saved.")


# ---------------------------------------------------------------- report explainers

@router.get("/explainers", response_class=HTMLResponse)
def explainers_page(request: Request):
    user = auth.require(request, EXPLAINER_ROLES)
    tests = db.query("SELECT code, name FROM lab_tests ORDER BY name")
    rows = {(r["test_code"], r["lang"]): r for r in db.query("SELECT * FROM report_explainers")}
    items = [{"code": t["code"], "name": t["name"], "en": rows.get((t["code"], "en")), "hi": rows.get((t["code"], "hi"))}
             for t in tests]
    return render(request, "explainers.html", user, items=items)


@router.post("/explainers")
async def explainers_save(request: Request, test_code: str = Form(""), lang: str = Form(""), body: str = Form("")):
    user = await auth.require_post(request, EXPLAINER_ROLES)
    if not db.scalar("SELECT 1 FROM lab_tests WHERE code = ?", (test_code,)):
        return back("/explainers", err="Unknown test.")
    try:
        explainers.save(test_code, lang, body, auth.actor(user))
    except ValueError as e:
        return back("/explainers", err=str(e))
    return back("/explainers", msg="Saved as a draft. A doctor must approve it before patients see it.")


@router.post("/explainers/approve")
async def explainers_approve(request: Request, test_code: str = Form(""), lang: str = Form("")):
    user = await auth.require_post(request, EXPLAINER_ROLES)
    try:
        explainers.approve(test_code, lang, auth.actor(user))
    except LookupError as e:
        return back("/explainers", err=str(e))
    return back("/explainers", msg="Approved. Patients now see this text on validated reports.")


# ---------------------------------------------------------------- draft replies

@router.post("/messages/draft")
async def messages_draft(request: Request, phone: str = Form("")):
    user = await auth.require_post(request, FRONT)
    digits = "".join(c for c in phone if c.isdigit())
    scope_sql, scope_params = ui._message_scope(user)
    if not digits or not db.scalar(f"SELECT 1 FROM messages m WHERE m.to_phone = ?{scope_sql} LIMIT 1", (digits, *scope_params)):
        raise auth.NotFound("conversation")
    d = drafts.propose(digits, auth.actor(user))
    src = "AI draft" if d["model_key"] == "draft_reply_claude" else "Template draft"
    return back(f"/messages?phone={digits}&draft={d['id']}", msg=f"{src} added to the reply box. Check and edit it, then press Send.")


# ---------------------------------------------------------------- coding assistant

@router.post("/claims/{claim_id}/codes/suggest")
async def claim_codes_suggest(request: Request, claim_id: int):
    user = await auth.require_post(request, BILLING)
    _own(user, "claims", claim_id)
    try:
        r = coding.suggest(claim_id, auth.actor(user))
    except (ValueError, LookupError) as e:
        return back("/claims", err=str(e))
    n = len(r["items"])
    return back("/claims", msg=f"{n} code suggestion{'s' if n != 1 else ''} ready on the claim card. A coder must accept or edit them."
                if n else "No code could be suggested from this record. Code it manually.")


@router.post("/claims/codes/{sid}/decide")
async def claim_codes_decide(request: Request, sid: int, codes: str = Form("")):
    user = await auth.require_post(request, BILLING)
    s = db.one("SELECT claim_id FROM coding_suggestions WHERE id = ?", (sid,))
    if s is None:
        raise auth.NotFound("suggestion")
    _own(user, "claims", s["claim_id"])
    try:
        status = coding.decide(sid, [c for c in codes.replace(";", ",").split(",")], auth.actor(user))
    except (ValueError, LookupError) as e:
        return back("/claims", err=str(e))
    return back("/claims", msg="Codes saved on the claim." if status == "Accepted" else "Suggestions rejected.")


def install_nav() -> None:
    """Add the AI feature screens to the staff menu (idempotent)."""
    have = {n[0] for n in ui.NAV}
    if "/vitals" not in have:
        at = next((i for i, n in enumerate(ui.NAV) if n[0] == "/patients"), len(ui.NAV) - 1) + 1
        ui.NAV.insert(at, ("/vitals", "Vitals & NEWS2", VITALS_ROLES, "Patients & front desk", "heart"))
    if "/explainers" not in have:
        at = next((i for i, n in enumerate(ui.NAV) if n[0] == "/ai-labs"), len(ui.NAV) - 1) + 1
        ui.NAV.insert(at, ("/explainers", "Report explainers", EXPLAINER_ROLES, "Intelligence", "spark"))
    ui.TABS.setdefault("nurse", [])
    if "/vitals" not in ui.TABS["nurse"]:
        ui.TABS["nurse"].insert(0, "/vitals")
    ui.HOME["lab"] = "/diagnostics"
    ui.HOME["pharmacy"] = "/diagnostics"


governance_ready = governance.ensure_registered
