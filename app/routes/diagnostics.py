"""Diagnostics & Pharmacy screens: Laboratory, Radiology, Pharmacy counter (/diagnostics)."""
from datetime import timedelta

from fastapi import APIRouter, Request

from app import auth, db, diagnostics, patients, util
from app.routes import ui

router = APIRouter(route_class=ui.UIRoute)

# Roles that exist today plus the clinical roles the auth module may add (lab, nurse, pharmacist).
LAB_ROLES = {"admin", "doctor", "frontdesk", "lab", "nurse"}
VALIDATE_ROLES = {"admin", "doctor", "lab"}
RAD_ROLES = {"admin", "doctor", "frontdesk", "radiology"}
RX_ROLES = {"admin", "frontdesk", "billing", "pharmacist"}
VIEW_ROLES = LAB_ROLES | RAD_ROLES | RX_ROLES | {"owner"}
TABS = [("lab", "Laboratory", "lab"), ("rad", "Radiology", "scan"), ("rx", "Pharmacy counter", "pill")]
FLAG_TEXT = {"HH": "!!", "LL": "!!", "H": "↑", "L": "↓", "N": ""}


def _own(user: dict, table: str, row_id: int, what: str) -> dict:
    """Same rule as the rest of the app: another branch's record is a plain 404."""
    row = db.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    if row is None or (user["branch_id"] and row["branch_id"] != user["branch_id"]):
        raise auth.NotFound(what)
    return row


def _tab_url(tab: str, anchor: str = "") -> tuple[str, str]:
    return f"/diagnostics?tab={tab}", anchor


def _back(target: tuple[str, str], msg: str | None = None, err: str | None = None):
    """Redirect with a signed toast; the #anchor goes after the query so the toast survives."""
    path, anchor = target
    r = ui.back(path, msg=msg, err=err)
    if anchor:
        r.headers["location"] = r.headers["location"] + f"#{anchor}"
    return r


def _patient_from_form(form) -> dict:
    phone = ui._phone_or_none(str(form.get("phone", "")))
    name = str(form.get("name", "")).strip()
    if not phone or not name:
        raise diagnostics.RuleError("Enter the patient's name and a 10-digit mobile number")
    return patients.find_or_create(name, phone)


def _branch_for(user: dict, form) -> str:
    b = user["branch_id"] or str(form.get("branch_id", ""))
    if b not in {x["id"] for x in ui._branches()}:
        raise diagnostics.RuleError("Choose a branch")
    return b


def _ago(ts: str | None, now) -> str:
    if not ts:
        return "—"
    mins = int((now - util.parse(ts)).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 0)} min ago"
    if mins < 1440:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} d ago"


