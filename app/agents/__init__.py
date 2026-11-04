"""AI Labs: agents that watch the hospital's data and raise findings for a person to decide.

An agent never changes a bill, claim or stock record on its own. It writes a finding (what it saw,
the evidence, and a suggested action). A person accepts it, which runs that one safe action, or
dismisses it with a reason. Every run, decision and action is in the audit log.
"""
import json
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from app import audit, db, util

SEVERITIES = ("info", "low", "medium", "high")


@dataclass(frozen=True)
class Agent:
    name: str
    title: str
    description: str
    interval_minutes: int
    run: Callable[[datetime], list[dict]]     # returns findings: dict(key, severity, title, evidence, suggested_action, ...)


REGISTRY: dict[str, Agent] = {}


def register(agent: Agent) -> Agent:
    REGISTRY[agent.name] = agent
    return agent


# The owner briefing is the existing 9 am automation; its switch lives there.
_AUTOMATION_SWITCH = {"owner_briefing": "daily_owner_report"}


def is_enabled(name: str) -> bool:
    if name not in REGISTRY:
        raise KeyError(f"Unknown agent {name!r}")
    if name in _AUTOMATION_SWITCH:
        from app import automations
        return automations.is_enabled(_AUTOMATION_SWITCH[name])
    return db.get_setting(f"agent_{name}", "on") == "on"


def set_enabled(name: str, on: bool, actor: str) -> None:
    if name not in REGISTRY:
        raise KeyError(f"Unknown agent {name!r}")
    if name in _AUTOMATION_SWITCH:
        from app import automations
        automations.set_enabled(_AUTOMATION_SWITCH[name], on)
    else:
        db.set_setting(f"agent_{name}", "on" if on else "off")
    audit.log(actor, "agent_" + ("enabled" if on else "disabled"), "agent", None, {"agent": name})


def last_run(name: str) -> dict | None:
    return db.one("SELECT * FROM agent_runs WHERE agent = ?", (name,))


def run_agent(name: str, now: datetime, actor: str = "agent") -> dict:
    """Run one agent: add new findings, refresh open ones, close the ones that resolved themselves."""
    agent = REGISTRY[name]
    found = agent.run(now)
    ts = util.ts(now)
    keys = set()
    new = 0
    for f in found:
        if f["severity"] not in SEVERITIES:
            raise ValueError(f"{name}: bad severity {f['severity']!r}")
        keys.add(f["key"])
        evidence = json.dumps(f["evidence"], ensure_ascii=False, default=str)
        action = json.dumps(f["action"]) if f.get("action") else None
        with db.connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO findings(agent, dedupe_key, severity, title, evidence, suggested_action, action,"
                " amount, branch_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (name, f["key"], f["severity"], f["title"], evidence, f["suggested_action"], action, f.get("amount"),
                 f.get("branch_id"), ts))
            if cur.rowcount == 1:
                new += 1
            else:
                conn.execute("UPDATE findings SET severity = ?, title = ?, evidence = ?, suggested_action = ?, action = ?,"
                             " amount = ? WHERE agent = ? AND dedupe_key = ? AND status = 'open'",
                             (f["severity"], f["title"], evidence, f["suggested_action"], action, f.get("amount"),
                              name, f["key"]))
    resolved = 0
    for row in db.query("SELECT id, dedupe_key FROM findings WHERE agent = ? AND status = 'open'", (name,)):
        if row["dedupe_key"] not in keys:
            db.execute("UPDATE findings SET status = 'dismissed', decided_by = 'agent', decided_at = ?,"
                       " decision_note = 'Resolved on its own' WHERE id = ?", (ts, row["id"]))
            resolved += 1
    result = {"found": len(found), "new": new, "resolved": resolved}
    db.execute("INSERT INTO agent_runs(agent, last_run_at, last_result) VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE"
               " SET last_run_at = excluded.last_run_at, last_result = excluded.last_result",
               (name, ts, json.dumps(result)))
    audit.log(actor, "agent_run", "agent", None, {"agent": name, **result})
    return result


def run_due(now: datetime) -> dict:
    """Run every enabled agent whose interval has passed. One agent failing never stops the others."""
    out = {}
    for name, agent in REGISTRY.items():
        if not is_enabled(name):
            continue
        lr = last_run(name)
        if lr and now - util.parse(lr["last_run_at"]) < timedelta(minutes=agent.interval_minutes):
            continue
        try:
            out[name] = run_agent(name, now)
        except Exception as e:  # noqa: BLE001 - report and keep the other agents running
            traceback.print_exc(file=sys.stderr)
            audit.log("agent", "agent_error", "agent", None, {"agent": name, "error": f"{type(e).__name__}: {e}"})
            out[name] = {"error": str(e)}
    return out


# Import the agents so they register themselves.
from app.agents import claims_docs, followup_churn, owner_briefing, revenue_loss, stock_expiry  # noqa: E402,F401
