"""Command Centre (/command) and Notifications (/notifications), plus the bell and sidebar extras."""
from datetime import timedelta

from fastapi import APIRouter, Request

from app import auth, config, db, notify, util
from app.routes import ui

router = APIRouter(route_class=ui.UIRoute)

COMMAND_ROLES = {"admin", "owner", "doctor"}
NOTIFY_ROLES = auth.STAFF | {"lab", "nurse", "pharmacist", "radiology"}
CLAIM_LIMITS = {"PreAuthRequested": 60, "FinalSent": 180}   # minutes (IRDAI 2024)

# ---------------------------------------------------------------- navigation entries for Pro screens
_NAV_ADDED = False


def extend_navigation() -> None:
    """Add Pro screens to the sidebar (idempotent)."""
    global _NAV_ADDED
    if _NAV_ADDED:
        return
    from app.routes import diagnostics as diag
    nav = ui.NAV
    after_dash = next(i for i, n in enumerate(nav) if n[0] == "/") + 1
    nav.insert(after_dash, ("/command", "Command Centre", COMMAND_ROLES, "Overview", "command"))
    after_patients = next(i for i, n in enumerate(nav) if n[0] == "/patients") + 1
    nav.insert(after_patients, ("/diagnostics", "Diagnostics & Pharmacy", diag.VIEW_ROLES, "Patients & front desk", "lab"))
    ui.TABS.setdefault("doctor", []).append("/diagnostics")
    _NAV_ADDED = True


def add_optional_nav(app) -> None:
    """Screens owned by other modules appear in the menu only once their route exists."""
    paths = {getattr(r, "path", "") for r in app.routes}
    extras = [("/ai-labs", "AI Labs", auth.STAFF, "Intelligence", "spark"),
              ("/account", "Account", auth.STAFF, "Admin", "users")]
    for item in extras:
        if item[0] in paths and all(n[0] != item[0] for n in ui.NAV):
            ui.NAV.append(item)


def _summary(user: dict | None) -> dict:
    if not user:
        return {"count": 0, "items": []}
    return {"count": notify.unread_count(user["id"]), "items": notify.recent(user["id"], 6)}


def _demo_build() -> bool:
    return config.settings.whatsapp_mode == "simulator"


ui.TEMPLATES.env.globals["notif_summary"] = _summary
ui.TEMPLATES.env.globals["demo_build"] = _demo_build


# ---------------------------------------------------------------- command centre

def overview(branch: str | None, now) -> dict:
    branches = [b for b in ui._branches() if not branch or b["id"] == branch]
    today = now.date().isoformat()
    out = []
    for b in branches:
        bid = b["id"]
        wards = db.query("SELECT w.name, SUM(bd.status='Occupied') AS occ, SUM(bd.status='Free') AS free,"
                         " SUM(bd.status='Cleaning') AS cleaning, COUNT(bd.id) AS total FROM wards w"
                         " JOIN beds bd ON bd.ward_id = w.id WHERE w.branch_id = ? GROUP BY w.id ORDER BY w.id", (bid,))
        total = sum(w["total"] for w in wards) or 0
        occ = sum(w["occ"] or 0 for w in wards)
        claims = db.query("SELECT stage, stage_changed_at FROM claims WHERE branch_id = ? AND stage IN ('PreAuthRequested','FinalSent')", (bid,))
        past = sum(1 for c in claims if (now - util.parse(c["stage_changed_at"])).total_seconds() / 60 > CLAIM_LIMITS[c["stage"]])
        out.append({
            "id": bid, "name": b["name"], "wards": wards, "beds_total": total, "beds_occ": occ,
            "occ_pct": round(100 * occ / total) if total else 0,
            "opd_waiting": db.scalar("SELECT COUNT(*) FROM appointments WHERE branch_id = ? AND date(starts_at) = ?"
                                     " AND status IN ('Booked','Confirmed') AND starts_at <= ?", (bid, today, util.ts(now + timedelta(hours=1)))),
            "opd_seen": db.scalar("SELECT COUNT(*) FROM appointments WHERE branch_id = ? AND date(starts_at) = ? AND status = 'Visited'", (bid, today)),
            "critical_open": db.scalar("SELECT COUNT(*) FROM lab_callouts c JOIN lab_orders l ON l.id = c.lab_order_id"
                                       " WHERE c.status = 'Open' AND l.branch_id = ?", (bid,)),
            "awaiting_validation": db.scalar("SELECT COUNT(*) FROM lab_orders WHERE branch_id = ? AND status = 'Resulted'", (bid,)),
            "claims_past": past,
            "unbilled": db.scalar("SELECT COALESCE(SUM(amount),0) FROM orders WHERE branch_id = ? AND bill_id IS NULL", (bid,)),
            "rx_pending": db.scalar("SELECT COUNT(*) FROM prescriptions WHERE branch_id = ? AND status = 'Pending'", (bid,)),
            "staff_on_duty": db.scalar(
                "SELECT COUNT(*) FROM users u WHERE u.active = 1 AND (u.branch_id = ? OR u.branch_id IS NULL) AND EXISTS"
                " (SELECT 1 FROM audit_log a WHERE a.action = 'login_success' AND a.entity_id = u.id AND date(a.created_at) = ?)",
                (bid, today)),
            "staff_total": db.scalar("SELECT COUNT(*) FROM users WHERE active = 1 AND (branch_id = ? OR branch_id IS NULL)", (bid,)),
        })
    return {"branches": out}


@router.get("/command")
def command_page(request: Request):
    user = auth.require(request, COMMAND_ROLES)
    branch = ui._scope(user, request.query_params.get("branch"))
    now = util.now()
    wall = request.query_params.get("wall") == "1"
    data = overview(branch, now)
    alerts = db.query(
        "SELECT c.lab_order_id, c.created_at, t.name AS test_name, l.result_value, t.unit, p.name AS patient_name, l.branch_id"
        " FROM lab_callouts c JOIN lab_orders l ON l.id = c.lab_order_id JOIN lab_tests t ON t.code = l.test_code"
        " JOIN patients p ON p.id = l.patient_id WHERE c.status = 'Open'" + (" AND l.branch_id = ?" if branch else "")
        + " ORDER BY c.created_at", (branch,) if branch else ())
    return ui.render(request, "command.html", user, wall=wall, now=now, alerts=alerts, branch=branch, **data)


# ---------------------------------------------------------------- notifications

@router.get("/notifications")
def notifications_page(request: Request):
    user = auth.require(request, NOTIFY_ROLES)
    rows = db.query("SELECT * FROM notifications WHERE user_id = ? ORDER BY read_at IS NOT NULL, id DESC LIMIT 100", (user["id"],))
    return ui.render(request, "notifications.html", user, rows=rows)


@router.post("/notifications/{nid}/open")
async def notification_open(request: Request, nid: int):
    user = await auth.require_post(request, NOTIFY_ROLES)
    n = db.one("SELECT * FROM notifications WHERE id = ? AND user_id = ?", (nid, user["id"]))
    if n is None:
        raise auth.NotFound("notification")
    notify.mark_read(user["id"], nid)
    link = n["link"] if n["link"].startswith("/") and not n["link"].startswith("//") else "/"
    return ui.RedirectResponse(link, status_code=303)


@router.post("/notifications/read-all")
async def notifications_read_all(request: Request):
    user = await auth.require_post(request, NOTIFY_ROLES)
    n = notify.mark_read(user["id"])
    return ui.back("/notifications", msg=f"{n} notification{'s' if n != 1 else ''} marked as read.")


extend_navigation()