@router.get("/diagnostics")
def diagnostics_page(request: Request):
    user = auth.require(request, VIEW_ROLES)
    tab = request.query_params.get("tab", "lab")
    tab = tab if tab in {t[0] for t in TABS} else "lab"
    branch = ui._scope(user, request.query_params.get("branch"))
    now = util.now()
    diagnostics.sweep(now)   # escalations and bell notifications (also runs every minute in the automations)
    f, p = (" AND l.branch_id = ?", (branch,)) if branch else ("", ())
    ctx = {"tab": tab, "tabs": TABS, "branch": branch, "now": now}
    if tab == "lab":
        rows = db.query(
            "SELECT l.*, t.name AS test_name, t.unit, t.specimen, p.name AS patient_name, p.uid, d.name AS doctor_name,"
            " c.status AS callout_status, c.called_to, c.called_at, c.called_by, r.test_code AS reflex_parent"
            " FROM lab_orders l JOIN lab_tests t ON t.code = l.test_code JOIN patients p ON p.id = l.patient_id"
            " LEFT JOIN doctors d ON d.id = l.doctor_id LEFT JOIN lab_callouts c ON c.lab_order_id = l.id"
            " LEFT JOIN lab_orders r ON r.id = l.reflex_of"
            f" WHERE l.status <> 'Cancelled'{f} ORDER BY CASE l.status WHEN 'Validated' THEN 1 ELSE 0 END,"
            " (c.status = 'Open') DESC, l.ordered_at DESC LIMIT 200", p)
        for r in rows:
            r["value_text"] = diagnostics.fmt_value(r["result_value"]) if r["result_value"] is not None else "—"
            r["mark"] = FLAG_TEXT.get(r["flag"] or "", "")
            lo, hi = r["ref_low"], r["ref_high"]
            r["ref_text"] = ("< " + diagnostics.fmt_value(hi)) if lo is None and hi is not None else \
                (f"{diagnostics.fmt_value(lo)}–{diagnostics.fmt_value(hi)}" if lo is not None and hi is not None else "—")
            r["ago"] = _ago(r["ordered_at"], now)
            r["reflex_name"] = None
            if r["reflex_of"]:
                parent = db.one("SELECT t.name FROM lab_orders l JOIN lab_tests t ON t.code = l.test_code WHERE l.id = ?", (r["reflex_of"],))
                r["reflex_name"] = parent["name"] if parent else None
        children = {r["reflex_of"]: r for r in rows if r["reflex_of"]}
        for r in rows:
            r["reflex_child"] = children.get(r["id"])
        ctx.update(rows=rows, kpis=diagnostics.lab_kpis(branch),
                   tests=db.query("SELECT code, name, price FROM lab_tests ORDER BY name"),
                   can_validate=user["role"] in VALIDATE_ROLES, can_lab=user["role"] in LAB_ROLES)
    elif tab == "rad":
        rows = db.query(
            "SELECT r.*, p.name AS patient_name, p.uid FROM rad_orders r JOIN patients p ON p.id = r.patient_id"
            f" WHERE r.status <> 'Cancelled'{f.replace('l.', 'r.')} ORDER BY CASE r.status WHEN 'Reported' THEN 1 ELSE 0 END, r.slot_at", p)
        ctx.update(rows=rows, can_rad=user["role"] in RAD_ROLES,
                   counts={s: sum(1 for r in rows if r["status"] == s) for s in diagnostics.RAD_FLOW})
    else:
        rxs = db.query(
            "SELECT x.*, p.name AS patient_name, p.uid, d.name AS doctor_name FROM prescriptions x JOIN patients p ON p.id = x.patient_id"
            f" LEFT JOIN doctors d ON d.id = x.doctor_id WHERE 1=1{f.replace('l.', 'x.')}"
            " ORDER BY CASE x.status WHEN 'Pending' THEN 0 WHEN 'Dispensed' THEN 1 ELSE 2 END, x.created_at DESC", p)
        for x in rxs:
            x["items"] = db.query("SELECT i.*, g.name, g.schedule, b.batch_no, b.expiry FROM prescription_items i"
                                  " JOIN drugs g ON g.code = i.drug_code LEFT JOIN drug_batches b ON b.id = i.batch_id"
                                  " WHERE i.prescription_id = ? ORDER BY i.id", (x["id"],))
            x["total"] = sum((i["amount"] or 0) for i in x["items"])
        reg = db.query("SELECT * FROM schedule_register" + (" WHERE branch_id = ?" if branch else "") + " ORDER BY id DESC LIMIT 20",
                       (branch,) if branch else ())
        near = db.query("SELECT b.*, g.name FROM drug_batches b JOIN drugs g ON g.code = b.drug_code WHERE b.qty > 0 AND b.expiry <= ?"
                        + (" AND b.branch_id = ?" if branch else "") + " ORDER BY b.expiry LIMIT 8",
                        ((now.date() + timedelta(days=90)).isoformat(), *((branch,) if branch else ())))
        ctx.update(rxs=rxs, register=reg, near_expiry=near, can_rx=user["role"] in RX_ROLES)
    return ui.render(request, "diagnostics.html", user, **ctx)


async def _post(request: Request, roles: set[str]) -> tuple[dict, dict]:
    user = await auth.require_post(request, roles)
    return user, dict(await request.form())


@router.post("/diagnostics/lab/order")
async def lab_order(request: Request):
    user, form = await _post(request, LAB_ROLES)
    try:
        p = _patient_from_form(form)
        lid = diagnostics.create_lab_order(p["id"], _branch_for(user, form), str(form.get("test_code", "")), actor=auth.actor(user))
    except (diagnostics.RuleError, ValueError) as e:
        return _back(_tab_url("lab"), err=str(e))
    return _back(_tab_url("lab", f"lab-{lid}"), msg=f"Test ordered for {p['name']}. It is on the bill as an unbilled service until added.")


@router.post("/diagnostics/lab/{lab_id}/advance")
async def lab_advance(request: Request, lab_id: int):
    user, _ = await _post(request, LAB_ROLES)
    _own(user, "lab_orders", lab_id, "lab test")
    try:
        new = diagnostics.advance(lab_id, actor=auth.actor(user))
    except diagnostics.RuleError as e:
        return _back(_tab_url("lab", f"lab-{lab_id}"), err=str(e))
    return _back(_tab_url("lab", f"lab-{lab_id}"), msg=f"Moved to {new}.")


