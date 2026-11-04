"""Stock and expiry agent: medicines that will expire before they are used, and stock below reorder level."""
from collections import defaultdict
from datetime import date, datetime

from app import db, util
from app.agents import Agent, register

HORIZON_DAYS = 90


def _projected_surplus(now: datetime) -> list[dict]:
    """Per batch: units still left at expiry if each item is used first-expiry-first-out at its daily rate."""
    today = now.date()
    rows = db.query("SELECT b.*, i.name, i.branch_id, i.daily_usage, i.unit FROM stock_batches b"
                    " JOIN stock_items i ON i.id = b.item_id WHERE b.qty > 0 ORDER BY b.item_id, b.expiry_date")
    by_item = defaultdict(list)
    for r in rows:
        by_item[r["item_id"]].append(r)
    out = []
    for batches in by_item.values():
        used_before = 0.0                                 # units consumed by earlier-expiring batches
        for b in batches:
            days_left = (date.fromisoformat(b["expiry_date"]) - today).days
            capacity = max(0.0, b["daily_usage"] * max(days_left, 0) - used_before)
            usable = min(b["qty"], capacity)
            used_before += usable
            surplus = int(b["qty"] - usable)
            if days_left <= HORIZON_DAYS and surplus > 0:
                out.append({**b, "days_left": days_left, "surplus": surplus})
    return out


def run(now: datetime) -> list[dict]:
    out = []
    for b in _projected_surplus(now):
        value = b["surplus"] * b["unit_cost"]
        target = db.one("SELECT i.id, i.branch_id, i.daily_usage,"
                        " (SELECT COALESCE(SUM(qty),0) FROM stock_batches WHERE item_id = i.id) AS on_hand"
                        " FROM stock_items i WHERE i.name = ? AND i.branch_id != ? ORDER BY i.daily_usage DESC LIMIT 1",
                        (b["name"], b["branch_id"]))
        can_take = 0
        if target and b["days_left"] > 0:
            can_take = int(max(0.0, target["daily_usage"] * b["days_left"] - target["on_hand"]))
        qty = min(b["surplus"], can_take)
        if qty > 0:
            action = {"type": "stock_transfer", "batch_id": b["id"], "to_item_id": target["id"], "qty": qty}
            suggestion = f"Move {qty} {b['unit']} to Branch {target['branch_id']}, which will use them before expiry."
        elif b["days_left"] > 30:
            action, suggestion = None, f"Return {b['surplus']} {b['unit']} to the distributor while the return window is open."
        else:
            action, suggestion = None, f"Use these first and plan the write-off of about {b['surplus']} {b['unit']}."
        out.append({
            "key": f"expiry:{b['id']}", "severity": "high" if b["days_left"] <= 30 else "medium",
            "title": f"{b['name']} batch {b['batch_no']} expires in {b['days_left']} days with {b['surplus']} {b['unit']} unused",
            "evidence": {"batch_id": b["id"], "expiry_date": b["expiry_date"], "qty": b["qty"], "surplus": b["surplus"],
                         "daily_usage": b["daily_usage"], "value": value},
            "suggested_action": suggestion, "action": action, "amount": value, "branch_id": b["branch_id"],
        })
    for i in db.query("SELECT i.*, (SELECT COALESCE(SUM(qty),0) FROM stock_batches WHERE item_id = i.id) AS on_hand"
                      " FROM stock_items i WHERE i.reorder_level > 0"):
        if i["on_hand"] < i["reorder_level"]:
            out.append({
                "key": f"reorder:{i['id']}", "severity": "medium",
                "title": f"Low stock: {i['name']} at Branch {i['branch_id']} ({i['on_hand']} {i['unit']} left)",
                "evidence": {"item_id": i["id"], "on_hand": i["on_hand"], "reorder_level": i["reorder_level"],
                             "daily_usage": i["daily_usage"]},
                "suggested_action": f"Reorder at least {i['reorder_level'] * 2 - i['on_hand']} {i['unit']}.",
                "action": None, "branch_id": i["branch_id"],
            })
    return out


register(Agent("stock_expiry", "Stock and expiry",
               "Finds medicines that will expire before use and suggests a transfer or return; flags low stock.", 360, run))
