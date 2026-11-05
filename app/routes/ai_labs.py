"""AI Labs screen: the agents, their switches, and the queue of findings to accept or dismiss."""
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app import agents, audit, auth, db, util
from app.agents import actions
from app.ai import client as ai
from app.auth import ADMIN, OWNER_VIEW
from app.routes import ui
from app.routes.ui import back, render

router = APIRouter(route_class=ui.UIRoute)
SEVERITY_ORDER = "CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END"


def _own_finding(user: dict, finding_id: int) -> dict:
    f = actions.get(finding_id)
    if f is None or (user["branch_id"] and f["branch_id"] not in (None, user["branch_id"])):
        raise auth.NotFound("finding")
    return f


@router.get("/ai-labs", response_class=HTMLResponse)
def ai_labs_page(request: Request, agent: str = "", show: str = "open"):
    user = auth.require(request, OWNER_VIEW)
    where, params = ["1=1"], []
    if agent in agents.REGISTRY:
        where.append("agent = ?")
        params.append(agent)
    if show in ("open", "accepted", "dismissed"):
        where.append("status = ?")
        params.append(show)
    if user["branch_id"]:
        where.append("(branch_id IS NULL OR branch_id = ?)")
        params.append(user["branch_id"])
    rows = db.query(f"SELECT * FROM findings WHERE {' AND '.join(where)} ORDER BY {SEVERITY_ORDER}, created_at DESC LIMIT 200",
                    tuple(params))
    for r in rows:
        r["evidence_obj"] = json.loads(r["evidence"])
    cards = []
    for name, a in agents.REGISTRY.items():
        lr = agents.last_run(name)
        bf, bp = ("AND (branch_id IS NULL OR branch_id = ?)", (user["branch_id"],)) if user["branch_id"] else ("", ())
        cards.append({"name": name, "title": a.title, "description": a.description, "on": agents.is_enabled(name),
                      "every": a.interval_minutes, "last_run": lr["last_run_at"] if lr else None,
                      "open": db.scalar(f"SELECT COUNT(*) FROM findings WHERE agent = ? AND status = 'open' {bf}", (name, *bp)),
                      "at_stake": db.scalar(f"SELECT COALESCE(SUM(amount),0) FROM findings WHERE agent = ? AND status = 'open' {bf}",
                                            (name, *bp))})
    return render(request, "ai_labs.html", user, cards=cards, findings=rows, agent=agent, show=show,
                  can_decide=user["role"] in ADMIN, ai_on=ai.enabled())


@router.post("/ai-labs/agents/{name}/toggle")
async def toggle(request: Request, name: str, on: str = Form(...)):
    user = await auth.require_post(request, ADMIN)
    if name not in agents.REGISTRY:
        raise auth.NotFound("agent")
    agents.set_enabled(name, on == "1", actor=auth.actor(user))
    return back("/ai-labs", msg=f"{agents.REGISTRY[name].title} is {'on' if on == '1' else 'off'}.")


@router.post("/ai-labs/agents/{name}/run")
async def run_now(request: Request, name: str):
    user = await auth.require_post(request, ADMIN)
    if name not in agents.REGISTRY:
        raise auth.NotFound("agent")
    r = agents.run_agent(name, util.now(), actor=auth.actor(user))
    return back(f"/ai-labs?agent={name}",
                msg=f"{agents.REGISTRY[name].title} checked: {r['new']} new, {r['found']} open, {r['resolved']} resolved on their own.")


@router.post("/ai-labs/findings/{finding_id}/accept")
async def accept(request: Request, finding_id: int):
    user = await auth.require_post(request, ADMIN)
    _own_finding(user, finding_id)
    try:
        done = actions.accept(finding_id, actor=auth.actor(user))
    except ValueError as e:
        return back("/ai-labs", err=str(e))
    return back("/ai-labs", msg=done)


@router.post("/ai-labs/findings/{finding_id}/dismiss")
async def dismiss(request: Request, finding_id: int, note: str = Form("")):
    user = await auth.require_post(request, ADMIN)
    _own_finding(user, finding_id)
    try:
        actions.dismiss(finding_id, actor=auth.actor(user), note=note)
    except ValueError as e:
        return back("/ai-labs", err=str(e))
    return back("/ai-labs", msg="Dismissed. The reason is saved with the finding.")


@router.post("/ai-labs/findings/{finding_id}/explain")
async def explain(request: Request, finding_id: int):
    user = await auth.require_post(request, OWNER_VIEW)
    _own_finding(user, finding_id)
    if not ai.enabled():
        return back("/ai-labs", err="AI explanations are off. An admin can turn on AI with an Anthropic API key.")
    try:
        actions.summarize(finding_id)
    except ai.AIError as e:
        audit.log("ai", "ai_error", "finding", finding_id, {"error": str(e)})
        return back("/ai-labs", err=f"No explanation this time: {e}")
    return back("/ai-labs", msg="Explanation added below the finding.")
