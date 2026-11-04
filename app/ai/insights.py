"""AI morning insights for the owner. Every number in the output must exist in the input data;
any insight with an invented number is dropped and audited."""
import json
import re
from datetime import datetime, timedelta

from pydantic import BaseModel

from app import audit, db, metrics, util
from app.ai import client as ai
from app.ai import prompts

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


class Insights(BaseModel):
    insights: list[str]
    action: str


def build_metrics(now: datetime) -> dict:
    y = now.date() - timedelta(days=1)
    week = metrics.collections_by_day(y, 7)
    branches = db.query("SELECT id, name FROM branches ORDER BY id")
    data = {"date": y.isoformat(), "branches": {}}
    for b in branches:
        k = metrics.kpis(y, b["id"])
        avg = round(sum(r[b["id"]] for r in week) / len(week))
        data["branches"][b["name"]] = {
            "opd_patients_yesterday": k["opd"],
            "appointments_booked_yesterday": k["booked"],
            "billed_yesterday": util.inr(k["billed"]),
            "collected_yesterday": util.inr(k["collected"]),
            "collected_7_day_average": util.inr(avg),
            "outstanding_dues": util.inr(k["dues"]),
            "no_show_rate_30_days": f"{k['no_show_pct']}%",
        }
    a = metrics.attention()
    data["open_issues"] = {
        "insurance_claims_past_time_limit": a["claims_stuck"],
        "services_not_yet_billed": util.inr(a["unbilled_amount"]),
        "missed_calls_not_returned": a["missed_calls_open"],
        "open_complaints": a["complaints_open"],
    }
    return data


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(text)}


def verify(lines: list[str], data: dict) -> tuple[list[str], list[str]]:
    """Split lines into (kept, dropped): a line is kept only if all its numbers appear in the data."""
    allowed = _numbers(json.dumps(data, ensure_ascii=False)) | {"7", "30"}   # the window lengths named in the data
    kept, dropped = [], []
    for line in lines:
        (kept if _numbers(line) <= allowed else dropped).append(line)
    return kept, dropped


def owner_insight(now: datetime, client=None) -> str | None:
    """Return the AI insight block for the owner report, or None when AI is off or nothing passes checks."""
    if client is None and not ai.enabled():
        return None
    data = build_metrics(now)
    try:
        out = ai.structured(system=prompts.INSIGHTS_V1,
                            user="<metrics>\n" + json.dumps(data, ensure_ascii=False, indent=1) + "\n</metrics>",
                            output=Insights, effort="medium", max_tokens=4096, client=client)
    except ai.AIError as e:
        audit.log("ai", "ai_error", "owner_insight", None, {"error": str(e), "prompt": prompts.INSIGHTS_VERSION})
        return None
    kept, dropped = verify([s.strip() for s in out.insights[:3] if s.strip()], data)
    action_ok, action_bad = verify([out.action.strip()] if out.action.strip() else [], data)
    if dropped or action_bad:
        audit.log("ai", "ai_insight_dropped", "owner_insight", None,
                  {"dropped": dropped + action_bad, "reason": "number not found in metrics", "prompt": prompts.INSIGHTS_VERSION})
    if not kept and not action_ok:
        return None
    lines = ["AI insights:"] + [f"• {s}" for s in kept]
    if action_ok:
        lines.append(f"Suggested action: {action_ok[0]}")
    return "\n".join(lines)