@router.post("/diagnostics/lab/{lab_id}/result")
async def lab_result(request: Request, lab_id: int):
    user, form = await _post(request, LAB_ROLES)
    _own(user, "lab_orders", lab_id, "lab test")
    raw = str(form.get("value", "")).replace(",", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return _back(_tab_url("lab", f"lab-{lab_id}"), err="Enter the result as a number, for example 4.2")
    try:
        out = diagnostics.enter_result(lab_id, value, actor=auth.actor(user))
    except diagnostics.RuleError as e:
        return _back(_tab_url("lab", f"lab-{lab_id}"), err=str(e))
    if out["flag"] in ("LL", "HH"):
        msg = "Critical value. Call the doctor now and record the call-out with read-back."
    elif out["auto_validated"]:
        msg = "Normal result: passed checks and auto-verified."
    else:
        msg = "Result saved. It waits for a pathologist to validate."
    if out["reflex"]:
        msg += " Reflex test added automatically."
    return _back(_tab_url("lab", f"lab-{lab_id}"), msg=msg)


@router.post("/diagnostics/lab/{lab_id}/validate")
async def lab_validate(request: Request, lab_id: int):
    user, _ = await _post(request, VALIDATE_ROLES)
    _own(user, "lab_orders", lab_id, "lab test")
    try:
        diagnostics.validate(lab_id, actor=auth.actor(user))
    except diagnostics.RuleError as e:
        return _back(_tab_url("lab", f"lab-{lab_id}"), err=str(e))
    return _back(_tab_url("lab", f"lab-{lab_id}"), msg="Validated. The patient can now see this result in their app.")


@router.post("/diagnostics/lab/{lab_id}/callout")
async def lab_callout(request: Request, lab_id: int):
    user, form = await _post(request, LAB_ROLES)
    _own(user, "lab_orders", lab_id, "lab test")
    try:
        diagnostics.call_out(lab_id, called_to=str(form.get("called_to", "")), read_back=form.get("read_back") == "1",
                             actor=auth.actor(user))
    except diagnostics.RuleError as e:
        return _back(_tab_url("lab", f"lab-{lab_id}"), err=str(e))
    return _back(_tab_url("lab", f"lab-{lab_id}"), msg="Call-out recorded with read-back.")


@router.post("/diagnostics/rad/order")
async def rad_order(request: Request):
    user, form = await _post(request, RAD_ROLES)
    try:
        p = _patient_from_form(form)
        slot = str(form.get("slot_at", "")).replace("T", " ")
        if len(slot) == 16:
            slot += ":00"
        util.parse(slot)
        rid = diagnostics.create_rad_order(p["id"], _branch_for(user, form), str(form.get("modality", "")),
                                           str(form.get("study", "")), slot, obstetric=form.get("obstetric") == "1",
                                           actor=auth.actor(user))
    except (diagnostics.RuleError, ValueError) as e:
        return _back(_tab_url("rad"), err=str(e) if isinstance(e, diagnostics.RuleError) else "Choose a date and time for the scan")
    return _back(_tab_url("rad", f"rad-{rid}"), msg="Scan scheduled.")


@router.post("/diagnostics/rad/{rad_id}/advance")
async def rad_advance(request: Request, rad_id: int):
    user, form = await _post(request, RAD_ROLES)
    _own(user, "rad_orders", rad_id, "scan")
    try:
        new = diagnostics.advance_rad(rad_id, actor=auth.actor(user), form_f=form.get("form_f") == "1",
                                      report_text=str(form.get("report_text", "")))
    except diagnostics.RuleError as e:
        return _back(_tab_url("rad", f"rad-{rad_id}"), err=str(e))
    return _back(_tab_url("rad", f"rad-{rad_id}"), msg=f"Marked {new.lower()}.")


@router.post("/diagnostics/rx/{rx_id}/advance")
async def rx_advance(request: Request, rx_id: int):
    user, _ = await _post(request, RX_ROLES)
    _own(user, "prescriptions", rx_id, "prescription")
    try:
        new = diagnostics.advance_rx(rx_id, actor=auth.actor(user))
    except (diagnostics.RuleError, ValueError) as e:
        return _back(_tab_url("rx", f"rx-{rx_id}"), err=str(e))
    msg = "Dispensed from the earliest-expiry batches. Schedule drugs were written to the register." if new == "Dispensed" \
        else "Bill created. Collect payment from Billing."
    return _back(_tab_url("rx", f"rx-{rx_id}"), msg=msg)
